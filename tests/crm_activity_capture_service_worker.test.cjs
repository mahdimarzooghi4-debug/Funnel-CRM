const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const cacheNames = new Set(["funnel-crm-activity-shell-old"]);
const entries = new Map();
const cache = {
  async put(key, response) { entries.set(String(key), response); },
  async match(key) { return entries.get(String(key)) || null; },
};
const caches = {
  async open(name) { cacheNames.add(name); return cache; },
  async keys() { return [...cacheNames]; },
  async delete(name) { cacheNames.delete(name); return true; },
};
const listeners = new Map();
const self = {
  location: { origin: "https://crm.example" },
  clients: { claimed: false, async claim() { this.claimed = true; } },
  addEventListener(name, callback) { listeners.set(name, callback); },
  async skipWaiting() { this.waitingSkipped = true; },
};
class Response {
  constructor(body, options = {}) { this.body = body; this.status = options.status || 200; this.ok = this.status >= 200 && this.status < 300; this.headers = options.headers || {}; }
  clone() { return new Response(this.body, { status: this.status, headers: this.headers }); }
}
let offline = false;
const fetch = async (request) => {
  if (offline) throw new Error("offline");
  return new Response(typeof request === "string" ? request : request.url);
};
const source = fs.readFileSync("src/funnel_crm/web/crm_activity_capture.py", "utf8");
const code = source.split('_SERVICE_WORKER_SCRIPT = r"""')[1].split('"""\n\n_SECURITY_HEADERS')[0];
assert.ok(code);
vm.runInNewContext(code, { self, caches, fetch, URL, Response, Promise, Error });

async function dispatch(name, event) { listeners.get(name)(event); await event.pending; }
async function main() {
  let installPromise;
  await dispatch("install", { waitUntil(promise) { installPromise = promise; }, get pending() { return installPromise; } });
  assert.equal(self.waitingSkipped, true);
  assert.ok(entries.has("https://crm.example/workspace/crm-activity-capture"));
  assert.ok(entries.has("https://crm.example/assets/crm-activity-capture.js"));

  let activatePromise;
  await dispatch("activate", { waitUntil(promise) { activatePromise = promise; }, get pending() { return activatePromise; } });
  assert.equal(self.clients.claimed, true);
  assert.equal(cacheNames.has("funnel-crm-activity-shell-old"), false);

  offline = true;
  const navigation = { request: { url: "https://crm.example/workspace/crm-activity-capture?workspace_id=abc", method: "GET", mode: "navigate" } };
  let offlineResponse;
  listeners.get("fetch")({ ...navigation, respondWith(promise) { offlineResponse = promise; } });
  assert.ok((await offlineResponse).ok, "offline navigation returns the cached shell");

  let apiIntercepted = false;
  listeners.get("fetch")({ request: { url: "https://crm.example/api/v1/crm/profiles/1", method: "GET", mode: "cors" }, respondWith() { apiIntercepted = true; } });
  assert.equal(apiIntercepted, false, "API responses must not be cached or intercepted");
  console.log("CRM activity service worker shell caching behavior passed.");
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
