#!/usr/bin/env python3
"""Repository checks and builds for kando-plugins. Standard library only, so CI needs nothing but the runner's python3.

The Kando tool (kando-plugin, from the Kando repository) is the authority on whether a pack installs: it runs the exact checks Kando runs. This script adds what only this repository knows: the folder layout, who may publish under which publisher (publishers.json), the accepted licenses, the repository's size budget, version bumps, deterministic pack files, and keeping already published pack files byte-for-byte the same.

Subcommands:
  check  --repo DIR [--markdown FILE]
  pr     --repo DIR --base SHA --head SHA --author LOGIN [--override] [--markdown FILE]
  build  --repo DIR --out DIR
  carry  --origin URL --out DIR --site DIR [--keep-days N]
"""

import argparse
import base64
import datetime
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

MANIFEST = "kando-plugin.json"
MIB = 1 << 20

# Kando's limits per kind (apps/kando/plugins/validate.go limitsOf, script.go scriptMax): the largest pack file, the most files in it, and the most bytes they unpack to.
DATA_LIMITS = {"zip": 32 * MIB, "entries": 16, "bytes": 64 * MIB}
KIND_LIMITS = {
    "dictionary": {"zip": 200 * MIB, "entries": 64, "bytes": 1 << 30},
    "script": {"zip": 16 * MIB, "entries": 8, "bytes": 16 * MIB},
}

# The data kinds a pack folder may be filed under (plugins.Kind, all but script, which lives under scripts/).
DATA_KINDS = ["dictionary", "wordlist", "glossary", "ai-service", "translate-style", "task", "export-template", "site"]

# This repository's own budget: GitHub refuses files over 100 MiB and warns over 50 MiB, and a GitHub Pages site may be at most 1 GB.
REPO_FILE_MAX = 50 * MIB
PUBLISHED_FILE_MAX = 100 * MIB
SITE_MAX = 900 * MIB

# Licenses accepted for data packs: redistributable, including commercially, so the directory can serve the files to anyone. SPDX ids; an expression may join them with AND or OR.
DATA_LICENSES = {
    "CC0-1.0", "PDDL-1.0", "Unlicense",
    "CC-BY-3.0", "CC-BY-4.0", "CC-BY-SA-3.0", "CC-BY-SA-4.0",
    "ODC-By-1.0", "ODbL-1.0",
    "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "0BSD",
}
# Licenses accepted for script plugins' source: OSI-approved.
SCRIPT_LICENSES = {
    "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "0BSD", "Unlicense", "CC0-1.0",
    "MPL-2.0", "LGPL-3.0-only", "LGPL-3.0-or-later", "GPL-3.0-only", "GPL-3.0-or-later",
}

ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
FILE_PATTERN = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]*[A-Za-z0-9_-]$|^[A-Za-z0-9_-]$")
# A pack file's name: <id>-<version> and its extension, so a new version is always a new file and a published file is never replaced (Kando checks a download against the SHA-256 of the index it has cached).
VERSION_PATTERN = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+-]*$")

# The date every entry of a built pack file carries, so building the same folder twice gives the same bytes.
ZIP_DATE = (1980, 1, 1, 0, 0, 0)


class Report:
    """Errors and notes, printed as GitHub annotations and written as Markdown for the PR comment."""

    def __init__(self):
        self.errors = []
        self.notes = []
        self.units = {}
        # In a PR, the packs it touches: the comment lists those alone.
        self.only = None

    def error(self, where, message):
        self.errors.append((where, message))
        print(f"::error title={where}::{message}")

    def note(self, where, message):
        self.notes.append((where, message))
        print(f"::notice title={where}::{message}")

    def unit(self, key, **fields):
        self.units.setdefault(key, {}).update(fields)

    def markdown(self, title):
        out = [f"### {title}", ""]
        if self.units and (self.only is None or self.only):
            out += ["| Pack | Kind | Version | License | Publisher |", "|---|---|---|---|---|"]
            for key in sorted(k for k in self.units if self.only is None or k in self.only):
                u = self.units[key]
                out.append(f"| `{key}` | {u.get('kind', '')} | {u.get('version', '')} | {u.get('license', '')} | {u.get('publisher', '')} |")
            out.append("")
        if self.errors:
            out.append(f"**{len(self.errors)} problem(s):**")
            out.append("")
            out += [f"- `{w}`: {m}" for w, m in self.errors]
        else:
            out.append("No problems found.")
        if self.notes:
            out.append("")
            out += [f"- `{w}`: {m}" for w, m in self.notes]
        out.append("")
        return "\n".join(out)


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def limits(kind):
    return KIND_LIMITS.get(kind, DATA_LIMITS)


def license_ok(expr, allowed):
    parts = re.split(r"\s+(?:AND|OR)\s+", expr.strip().strip("()"))
    return bool(expr.strip()) and all(p.strip("() ") in allowed for p in parts)


def publishers(repo):
    data = load_json(os.path.join(repo, "publishers.json"))
    return data.get("maintainers", []), data.get("publishers", {})


def pack_file_name(pack_id, version, ext):
    return f"{pack_id}-{version}{ext}"


def check_data_pack(repo, kind, pack_id, pubs, report):
    """Checks packs/<kind>/<id>/ against this repository's rules and returns its manifest, or None."""
    where = f"packs/{kind}/{pack_id}"
    folder = os.path.join(repo, where)
    if os.path.islink(folder) or not os.path.isdir(folder):
        report.error(where, "is not a folder")
        return None
    if not ID_PATTERN.match(pack_id) or "." not in pack_id or len(pack_id) > 64:
        report.error(where, "the folder's name must be the pack's id, <publisher>.<name> in lowercase letters, digits, dots and hyphens, at most 64 bytes")
    names = sorted(os.listdir(folder))
    total = 0
    for name in names:
        path = os.path.join(folder, name)
        if os.path.islink(path) or not os.path.isfile(path):
            report.error(f"{where}/{name}", "a pack holds plain files only: no folder, link or special file")
            continue
        if name.startswith(".") or not FILE_PATTERN.match(name) or len(name) > 100:
            report.error(f"{where}/{name}", "file names are ASCII letters, digits, '.', '-' and '_', not starting or ending with a dot, at most 100 bytes")
        size = os.path.getsize(path)
        total += size
        if size > REPO_FILE_MAX:
            report.error(f"{where}/{name}", f"is {size / MIB:.1f} MiB; this repository takes files of at most {REPO_FILE_MAX // MIB} MiB")
    lim = limits(kind)
    if len(names) > lim["entries"]:
        report.error(where, f"has {len(names)} files; a {kind} pack has at most {lim['entries']}")
    if total > lim["bytes"]:
        report.error(where, f"holds {total / MIB:.1f} MiB; a {kind} pack holds at most {lim['bytes'] // MIB} MiB")
    if MANIFEST not in names:
        report.error(where, f"has no {MANIFEST}")
        return None
    try:
        m = load_json(os.path.join(folder, MANIFEST))
    except (OSError, ValueError) as e:
        report.error(f"{where}/{MANIFEST}", f"is not valid JSON: {e}")
        return None
    if not isinstance(m, dict):
        report.error(f"{where}/{MANIFEST}", "is not a JSON object")
        return None
    if m.get("id") != pack_id:
        report.error(f"{where}/{MANIFEST}", f"id {m.get('id')!r} is not the folder's name {pack_id!r}")
    if m.get("kind") != kind:
        report.error(f"{where}/{MANIFEST}", f"kind {m.get('kind')!r} is not the folder it is filed under ({kind})")
    if m.get("schema") != 1:
        report.error(f"{where}/{MANIFEST}", "a data pack's schema is 1")
    version = m.get("version", "")
    if not isinstance(version, str) or not VERSION_PATTERN.match(version) or len(version) > 32:
        report.error(f"{where}/{MANIFEST}", f"version {version!r} is letters, digits, '.', '+' and '-', at most 32 bytes")
    lic = m.get("license", "")
    if not isinstance(lic, str) or not license_ok(lic, DATA_LICENSES):
        report.error(f"{where}/{MANIFEST}", f"license {lic!r} is not one this directory accepts for data (CONTRIBUTING.md, Licensing)")
    publisher = pack_id.split(".")[0]
    if publisher == "kando":
        report.error(where, "the publisher kando is reserved for Kando's signed script plugins; Kando refuses a data pack under it. The Kando team publishes data packs as yldm")
    elif publisher not in pubs:
        report.error(where, f"publisher {publisher!r} is not registered in publishers.json (CONTRIBUTING.md, Publishers)")
    report.unit(pack_id, kind=kind, version=version, license=lic, publisher=publisher)
    return m


def read_plugin_zip(path):
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        if MANIFEST not in z.namelist():
            return infos, None
        # Kando reads at most 256 KiB of a manifest; the file is untrusted, so nothing larger is unpacked.
        if z.getinfo(MANIFEST).file_size > 256 << 10:
            raise ValueError(f"{MANIFEST} is over 256 KiB")
        with z.open(MANIFEST) as f:
            manifest = json.loads(f.read((256 << 10) + 1))
    return infos, manifest


def without_script(m):
    return {k: v for k, v in m.items() if k != "script"}


def check_script(repo, pack_id, pubs, report):
    """Checks scripts/<id>/: one signed <id>-<version>.kandoplugin and its source in src/, whose kando-plugin.json is the packaged one but for the script field."""
    where = f"scripts/{pack_id}"
    folder = os.path.join(repo, where)
    if os.path.islink(folder) or not os.path.isdir(folder):
        report.error(where, "is not a folder")
        return None
    plugins = [n for n in os.listdir(folder) if n.endswith(".kandoplugin")]
    if len(plugins) != 1:
        report.error(where, f"holds {len(plugins)} .kandoplugin files; it holds exactly one, the version to list")
        return None
    name = plugins[0]
    path = os.path.join(folder, name)
    size = os.path.getsize(path)
    if size > limits("script")["zip"]:
        report.error(f"{where}/{name}", f"is {size / MIB:.1f} MiB; a script plugin is at most {limits('script')['zip'] // MIB} MiB")
    try:
        infos, m = read_plugin_zip(path)
    except (OSError, ValueError, zipfile.BadZipFile, KeyError) as e:
        report.error(f"{where}/{name}", f"cannot be read as a .kandoplugin: {e}")
        return None
    if len(infos) > limits("script")["entries"]:
        report.error(f"{where}/{name}", f"has {len(infos)} entries; a script plugin has at most {limits('script')['entries']}")
    if not isinstance(m, dict):
        report.error(f"{where}/{name}", f"has no {MANIFEST} at its top level")
        return None
    version = m.get("version", "")
    if m.get("id") != pack_id or m.get("kind") != "script":
        report.error(f"{where}/{name}", f"is {m.get('kind')!r} {m.get('id')!r}, not the script plugin {pack_id!r} its folder names")
    if name != pack_file_name(pack_id, version, ".kandoplugin"):
        report.error(f"{where}/{name}", f"is named {pack_file_name(pack_id, version, '.kandoplugin')} for the version it holds")
    lic = m.get("license", "")
    if not isinstance(lic, str) or not license_ok(lic, SCRIPT_LICENSES):
        report.error(f"{where}/{name}", f"license {lic!r} is not one this directory accepts for script plugins (CONTRIBUTING.md, Licensing)")
    src = os.path.join(folder, "src")
    src_manifest = os.path.join(src, MANIFEST)
    if not os.path.isdir(src) or not os.path.isfile(src_manifest):
        report.error(where, f"has no src/{MANIFEST}: the source of the signed plugin is required for review")
    else:
        try:
            if without_script(load_json(src_manifest)) != without_script(m):
                report.error(f"{where}/src/{MANIFEST}", "differs from the manifest inside the signed .kandoplugin (the script field aside): commit the source the plugin was built from")
        except (OSError, ValueError) as e:
            report.error(f"{where}/src/{MANIFEST}", f"is not valid JSON: {e}")
        if not any(n.endswith(".tsx") or n.endswith(".ts") for n in os.listdir(src)):
            report.error(f"{where}/src", "holds no .tsx or .ts entry")
    for root, dirs, files in os.walk(folder):
        for n in files + dirs:
            p = os.path.join(root, n)
            if os.path.islink(p):
                report.error(os.path.relpath(p, repo), "links are not allowed")
            elif os.path.isfile(p) and os.path.getsize(p) > REPO_FILE_MAX:
                report.error(os.path.relpath(p, repo), f"is over {REPO_FILE_MAX // MIB} MiB")
    publisher = pack_id.split(".")[0]
    pub = pubs.get(publisher)
    if pub is None:
        report.error(where, f"publisher {publisher!r} is not registered in publishers.json")
    elif not pub.get("scripts"):
        report.error(where, f"publisher {publisher!r} is not certified for script plugins (CONTRIBUTING.md, Script plugins)")
    report.unit(pack_id, kind="script", version=version, license=lic, publisher=publisher)
    return m


def units(repo):
    """Every pack folder of the repository: (where, kind, id)."""
    out = []
    packs = os.path.join(repo, "packs")
    if os.path.isdir(packs):
        for kind in sorted(os.listdir(packs)):
            for pack_id in sorted(os.listdir(os.path.join(packs, kind))) if os.path.isdir(os.path.join(packs, kind)) else []:
                out.append((f"packs/{kind}/{pack_id}", kind, pack_id))
    scripts = os.path.join(repo, "scripts")
    if os.path.isdir(scripts):
        for pack_id in sorted(os.listdir(scripts)):
            out.append((f"scripts/{pack_id}", "script", pack_id))
    return out


def check_repo(repo, report):
    _, pubs = publishers(repo)
    packs = os.path.join(repo, "packs")
    if os.path.isdir(packs):
        for kind in sorted(os.listdir(packs)):
            if kind not in DATA_KINDS or not os.path.isdir(os.path.join(packs, kind)):
                report.error(f"packs/{kind}", f"is not a data kind's folder ({', '.join(DATA_KINDS)}); script plugins go under scripts/")
    seen = {}
    for where, kind, pack_id in units(repo):
        if kind not in DATA_KINDS and kind != "script":
            continue
        if kind == "script":
            check_script(repo, pack_id, pubs, report)
        else:
            check_data_pack(repo, kind, pack_id, pubs, report)
        if pack_id in seen:
            report.error(where, f"id {pack_id} is also at {seen[pack_id]}: an id is one pack across every kind")
        seen[pack_id] = where
    return report


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True).stdout


def git_exists(repo, rev, path):
    return subprocess.run(["git", "-C", repo, "cat-file", "-e", f"{rev}:{path}"], capture_output=True).returncode == 0


def compare_versions(a, b):
    """index.Newer's order: dotted parts, numbers as numbers, a pre-release (-x) before the release, build metadata (+x) ignored."""
    def split(v):
        v = v.split("+", 1)[0]
        core, _, pre = v.partition("-")
        return core.split("."), ("-" in v), pre

    def part(x, y):
        xd, yd = x.isdigit(), y.isdigit()
        if xd and yd:
            return (int(x) > int(y)) - (int(x) < int(y))
        if xd:
            return -1
        if yd:
            return 1
        return (x > y) - (x < y)

    ac, apre, ap = split(a)
    bc, bpre, bp = split(b)
    for i in range(max(len(ac), len(bc))):
        c = part(ac[i] if i < len(ac) else "0", bc[i] if i < len(bc) else "0")
        if c:
            return c
    if apre != bpre:
        return -1 if apre else 1
    return (ap > bp) - (ap < bp)


def unit_version(repo, rev, where, kind):
    """The version of the pack at where in rev ("" for the working tree), or None when it is not there."""
    if kind == "script":
        if rev:
            if not git_exists(repo, rev, where):
                return None
            names = git(repo, "ls-tree", "--name-only", rev, where + "/").split()
        else:
            if not os.path.isdir(os.path.join(repo, where)):
                return None
            names = os.listdir(os.path.join(repo, where))
        found = [os.path.basename(n) for n in names if n.endswith(".kandoplugin")]
        prefix = where.split("/")[1] + "-"
        if len(found) != 1 or not found[0].startswith(prefix):
            return None
        return found[0][len(prefix):-len(".kandoplugin")]
    path = f"{where}/{MANIFEST}"
    try:
        if rev:
            if not git_exists(repo, rev, path):
                return None
            m = json.loads(git(repo, "show", f"{rev}:{path}"))
        else:
            if not os.path.isfile(os.path.join(repo, path)):
                return None
            m = load_json(os.path.join(repo, path))
        return m.get("version")
    except (ValueError, subprocess.CalledProcessError, AttributeError):
        return None


def check_pr(repo, base, head, author, override, report):
    maintainers, base_pubs = publishers(repo)
    # Ownership is judged by the publishers.json of the base branch, so a PR cannot register its own author.
    if git_exists(repo, base, "publishers.json"):
        base_data = json.loads(git(repo, "show", f"{base}:publishers.json"))
        maintainers, base_pubs = base_data.get("maintainers", []), base_data.get("publishers", {})
    trusted = author in maintainers or override
    if override:
        report.note("PR", "a maintainer applied the `maintainer-override` label: publisher ownership and maintainer-only paths are not enforced")
    changed = [p for p in git(repo, "diff", "--name-only", "--no-renames", f"{base}...{head}").splitlines() if p]
    touched = {}
    for path in changed:
        parts = path.split("/")
        if parts[0] == "packs" and len(parts) >= 4:
            touched[f"packs/{parts[1]}/{parts[2]}"] = (parts[1], parts[2])
        elif parts[0] == "scripts" and len(parts) >= 3:
            touched[f"scripts/{parts[1]}"] = ("script", parts[1])
        elif not trusted:
            report.error(path, "only maintainers change files outside packs/ and scripts/; ask for the maintainer-override label if this change is meant")
    report.only = {pack_id for _, pack_id in touched.values()}
    for where, (kind, pack_id) in sorted(touched.items()):
        publisher = pack_id.split(".")[0]
        owners = base_pubs.get(publisher, {}).get("github", [])
        if not trusted and author not in owners:
            if publisher in base_pubs:
                report.error(where, f"publisher {publisher!r} belongs to {', '.join('@' + o for o in owners) or 'nobody'}; @{author} may only add or change packs under their own publisher")
            else:
                report.error(where, f"publisher {publisher!r} is not registered; open a 'New publisher' issue first (CONTRIBUTING.md, Publishers)")
        old, new = unit_version(repo, base, where, kind), unit_version(repo, "", where, kind)
        if new is None:
            report.note(where, "removed: it leaves the index on merge; installed copies are not affected")
        elif old is not None and compare_versions(new, old) <= 0:
            report.error(where, f"changed without a newer version ({old} -> {new}): every change to a published pack needs a higher version, as its file name carries the version and published files never change")
    return report


def build(repo, out):
    """Writes each data pack folder as <id>-<version>.kandopack and copies each signed script plugin, into out. The zips are deterministic: entries sorted, at the top level, with a fixed date and mode."""
    os.makedirs(out, exist_ok=True)
    built = []
    for where, kind, pack_id in units(repo):
        folder = os.path.join(repo, where)
        if kind == "script":
            names = [n for n in os.listdir(folder) if n.endswith(".kandoplugin")]
            if len(names) != 1:
                raise SystemExit(f"{where}: needs exactly one .kandoplugin (run check)")
            with open(os.path.join(folder, names[0]), "rb") as f:
                data = f.read()
            name = names[0]
        else:
            m = load_json(os.path.join(folder, MANIFEST))
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                for n in sorted(os.listdir(folder)):
                    info = zipfile.ZipInfo(n, date_time=ZIP_DATE)
                    info.create_system = 3
                    info.external_attr = 0o100644 << 16
                    # A Yomitan dictionary is a zip already: stored, not compressed again.
                    info.compress_type = zipfile.ZIP_STORED if n.lower().endswith(".zip") else zipfile.ZIP_DEFLATED
                    with open(os.path.join(folder, n), "rb") as f:
                        z.writestr(info, f.read(), compresslevel=9)
            data = buf.getvalue()
            name = pack_file_name(pack_id, m["version"], ".kandopack")
            if len(data) > limits(kind)["zip"]:
                raise SystemExit(f"{where}: its pack file is {len(data) / MIB:.1f} MiB, over Kando's {limits(kind)['zip'] // MIB} MiB for a {kind} pack")
        if len(data) > PUBLISHED_FILE_MAX:
            raise SystemExit(f"{where}: its pack file is {len(data) / MIB:.1f} MiB, over the {PUBLISHED_FILE_MAX // MIB} MiB this directory publishes")
        with open(os.path.join(out, name), "wb") as f:
            f.write(data)
        built.append((name, len(data)))
    total = sum(s for _, s in built)
    if total > SITE_MAX:
        raise SystemExit(f"the pack files come to {total / MIB:.1f} MiB, over the site budget of {SITE_MAX // MIB} MiB")
    for name, size in built:
        print(f"{name}\t{size}")
    return built


def fetch(url, max_bytes):
    req = urllib.request.Request(url, headers={"User-Agent": "kando-plugins-publish"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read(max_bytes + 1)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    if len(data) > max_bytes:
        raise SystemExit(f"{url}: over {max_bytes} bytes")
    return data


def zip_contents(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return {i.filename: z.read(i) for i in z.infolist()}


def carry(origin, out, site, keep_days, now=None):
    """Keeps published pack files the same and available a while after they leave the index.

    For every pack file the live index lists: when this build made a file of the same name (the same id and version), the live bytes replace the new ones once their contents are found equal, so a Kando that cached the live index still gets the SHA-256 it expects whatever zlib the runner has; equal names with other contents stop the publish, as that is a pack changed without a new version. A live file this build no longer has (an older version, a removed pack) is copied into the site's packs folder and recorded in carried.json, and kept there for keep_days, so a Kando with a cached index can still download it until its daily refresh.
    """
    now = now or datetime.datetime.now(datetime.timezone.utc)
    origin = origin.rstrip("/")
    packs_dir = os.path.join(site, "packs")
    os.makedirs(packs_dir, exist_ok=True)
    raw = fetch(f"{origin}/index.json", 4 << 20)
    live = {}
    if raw is None:
        print("no live index: first publish, nothing to carry")
    else:
        body = json.loads(base64.b64decode(json.loads(raw)["body"]))
        for e in body.get("entries", []):
            name = urllib.parse.unquote(e["url"].rsplit("/", 1)[1])
            live[name] = {"sha256": e["sha256"], "size": e["size"]}
    raw_carried = fetch(f"{origin}/carried.json", 1 << 20)
    carried = json.loads(raw_carried) if raw_carried else {}
    keep = {}
    for name, info in carried.items():
        since = datetime.datetime.fromisoformat(info["since"])
        if name not in live and now - since < datetime.timedelta(days=keep_days):
            keep[name] = info
    for name, info in live.items():
        if name not in os.listdir(out):
            keep.setdefault(name, {"sha256": info["sha256"], "size": info["size"], "since": now.isoformat(timespec="seconds")})
    for name, info in live.items():
        if name in os.listdir(out):
            data = download(origin, name, info)
            with open(os.path.join(out, name), "rb") as f:
                fresh = f.read()
            if zip_contents(data) != zip_contents(fresh):
                raise SystemExit(f"{name}: its contents differ from the published file of the same name; a changed pack needs a new version")
            with open(os.path.join(out, name), "wb") as f:
                f.write(data)
            print(f"kept the published bytes of {name}")
    for name, info in sorted(keep.items()):
        if name in os.listdir(out):
            continue
        data = download(origin, name, info)
        with open(os.path.join(packs_dir, name), "wb") as f:
            f.write(data)
        print(f"carried {name} (since {info['since']})")
    with open(os.path.join(site, "carried.json"), "w", encoding="utf-8") as f:
        json.dump({n: i for n, i in keep.items() if n not in os.listdir(out)}, f, indent=2, sort_keys=True)
        f.write("\n")


def download(origin, name, info):
    data = fetch(f"{origin}/packs/{urllib.parse.quote(name)}", PUBLISHED_FILE_MAX)
    if data is None:
        raise SystemExit(f"{name}: listed as published but the site does not have it")
    if len(data) != info["size"] or hashlib.sha256(data).hexdigest() != info["sha256"]:
        raise SystemExit(f"{name}: the published file does not match its SHA-256 and size")
    return data


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--repo", default=".")
    c.add_argument("--markdown")
    p = sub.add_parser("pr")
    p.add_argument("--repo", default=".")
    p.add_argument("--base", required=True)
    p.add_argument("--head", required=True)
    p.add_argument("--author", required=True)
    p.add_argument("--override", action="store_true")
    p.add_argument("--markdown")
    b = sub.add_parser("build")
    b.add_argument("--repo", default=".")
    b.add_argument("--out", required=True)
    k = sub.add_parser("carry")
    k.add_argument("--origin", required=True)
    k.add_argument("--out", required=True)
    k.add_argument("--site", required=True)
    k.add_argument("--keep-days", type=int, default=7)
    args = ap.parse_args()

    if args.cmd == "build":
        build(args.repo, args.out)
        return 0
    if args.cmd == "carry":
        carry(args.origin, args.out, args.site, args.keep_days)
        return 0
    report = check_repo(args.repo, Report())
    if args.cmd == "pr":
        check_pr(args.repo, args.base, args.head, args.author, args.override, report)
    if args.markdown:
        with open(args.markdown, "w", encoding="utf-8") as f:
            f.write(report.markdown("Repository checks"))
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
