# kando.yldm.ai/plugin Worker

A Cloudflare Worker that serves the plugin directory at the addresses Kando reads:

| Public address | Served from |
|---|---|
| `https://kando.yldm.ai/plugin/index.json` | `https://yldm-tech.github.io/kando-plugins/index.json` |
| `https://kando.yldm.ai/plugin/packs/<file>` | `https://yldm-tech.github.io/kando-plugins/packs/<file>` |

The rest of `kando.yldm.ai` is the landing site and never reaches the Worker: its routes cover these two patterns only.

What it does:

- Answers `GET` and `HEAD` only (`405` otherwise), and only for `index.json` and pack file names of the form `<id>-<version>.kandopack` or `.kandoplugin` with no query string (`404` otherwise, without asking the origin).
- Passes `If-None-Match` and `If-Modified-Since` to the origin and passes back `ETag`, `Last-Modified` and `Content-Length`, so Kando's daily check of the index usually ends in a `304`.
- Sets `Content-Type`: `application/json` for the index, `application/zip` for packs.
- Caches the index for 5 minutes and packs for a year (`immutable`): a pack file's name carries its version and is never reused. A `404`, a redirect or an error of the origin is not cached, so a newly published file shows up at once; redirects are never followed (`502`).

Nothing here is trusted for integrity: the index is signed with Kando's index key, and Kando checks every download against the size and SHA-256 the index lists.

## Deploy

The owner deploys it once, and again only when `src/index.js` or `wrangler.toml` changes. Nothing in CI deploys it.

1. Fill in `account_id` and both `zone_id`s in `wrangler.toml` (Cloudflare dashboard › yldm.ai › Overview, API section).
2. From this folder: `npx wrangler login`, then `npx wrangler deploy`.
3. Check it: `curl -sI https://kando.yldm.ai/plugin/index.json` answers `200` with `content-type: application/json` once the first publish ran, and `curl -sI https://kando.yldm.ai/plugin/packs/nothing.txt` answers `404` with `cache-control: no-store`.

`kando.yldm.ai` must be proxied through Cloudflare (orange cloud) for the routes to apply.

## Test

`npm test` (Node.js 20 or newer, no dependencies) runs the Worker against a stubbed origin.

## Caveats

- GitHub Pages sets `Cache-Control: max-age=600` on everything it serves and that cannot be changed; the Worker replaces it with its own headers, so only Cloudflare's edge sees the origin's value.
- The origin is the project site `yldm-tech.github.io/kando-plugins`. If the organisation's own site (`yldm-tech/yldm-tech.github.io`) is ever given a custom domain, GitHub redirects project sites to it, and the Worker answers `502` until `ORIGIN` is changed to the new address.
