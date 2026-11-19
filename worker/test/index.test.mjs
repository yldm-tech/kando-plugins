// node --test worker/test: the Worker against a stubbed origin. No dependencies.
import { test } from "node:test";
import assert from "node:assert/strict";
import { handle } from "../src/index.js";

const ORIGIN = "https://origin.example/kando-plugins";

function stub(responder) {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    return responder(url, init);
  };
  return calls;
}

const req = (path, init) => new Request("https://kando.yldm.ai" + path, init);

test("index.json is proxied with a short cache and JSON type", async () => {
  const calls = stub(() => new Response('{"format":"kando-plugins-index"}', { status: 200, headers: { ETag: '"abc"', "Content-Length": "32" } }));
  const res = await handle(req("/plugin/index.json"), ORIGIN);
  assert.equal(res.status, 200);
  assert.equal(calls[0].url, ORIGIN + "/index.json");
  assert.equal(calls[0].init.redirect, "manual");
  assert.equal(res.headers.get("content-type"), "application/json");
  assert.equal(res.headers.get("cache-control"), "public, max-age=300");
  assert.equal(res.headers.get("etag"), '"abc"');
  assert.equal(res.headers.get("content-length"), "32");
});

test("a pack is proxied as an immutable zip", async () => {
  const calls = stub(() => new Response("PK", { status: 200 }));
  const res = await handle(req("/plugin/packs/yldm.style-casual-1.0.0.kandopack"), ORIGIN);
  assert.equal(res.status, 200);
  assert.equal(calls[0].url, ORIGIN + "/packs/yldm.style-casual-1.0.0.kandopack");
  assert.equal(res.headers.get("content-type"), "application/zip");
  assert.match(res.headers.get("cache-control"), /immutable/);
});

test("If-None-Match is passed on and a 304 has no body", async () => {
  const calls = stub(() => new Response(null, { status: 304, headers: { ETag: '"abc"' } }));
  const res = await handle(req("/plugin/index.json", { headers: { "If-None-Match": '"abc"' } }), ORIGIN);
  assert.equal(calls[0].init.headers.get("if-none-match"), '"abc"');
  assert.equal(res.status, 304);
  assert.equal(res.body, null);
});

test("HEAD has no body", async () => {
  stub(() => new Response(null, { status: 200, headers: { "Content-Length": "10" } }));
  const res = await handle(req("/plugin/index.json", { method: "HEAD" }), ORIGIN);
  assert.equal(res.status, 200);
  assert.equal(res.body, null);
  assert.equal(res.headers.get("content-length"), "10");
});

test("other methods are refused without reaching the origin", async () => {
  const calls = stub(() => new Response("x"));
  const res = await handle(req("/plugin/index.json", { method: "POST", body: "x" }), ORIGIN);
  assert.equal(res.status, 405);
  assert.equal(res.headers.get("allow"), "GET, HEAD");
  assert.equal(calls.length, 0);
});

test("other paths and odd file names are refused without reaching the origin", async () => {
  const calls = stub(() => new Response("x"));
  for (const path of ["/plugin/", "/plugin/carried.json", "/plugin/packs/..%2Findex.json", "/plugin/packs/%2e%2e%2fsecret.kandopack", "/plugin/packs/a.exe", "/plugin/packs/sub/x-1.kandopack", "/plugin/index.json?x=1", "/"]) {
    const res = await handle(req(path), ORIGIN);
    assert.equal(res.status, 404, path);
    assert.equal(res.headers.get("cache-control"), "no-store", path);
  }
  assert.equal(calls.length, 0);
});

test("a 404 of the origin is not cached, a redirect or error is a 502", async () => {
  stub(() => new Response("nope", { status: 404 }));
  let res = await handle(req("/plugin/packs/yldm.x-1.0.0.kandopack"), ORIGIN);
  assert.equal(res.status, 404);
  assert.equal(res.headers.get("cache-control"), "no-store");
  stub(() => new Response(null, { status: 301, headers: { Location: "https://elsewhere.example/" } }));
  res = await handle(req("/plugin/index.json"), ORIGIN);
  assert.equal(res.status, 502);
  stub(() => { throw new Error("down"); });
  res = await handle(req("/plugin/index.json"), ORIGIN);
  assert.equal(res.status, 502);
});

test("a decoded body does not claim the encoded length", async () => {
  stub(() => new Response("{}", { status: 200, headers: { "Content-Length": "5", "Content-Encoding": "gzip" } }));
  const res = await handle(req("/plugin/index.json"), ORIGIN);
  assert.equal(res.headers.get("content-length"), null);
});
