# Writing and publishing Kando plugins

This guide covers everything from a first pack to a published script plugin. Kando's own design document, [docs/plugin-system.md](https://github.com/yldm-tech/Kando/blob/main/docs/plugin-system.md) in the Kando repository, is the authority on the format; the rules below are the ones its validator (`apps/kando/plugins/validate.go`) enforces, plus this directory's own.

- [Kinds of plugins](#kinds-of-plugins)
- [Publishers](#publishers)
- [The manifest](#the-manifest)
- [Data pack kinds](#data-pack-kinds)
- [Limits](#limits)
- [Licensing](#licensing)
- [Testing locally](#testing-locally)
- [Opening a pull request](#opening-a-pull-request)
- [Review criteria](#review-criteria)
- [Script plugins](#script-plugins)
- [Updating and removing a pack](#updating-and-removing-a-pack)
- [Takedowns and revocation](#takedowns-and-revocation)

## Kinds of plugins

There are two layers:

- **Data packs** run no code. Kando reads them by kind: `dictionary`, `wordlist`, `glossary`, `ai-service`, `translate-style`, `task`, `export-template` and `site`. A data pack is a folder (or a zip of it, `.kandopack`) holding `kando-plugin.json` and the data files it names. Data packs are listed after review and merge.
- **Script plugins** (`script`) are TSX code that runs in NSGo's sandbox on desktop, with only the permissions the user grants. They must be signed under Kando's plugin root, so their publisher must be certified first (see [Script plugins](#script-plugins)), and every version is reviewed here.

## Publishers

Every pack id is `<publisher>.<name>`, for example `alice.jlpt-n5`. The publisher segment is yours: `publishers.json` maps each publisher id to the GitHub accounts that may publish under it, and CI refuses a pull request that adds or changes packs under a publisher its author is not listed for.

To register a publisher, open a [New publisher](../../issues/new?template=new-publisher.yml) issue with the id you want. A maintainer adds it to `publishers.json`; your first pack PR can follow right away. Publisher ids are lowercase letters and digits (hyphens inside are fine), short, and should be recognizably yours (your GitHub name, your project or your organisation).

Reserved:

- `kando` is reserved for Kando's own **signed script plugins**. Kando refuses any data pack under `kando.` (`ErrReservedID`), so an unsigned pack can never look official.
- `yldm` is the Kando team's publisher for data packs (the packs seeded in this repository).
- No pack's display name may read as `Kando`, `看懂`, `Official`, `官方`, `公式`, `공식`, or the name of an AI service built into Kando (OpenAI, DeepSeek, Ollama, and the rest of `plugins.ReservedNames`), compared without case, width or spaces.

## The manifest

`kando-plugin.json` is read strictly: an unknown key at any level refuses the whole pack. The fields every pack has:

| Field | Rule |
|---|---|
| `schema` | `1` for data packs, `2` for script plugins. |
| `id` | `<publisher>.<name>`: lowercase letters and digits joined by single `.` or `-`, at least one dot, at most 64 bytes, no part a Windows device name (`con`, `nul`, `com1`…). Must equal the pack's folder name here. |
| `kind` | One of the kinds above. Must match the folder it is filed under here. |
| `version` | Letters, digits, `.`, `+`, `-`, at most 32 bytes. Use `MAJOR.MINOR.PATCH`; Kando compares versions part by part. |
| `license` | An SPDX id from the [accepted list](#licensing), at most 64 characters. |
| `author` | Optional, at most 80 characters. |
| `homepage` | Optional, an `https` address with a host name. |
| `name` | Text in several languages (below), English required, each at most 40 characters. |
| `description` | Optional text, English required when present, each at most 500 characters. Shown in the directory as the pack's summary. |

Texts (`name`, `description`, labels) are objects keyed by canonical language tags: `en`, `zh-Hans`, `zh-Hant`, `ja`, `ko` are Kando's interface languages; any canonical tag is accepted (`zh-Hans`, not `zh-hans` or `zh_CN`). Invisible and bidirectional control characters are stripped before lengths are counted.

Then exactly one kind-specific field: `dictionary`, `wordlist`, `glossary`, `service` (for `ai-service`), `style` (for `translate-style`), `task`, `template` (for `export-template`) or `site`.

The folder holds only `kando-plugin.json`, the files its manifest names, and optional `.md` or `.txt` notes. No subfolders, links or other files. File names are ASCII letters, digits, `.`, `-` and `_`, not starting or ending with a dot, at most 100 bytes.

## Data pack kinds

Each example below is a complete, valid manifest. The seed packs under `packs/` are real examples too.

### translate-style

A preset of the translation prompt, offered in Settings › Translation. Picking it fills the prompt box; the user can still edit it. Kando always appends its own reply format rule, so a style cannot break how translations are read. Write `{{language}}` where the target language goes; without it, Kando names the language after the prompt.

```json
{
  "schema": 1,
  "id": "alice.style-anime",
  "kind": "translate-style",
  "version": "1.0.0",
  "license": "CC0-1.0",
  "name": {"en": "Anime fansub style", "zh-Hans": "动画字幕组风格"},
  "style": {"prompt": "Translate anime subtitles into {{language}}. Keep honorifics such as -san and -senpai as they are..."}
}
```

`style.prompt`: 1 to 4000 characters.

### task

A study task the user runs on what they are watching; the reply shows in the player's side panel. Task packs spend the user's AI tokens, so they install turned off and run within a daily token budget.

```json
{
  "schema": 1,
  "id": "alice.vocab-line",
  "kind": "task",
  "version": "1.0.0",
  "license": "CC0-1.0",
  "name": {"en": "Useful words in this line"},
  "task": {
    "scope": "line",
    "prompt": "List the words in the current line worth learning, in {{language}}.",
    "reply": {
      "fields": [
        {"key": "word", "label": {"en": "Word"}},
        {"key": "meaning", "label": {"en": "Meaning"}}
      ],
      "items": 5
    },
    "render": "list",
    "maxTokens": 0
  }
}
```

| Field | Rule |
|---|---|
| `scope` | `line` (the current line and the 3 before it), `word` (the word looked up, its line and the 3 before) or `film-so-far` (everything watched, up to 40000 characters). Nothing after where the learner is ever leaves Kando. |
| `prompt` | 1 to 4000 characters, `{{language}}` for the answer language. Kando appends its own rules after yours: answer in that language, use only the given subtitles, reply in the exact JSON shape below. |
| `reply.fields` | 1 to 8 fields; `key` matches `^[a-z][A-Za-z0-9_]{0,31}$`, keys unique; `label` is text (English required, at most 40 characters). Every value in the reply is a string. |
| `reply.items` | For `list` and `cards` only: at most 20, default 8. Not allowed with `sections`. |
| `render` | `sections` (one object, a heading per field), `list` (a row per item) or `cards` (a card per item, first field as its title). |
| `maxTokens` | `0`, or 64 to 4096. With `0`, the reply cap is items × fields × 100 + 50 tokens, which must not exceed 4096. |

### export-template

Another way to export saved lines, next to Kando's own Anki notes.

```json
{
  "schema": 1,
  "id": "alice.sheet",
  "kind": "export-template",
  "version": "1.0.0",
  "license": "CC0-1.0",
  "name": {"en": "Spreadsheet (CSV)"},
  "template": {
    "format": "csv",
    "columns": [
      {"header": "Line", "value": "{{original}}"},
      {"header": "Translation", "value": "{{translation}}"},
      {"header": "Where", "value": "{{film}} {{time}}"}
    ]
  }
}
```

| Field | Rule |
|---|---|
| `format` | `csv`, `tsv` (quoted like Go's `encoding/csv`) or `anki` (Anki's text import: `#separator:tab`, `#html:false`, `#notetype:` headers). |
| `columns` | 1 to 16; each `value` 1 to 500 characters of text and placeholders. |
| placeholders | Only `{{original}}`, `{{translation}}`, `{{note}}`, `{{film}}`, `{{time}}` (m:ss) and `{{sound}}` (`[sound:file]` for Anki, the file name otherwise; Kando cuts audio clips only when a column uses it). Any other `{{…}}` or an unclosed `{{`/`}}` is refused. |
| `header` | CSV and TSV only, at most 40 characters. A header row is written when any column has one. |
| `noteType` | Anki only, at most 40 characters; `Basic` when empty. |

### glossary

Terms Kando adds to every translation whose languages match, after the user's own terms (the user's always win).

```json
{
  "schema": 1,
  "id": "alice.anime-ja-en",
  "kind": "glossary",
  "version": "1.0.0",
  "license": "CC-BY-4.0",
  "name": {"en": "Anime terms (Japanese → English)"},
  "glossary": {
    "from": "ja",
    "to": "en",
    "terms": [
      {"source": "先輩", "target": "senpai"},
      {"source": "お兄ちゃん", "target": "big brother"}
    ]
  }
}
```

`from` and `to` are canonical language tags (a `zh` pack applies to both `zh-Hans` and `zh-Hant`; a `zh-Hans` pack does not apply to `zh-Hant`). 1 to 5000 terms; each `source` and `target` 1 to 200 characters.

### wordlist

Levels of words (JLPT, HSK, CEFR, your own), drawn as colored underlines in the subtitles.

```json
{
  "schema": 1,
  "id": "alice.jlpt",
  "kind": "wordlist",
  "version": "1.0.0",
  "license": "CC-BY-4.0",
  "name": {"en": "JLPT levels"},
  "wordlist": {
    "language": "ja",
    "file": "jlpt.tsv",
    "tiers": [
      {"id": "n5", "label": {"en": "N5"}, "tone": "success"},
      {"id": "n3", "label": {"en": "N3"}, "tone": "accent"},
      {"id": "n1", "label": {"en": "N1"}, "tone": "warn"}
    ]
  }
}
```

`jlpt.tsv`, UTF-8, one word per line:

```
# word<TAB>tier id; lines starting with # are comments
食べる	n5
経済	n3
```

1 to 32 tiers; a tier `id` matches `^[a-z0-9][a-z0-9-]{0,31}$` and is unique; `tone` is `accent`, `warn`, `success` or `muted`; `label` is text, at most 40 characters. Columns after the second are ignored; lines without a tab, or with a tier not declared, are ignored; a repeated word keeps its first tier; words compare in lower case. A list with no usable word is refused when opened.

### dictionary

An offline dictionary, looked up before the AI service.

```json
{
  "schema": 1,
  "id": "alice.mini-ja-en",
  "kind": "dictionary",
  "version": "1.0.0",
  "license": "CC-BY-SA-4.0",
  "name": {"en": "Mini Japanese–English"},
  "dictionary": {
    "format": "tsv",
    "files": ["words.tsv"],
    "from": ["ja"],
    "to": ["en"],
    "attribution": {"en": "Based on … © …"}
  }
}
```

| `format` | Files |
|---|---|
| `tsv` | UTF-8, one entry per line: `headword<TAB>reading<TAB>definition` or `headword<TAB>definition`; `#` starts a comment line; columns after the third are ignored. |
| `cc-cedict` | The CC-CEDICT text format, UTF-8. |
| `yomitan-zip` | A dictionary zip as Yomitan exports it (only its `term_bank_<n>.json` files are read). Only this format's files end in `.zip`; entries inside may not contain `..`, absolute paths, links or another zip. |

`files` is one or more files of the pack; `from` and `to` are lists of canonical language tags; `attribution` is optional text (at most 500 characters), shown under every definition, and required here whenever the license asks for credit.

### ai-service

A preset for Settings › AI Service: the address and model of a service the user then gives their own key. A pack never holds a key.

```json
{
  "schema": 1,
  "id": "acme.gateway",
  "kind": "ai-service",
  "version": "1.0.0",
  "license": "MIT",
  "name": {"en": "Acme LLM gateway"},
  "service": {"baseURL": "https://llm.acme.example/v1", "model": "qwen3-32b", "keyURL": "https://llm.acme.example/keys", "group": "cloud"}
}
```

`baseURL` (required) and `keyURL` (optional) are `https` with a host name and no user name or password; only loopback addresses (`localhost`, `127.0.0.1`, `::1`) may use `http`. `model` is at most 200 characters; `group` is `cloud` or `local`. Kando lists pack presets after the built-in ones, labelled with the pack and host, and asks before opening a pack's `keyURL`. This directory only accepts presets for services whose operator you are or who publish an OpenAI-compatible endpoint for the public.

### site

Teaches Kando's built-in browser which links on a site are single videos, for its Download Video button. Each domain works only after the user allows it, and downloads from these sites never borrow the browser's sign-in.

```json
{
  "schema": 1,
  "id": "alice.lectures",
  "kind": "site",
  "version": "1.0.0",
  "license": "CC0-1.0",
  "name": {"en": "Open Lectures"},
  "site": {
    "sites": [
      {
        "domain": "lectures.example.org",
        "not": ["forum.lectures.example.org"],
        "videos": [
          {"path": "^/watch/[0-9]+$"},
          {"path": "^/play$", "param": "v", "value": "^[A-Za-z0-9_-]{6,20}$"}
        ]
      }
    ]
  }
}
```

1 to 8 sites; each `domain` is a registrable domain or a host under one (not a public suffix such as `github.io`), must not be, contain or be under a site Kando already knows (YouTube, Bilibili and the rest of its catalog), and domains may not overlap. `not` lists up to 16 hosts under the domain whose pages are never videos. `videos` holds 1 to 16 link shapes: `path` is matched against the URL's escaped path, and `param` with `value` (always together) against a query parameter's first value. Patterns use the subset Go and JavaScript read alike, at most 256 characters, with no nested quantifiers, backreferences or lookarounds. There are no scripts, cookies, sign-in recipes or yt-dlp arguments in a site pack.

## Limits

Kando's limits per pack, which CI checks with Kando's own validator:

| Kind | Pack file | Files in it | Unpacked |
|---|---|---|---|
| Data packs | 32 MiB | 16 | 64 MiB |
| `dictionary` | 200 MiB | 64 (entries of nested Yomitan zips count) | 1 GiB |
| `script` | 16 MiB (the `.nsgopkg` inside at most 8 MiB) | 8 | 16 MiB |

The manifest itself is at most 256 KiB. This repository adds:

- No single file over **50 MiB** (GitHub warns at 50 MiB and refuses 100 MiB), and no built pack file over 100 MiB. A dictionary larger than that does not fit here yet; open an issue to discuss it.
- All published pack files together stay under 900 MiB (GitHub Pages serves at most 1 GB).

## Licensing

Everything published here is redistributed to anyone, so a pack's license must allow redistribution, including commercial use, and you must have the right to apply it: your own work, or third-party data whose license allows it. Name the pack's license in `license` as an SPDX id, put a `LICENSE.txt` or `README.md` with the full notice in the pack folder when the license asks for it, and give credit in `description` (and in `dictionary.attribution` for dictionaries).

Accepted for **data packs**:

| SPDX id | |
|---|---|
| `CC0-1.0`, `PDDL-1.0`, `Unlicense` | Public domain dedications |
| `CC-BY-3.0`, `CC-BY-4.0` | Attribution |
| `CC-BY-SA-3.0`, `CC-BY-SA-4.0` | Attribution, share-alike (JMdict, CC-CEDICT) |
| `ODC-By-1.0`, `ODbL-1.0` | Open Data Commons |
| `MIT`, `Apache-2.0`, `BSD-2-Clause`, `BSD-3-Clause`, `ISC`, `0BSD` | Permissive software licenses |

Accepted for **script plugins**: `MIT`, `Apache-2.0`, `BSD-2-Clause`, `BSD-3-Clause`, `ISC`, `0BSD`, `Unlicense`, `CC0-1.0`, `MPL-2.0`, `LGPL-3.0-only`, `LGPL-3.0-or-later`, `GPL-3.0-only`, `GPL-3.0-or-later`. Kando's own official plugins (publisher `kando`) may also carry Kando's license, `FSL-1.1-ALv2`; no other publisher may.

An expression joining accepted ids with `AND` or `OR` is accepted too. Non-commercial (`-NC`) and no-derivatives (`-ND`) licenses, "free for personal use" terms, and data scraped from sites whose terms forbid it are not. When in doubt, ask in the PR before doing the work.

The repository's own files are MIT; that license does not extend to the packs.

## Testing locally

1. Write the folder: `kando-plugin.json` plus its files, named by the rules above.
2. Check it with Kando's validator, the same code Kando installs with:

   ```sh
   kando plugin validate path/to/alice.jlpt
   ```

   It takes the folder or a zip and prints the id, kind, version and hash, or exactly why the pack is refused. (`kando` is Kando's command-line tool; Settings › General › Command Line & MCP puts it on your PATH.)
3. Install it: drag the folder onto Settings › Plugins, or zip the folder's **contents** (the manifest at the zip's top level, no folder entries: `cd alice.jlpt && zip -X ../alice.jlpt.kandopack *`) and use **Settings › Plugins › Install from File…**. Try it where it shows up: the translation prompt presets, the player's task menu, the saved lines' export, the subtitles' underlines, and so on.
4. Run this repository's checks (Python 3, no packages): `python3 tools/packs.py check`.

Script plugins are tested in developer mode, see below.

## Opening a pull request

1. Register your publisher if you have not ([Publishers](#publishers)).
2. Fork, add `packs/<kind>/<your id>/` (or `scripts/<your id>/`), and open a pull request using the template. One pack per PR keeps review quick; a few closely related packs (one family of styles) may share one.
3. CI runs **Validate**: this repository's checks (layout, your ownership of the publisher, license, sizes, version bump), then Kando's validator on the built pack file, then a preview of how the directory will list it. A bot posts the result as one comment on the PR and updates it on every push. Fix whatever it reports; maintainers review once it is green.
4. A maintainer reviews it ([criteria](#review-criteria)), may ask for changes, and merges.
5. On merge, **Publish** builds the pack, signs a new index and deploys it. Kando picks it up on its next daily refresh, or at once when the user presses Refresh in the Plugin Directory.

Only maintainers change files outside `packs/` and `scripts/` (the docs, `publishers.json`, tools, workflows). When a contributor's PR rightly does, a maintainer adds the `maintainer-override` label, which lifts that rule and the publisher ownership rule for the PR; it lifts nothing else.

## Review criteria

A maintainer checks, beyond what CI checks:

- **Useful and honest.** The pack does what its name and description say, for learners. Names and descriptions are accurate in every language given (machine translation is fine if checked), and do not imitate Kando, an AI provider or another publisher.
- **Licensed.** The license is accepted, you have the right to apply it, and credit is given where required.
- **Clean content.** No hateful, sexual or harassing content, no personal data, no advertising or tracking links; addresses (`homepage`, `keyURL`, `baseURL`) go where they say.
- **Prompts** (styles, tasks) do not try to get around Kando's rules (asking for content beyond the lines given, changing the reply format) and do not waste tokens: replies sized to what is shown.
- **AI service presets** point at a real service the publisher operates or that is meant for public use, over `https`.
- **Site packs** name sites whose videos may be downloaded, with patterns no wider than the video pages.
- **Script plugins**: see the next section.

## Script plugins

Script plugins run code, so they take two extra steps: your publisher is certified once, and every version's source is reviewed here.

### 1. Develop in developer mode

In Kando, turn on **Settings › Plugins › Developer › Developer Mode** and press **Make Developer Key**. Write a folder with `kando-plugin.json` (schema 2; no `script` field, packing fills it in) and `plugin.tsx`, then use **Pack and Install Folder…**: Kando compiles and signs it with your developer key and installs it after the usual confirmation. Developer plugins carry a Developer badge and run only on your computer.

The manifest's script fields (`kando`, `capabilities`, `optional`, `contributes`, `credentials`, `settings`, `events`) are described in section 4.2 of the [design document](https://github.com/yldm-tech/Kando/blob/main/docs/plugin-system.md). In short: `capabilities.host` lists the Kando permissions you need (`kando.film.current`, `kando.line.current`, `kando.lines.seen`, `kando.saved.read`, `kando.words.read`, `kando.sound.read`, `kando.llm.chat`, `kando.net.credentialFetch`, `kando.toast`, `kando.ui.openURL`, `kando.settings.get`), `capabilities.network.http` lists each request you make (exact host, methods, and paths or path prefixes; at most 16 rules, never a wildcard), and your code must export `kandoManifest()` returning the same `capabilities`, `contributes`, `credentials`, `settings` and `events` as the manifest, since the manifest itself is not covered by the signature.

### 2. Get your publisher certified

Open a [New publisher](../../issues/new?template=new-publisher.yml) issue and tick "script plugins". The owner reviews your code once (a link to the plugin you intend to publish is enough), and if accepted signs a **publisher certificate** for your release key with Kando's offline plugin root:

```sh
# You: make a release key, keep its secret offline, send only the public key.
go tool nsgo keygen
# The owner, on the offline machine: certify it for your publisher only, for at most a year.
NSGO_ROOT_KEY=<root secret> go tool nsgo certify -key <your release public key> -apps 'ai.yldm.kando.plugin.<publisher>.*' -days 365 -out <publisher>.cert
```

The certificate covers only `ai.yldm.kando.plugin.<publisher>.*`, so it signs plugins under your publisher and nothing else, and it is valid for at most 365 days; renew it with a new issue. Kando shows certified plugins with a Verified badge. `publishers.json` records `"scripts": true` for certified publishers, and CI refuses script plugins from any other.

### 3. Sign and submit each version

In the plugin folder, an `nsgo.yaml` names the plugin (`id: ai.yldm.kando.plugin.<publisher>.<name>`, `name`, `version`, `capabilities` in snake_case with only `host` and `network`). Then:

```sh
NSGO_RELEASE_KEY=<your release secret> go tool nsgo publish -cert <publisher>.cert -entry plugin.tsx -out <name>.nsgopkg .
```

Make the `.kandoplugin`: a zip with `kando-plugin.json` (now with `script: {"package": "<name>.nsgopkg", "sha256": "<its SHA-256>"}`) and the `.nsgopkg` at its top level, named `<id>-<version>.kandoplugin`. Check it with `kando plugin validate <file>`; it must report source `verified`.

Open a PR adding:

```
scripts/<id>/
  <id>-<version>.kandoplugin
  src/
    kando-plugin.json   (as packed, the script field aside)
    nsgo.yaml
    plugin.tsx          (and any other source files)
```

CI verifies the signature against Kando's official root and that `src/kando-plugin.json` equals the signed manifest (the `script` field aside). **CI does not rebuild the bundle from the source:** `nsgo publish` stamps each package with its signing time and build number, so builds are not byte-reproducible. The source is required so reviewers can read exactly what the plugin does, and your certification is the commitment that the signed bundle is built from it. Reviewers check that the code does only what the description says; that permissions and network rules are the narrowest that work; that nothing sends subtitles, saved lines or words anywhere the user would not expect; that `kando.lines.seen` or `kando.llm.chat` are not combined with network access that could act on what a subtitle says; and that `kandoManifest()` matches the manifest.

## Updating and removing a pack

- **Update:** change the files and raise `version`. CI refuses any change to a published pack without a higher version, because a pack file's name is `<id>-<version>.kandopack` and a published file never changes (Kando checks downloads against the SHA-256 in its cached index). Kando shows **Update** for installed packs older than the listed version; updates are never automatic, and a script plugin that asks for more than it was granted needs the user's consent again.
- **Remove:** delete the pack's folder in a PR. It leaves the index on merge; its last file stays downloadable for a week for Kando installs whose cached index still lists it. Copies already installed are not affected.
- Only one version of each pack is listed: the one in the repository.

## Takedowns and revocation

Report a pack with the [Report a plugin](../../issues/new?template=report-plugin.yml) issue form (or privately, through [security advisories](../../security/advisories/new), for anything exploitable).

- Taking a pack out of the index stops new installs only. Installed data packs stay until the user removes them; they run no code.
- A script plugin, or a whole release key, can be **revoked**: the owner signs a revocation list with the plugin root (`go tool nsgo revoke`), published next to Kando's update feed. Kando fetches it daily; a revoked plugin is stopped at once and marked as withdrawn. A publisher whose release key leaks must tell the maintainers immediately, since certificate expiry does not stop a stolen key: only revocation does.
- Maintainers may remove a pack or suspend a publisher for breaking these rules.
