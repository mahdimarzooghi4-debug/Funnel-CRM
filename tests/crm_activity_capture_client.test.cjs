const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(id = "") {
    this.id = id; this.value = ""; this.textContent = ""; this.className = "";
    this.children = []; this.listeners = new Map(); this.disabled = false;
    this.selectedOptions = [{ textContent: "بازدید" }];
  }
  addEventListener(name, callback) { this.listeners.set(name, callback); }
  async dispatch(name, event = {}) { await this.listeners.get(name)?.({ preventDefault() {}, ...event }); }
  append(...nodes) { this.children.push(...nodes); }
  appendChild(node) { this.children.push(node); return node; }
  replaceChildren(...nodes) { this.children = nodes; }
  reset() { for (const element of elements.values()) if (element !== this) element.value = ""; }
  reportValidity() { return true; }
}

const ids = ["status", "activity-queue", "connection-status", "activity-form", "sync-activities",
  "workspace-id", "profile-id", "campaign-id", "activity-type", "channel", "occurred-at"];
const elements = new Map(ids.map((id) => [id, new Element(id)]));
elements.get("activity-form").tagName = "FORM";
elements.get("activity-type").value = "field.visit";
elements.get("channel").value = "field";
elements.get("occurred-at").value = "2026-10-25T10:15";

const stored = new Map();
function request(run) {
  const req = {};
  setTimeout(() => {
    try { req.result = run(); req.onsuccess?.(); }
    catch (error) { req.error = error; req.onerror?.(); }
  }, 0);
  return req;
}
const db = {
  objectStoreNames: { contains: () => true },
  close() {},
};
db.transaction = () => {
  const transaction = {};
  transaction.objectStore = () => ({
    put(item) { return request(() => { stored.set(item.source_event_id, structuredClone(item)); setTimeout(() => transaction.oncomplete?.(), 0); return item.source_event_id; }); },
    index() { return { getAll: (workspaceId) => request(() => [...stored.values()].filter((item) => item.workspace_id === workspaceId)) }; },
  });
  return transaction;
};
const indexedDB = {
  open() {
    const req = {};
    setTimeout(() => { req.result = db; req.onupgradeneeded?.(); req.onsuccess?.(); }, 0);
    return req;
  },
};
const windowListeners = new Map();
const window = {
  indexedDB, location: { search: "?workspace_id=11111111-1111-4111-8111-111111111111" },
  addEventListener(name, callback) { windowListeners.set(name, callback); },
};
const navigator = { onLine: false };
const calls = [];
const fetch = async (path, options) => {
  calls.push({ path, options });
  return { ok: true, status: 201, async json() { return { activity: { id: "stored-activity" }, duplicate: false }; } };
};
let eventSequence = 1;
const crypto = { randomUUID: () => `event-${eventSequence++}` };
const document = {
  getElementById: (id) => elements.get(id),
  createElement: (tag) => new Element(tag),
};
const code = fs.readFileSync("src/funnel_crm/web/crm_activity_capture.py", "utf8")
  .split('_CLIENT_SCRIPT = r"""')[1].split('"""\n\n_SERVICE_WORKER_SCRIPT')[0];
assert.ok(code);
vm.runInNewContext(code, { window, navigator, document, fetch, crypto, URLSearchParams, encodeURIComponent, setTimeout, Date, structuredClone });

const tick = () => new Promise((resolve) => setTimeout(resolve, 10));
async function main() {
  await tick();
  assert.equal(elements.get("workspace-id").value, "11111111-1111-4111-8111-111111111111");
  elements.get("profile-id").value = "22222222-2222-4222-8222-222222222222";
  await elements.get("activity-form").dispatch("submit");
  await tick(); await tick();
  assert.equal(stored.size, 1);
  const [eventId, item] = [...stored.entries()][0];
  assert.equal(eventId, "event-1");
  assert.equal(item.status, "queued");
  assert.equal(calls.length, 0, "offline capture must not attempt a network request");

  navigator.onLine = true;
  windowListeners.get("online")();
  await tick(); await tick(); await tick();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].options.headers["X-Workspace-ID"], item.workspace_id);
  assert.equal(JSON.parse(calls[0].options.body).source_event_id, eventId);
  assert.equal(stored.get(eventId).status, "synced");
  assert.equal(elements.get("activity-queue").children.length, 1);
  assert.match(elements.get("activity-queue").children[0].children[0].textContent, /همگام‌شده/);
  console.log("CRM activity capture offline queue behavior passed.");
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
