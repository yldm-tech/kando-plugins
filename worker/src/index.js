// Serves Kando's community plugin directory on kando.yldm.ai: /plugin/index.json and /plugin/packs/<file>, proxied from this repository's GitHub Pages site (env.ORIGIN). Everything else on the host never reaches this Worker (wrangler.toml routes only these two patterns), and any other path or method that does is refused.
//
// The index is signed and every pack is checked against the SHA-256 the index lists, so this Worker is not trusted for integrity; it only has to serve the bytes as they are, say what they are, and keep caches sensible: the index briefly (it changes on every publish), the packs for a year (a pack file's name carries its version and is never reused), and nothing that is not a 2xx or 304.

const INDEX_PATH = "/plugin/index.json";
const PACKS_PREFIX = "/plugin/packs/";

// A pack file's name as tools/packs.py writes it: <id>-<version>.kandopack, or a signed .kandoplugin. Only these characters, so the name is never escaped and never reaches another path of the origin.
const PACK_NAME = /^[a-z0-9][a-z0-9.-]{0,63}-[0-9A-Za-z][0-9A-Za-z.+-]{0,31}\.(?:kandopack|kandoplugin)$/;

const INDEX_TTL = 300;
const PACK_TTL = 31536000;

// The origin's headers passed on: what a client needs to revalidate and to know the length.
const PASSED = ["etag", "last-modified", "content-length"];

export default {
  async fetch(request, env) {
    return handle(request, env.ORIGIN || "https://yldm-tech.github.io/kando-plugins");
  },
};

export async function handle(request, origin) {
  if (request.method !== "GET" && request.method !== "HEAD") {
    return plain(405, "Method not allowed", { Allow: "GET, HEAD" });
  }
  const url = new URL(request.url);
  let upstream, type, ttl, file;
  if (url.pathname === INDEX_PATH) {
    upstream = "/index.json";
    type = "application/json";
    ttl = INDEX_TTL;
  } else if (url.pathname.startsWith(PACKS_PREFIX)) {
    file = url.pathname.slice(PACKS_PREFIX.length);
    if (!PACK_NAME.test(file) || file.includes("..")) {
      return plain(404, "Not found");
    }
    upstream = "/packs/" + file;
    type = "application/zip";
    ttl = PACK_TTL;
  } else {
    return plain(404, "Not found");
  }
  if (url.search !== "") {
    // A query string would make a separate cache entry for the same file.
    return plain(404, "Not found");
  }

  const headers = new Headers();
  for (const name of ["if-none-match", "if-modified-since"]) {
    const value = request.headers.get(name);
    if (value !== null) headers.set(name, value);
  }
  let res;
  try {
    res = await fetch(origin.replace(/\/+$/, "") + upstream, {
      method: request.method,
      headers,
      redirect: "manual",
      // Cache only what is good at Cloudflare's edge: a missing file must show up as soon as it is published.
      cf: { cacheEverything: true, cacheTtlByStatus: { "200-299": ttl, "300-599": 0 } },
    });
  } catch {
    return plain(502, "The plugin directory is unavailable");
  }

  if (res.status === 404) {
    return plain(404, "Not found");
  }
  if (res.status !== 200 && res.status !== 304) {
    // A redirect included: the origin is never followed anywhere else.
    return plain(502, "The plugin directory is unavailable");
  }

  const out = new Headers({
    "Content-Type": type,
    "Cache-Control": file ? `public, max-age=${ttl}, immutable` : `public, max-age=${ttl}`,
    "X-Content-Type-Options": "nosniff",
    "Access-Control-Allow-Origin": "*",
  });
  if (file) out.set("Content-Disposition", `attachment; filename="${file}"`);
  for (const name of PASSED) {
    const value = res.headers.get(name);
    // A length is only true of the body as the origin sent it, not once the runtime decoded it.
    if (value !== null && !(name === "content-length" && res.headers.get("content-encoding"))) {
      out.set(name, value);
    }
  }
  const body = request.method === "HEAD" || res.status === 304 ? null : res.body;
  return new Response(body, { status: res.status, headers: out });
}

function plain(status, text, extra = {}) {
  return new Response(text + "\n", {
    status,
    headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store", ...extra },
  });
}
