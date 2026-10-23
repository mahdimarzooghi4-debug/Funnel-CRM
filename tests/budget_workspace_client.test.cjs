const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tagName = "div") {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.listeners = new Map();
    this.style = {};
    this.value = "";
    this.textContent = "";
    this.disabled = false;
    this.hidden = false;
    this.checked = false;
    this.type = "";
    this.download = "";
    this.href = "";
    this.clicked = false;
  }
  appendChild(node) {
    this.children.push(node);
    return node;
  }
  remove() { this.removed = true; }
  click() { this.clicked = true; }
  append(...nodes) {
    nodes.forEach((node) => this.appendChild(node));
  }
  replaceChildren(...nodes) {
    this.children = nodes;
  }
  addEventListener(name, callback) {
    const listeners = this.listeners.get(name) || [];
    listeners.push(callback);
    this.listeners.set(name, listeners);
  }
  async dispatch(name) {
    for (const callback of this.listeners.get(name) || []) {
      await callback({ target: this });
    }
  }
  querySelectorAll(selector) {
    assert.equal(selector, "input[type=checkbox]:checked");
    const matches = [];
    const visit = (node) => {
      if (node.tagName === "INPUT" && node.type === "checkbox" && node.checked) {
        matches.push(node);
      }
      node.children.forEach(visit);
    };
    this.children.forEach(visit);
    return matches;
  }
}
Object.defineProperty(Element.prototype, "innerHTML", {
  get() { throw new Error("Unsafe innerHTML read"); },
  set() { throw new Error("Unsafe innerHTML write"); },
});

const ids = [
  "workspace-id", "organization-id", "status", "scenario-list",
  "scenario-panel", "results", "scenario-results", "campaign-results", "evidence-coverage", "channel-coverage", "evidence-gaps",
  "selection-count", "compare", "load-scenarios", "period-start", "period-end", "export-csv",
];
const elements = new Map(ids.map((id) => [id, new Element(id.includes("id") ? "select" : "div")]));
elements.get("load-scenarios").tagName = "BUTTON";
elements.get("compare").tagName = "BUTTON";
elements.get("period-start").value = "2026-10-01";
elements.get("period-end").value = "2026-10-14";

const calls = [];
const downloads = [];
const body = { appendChild: (node) => downloads.push(node) };
const urlApi = { createObjectURL: (blob) => { downloads.push(blob); return "blob:report"; }, revokeObjectURL: (url) => downloads.push("revoked:" + url) };
const workspace = { id: "workspace-1", name: "Demo workspace", root_organization_id: "root-1" };
const scenarios = [
  { id: "scenario-1", name: "<img src=x onerror=alert(1)>", allocation_count: 2 },
  { id: "scenario-2", name: '=HYPERLINK("https://evil.example","open")', allocation_count: 2 },
];
const fetch = async (path, options = {}) => {
  calls.push({ path, options });
  let payload;
  if (path === "/api/v1/system/workspaces") {
    payload = [workspace];
  } else if (path === "/api/v1/system/organization-units") {
    payload = [{ id: "root-1", name: "مرکز اصلی", parent_id: null, unit_type: "root" }];
  } else if (path.startsWith("/api/v1/crm/budget-scenarios?")) {
    payload = scenarios;
  } else if (path.startsWith("/api/v1/crm/budget-scenarios/compare/performance-context?")) {
    payload = {
      period_calendar_days: 14,
      scenarios: [
        { name: scenarios[0].name, reconciliation_by_currency: { USD: {
          planned_amount: 1200, comparable_planned_amount: 1000, observed_spend_amount: 900,
          variance_amount: 100, allocation_coverage_percent: 80, currency_mismatch_allocation_count: 1,
        } } },
        { name: scenarios[1].name, reconciliation_by_currency: {} },
      ],
      campaigns: [{
        campaign_name: "Spring launch", channel: "email",
        recorded_spend_by_currency: { USD: 900 },
        metrics: { leads: { actual: 12, recorded_day_coverage_percent: 80 }, conversions: { actual: null, recorded_day_coverage_percent: 60 } },
        scenario_allocations: [{
          scenario_name: scenarios[1].name, planned_budget_currency: "USD", planned_budget_amount: 1000,
          actual_spend_in_allocation_currency: null, variance_amount: null,
        }],
      }, {
        campaign_name: "Brand awareness", channel: "social",
        recorded_spend_by_currency: {},
        metrics: { leads: { actual: null }, conversions: { actual: 3 } },
        scenario_allocations: [],
      }],
    };
  } else {
    throw new Error("Unexpected request: " + path);
  }
  return { ok: true, status: 200, json: async () => payload };
};

const pythonSource = fs.readFileSync(
  "src/funnel_crm/web/budget_scenario_comparison.py",
  "utf8",
);
const script = pythonSource.match(/_CLIENT_SCRIPT = r"""([\s\S]*?)"""/);
assert.ok(script, "client script should be available in the web module");

vm.runInNewContext(script[1], {
  document: {
    getElementById: (id) => {
      assert.ok(elements.has(id), "unexpected DOM id: " + id);
      return elements.get(id);
    },
    createElement: (tagName) => new Element(tagName),
    body,
  },
  window: { location: { search: "?period_start=2026-10-01&period_end=2026-10-14" } },
  URLSearchParams,
  Intl,
  fetch,
  URL: urlApi,
  Blob,
  setTimeout,
});

async function settle() {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

async function main() {
  await settle();
  assert.equal(elements.get("workspace-id").value, workspace.id);
  assert.equal(elements.get("organization-id").value, "root-1");
  assert.equal(elements.get("organization-id").children[1].textContent, "مرکز اصلی");

  await elements.get("load-scenarios").dispatch("click");
  assert.equal(elements.get("scenario-panel").hidden, false);
  assert.equal(elements.get("scenario-list").children.length, 2);
  assert.equal(elements.get("scenario-list").children[0].children[1].children[0].textContent,
    "<img src=x onerror=alert(1)>");

  const checkboxes = elements.get("scenario-list").children.map((label) => label.children[0]);
  checkboxes.forEach((checkbox) => { checkbox.checked = true; });
  await checkboxes[0].dispatch("change");
  await checkboxes[1].dispatch("change");
  assert.equal(elements.get("compare").disabled, false);

  await elements.get("compare").dispatch("click");
  assert.equal(elements.get("results").hidden, false);
  assert.equal(elements.get("status").textContent, "گزارش برای 14 روز تقویمی آماده شد.");
  const coverage = elements.get("evidence-coverage").children;
  assert.equal(coverage.length, 5);
  assert.equal(coverage[0].children[0].textContent, "۲");
  assert.equal(coverage[1].children[0].textContent, "۲");
  assert.equal(coverage[2].children[0].textContent, "۱");
  assert.equal(coverage[3].children[0].textContent, "۱");
  assert.equal(coverage[4].children[0].textContent, "۱");
  assert.equal(coverage[4].children[1].textContent, "کمپین دارای دادهٔ تبدیل · از 2 کمپین");
  const channelRows = elements.get("channel-coverage").children;
  assert.equal(channelRows.length, 2);
  assert.deepEqual(channelRows[0].children.map((cell) => cell.textContent), ["email", "۱", "۱", "۱", "۰"]);
  assert.deepEqual(channelRows[1].children.map((cell) => cell.textContent), ["social", "۱", "۰", "۰", "۱"]);
  const gaps = elements.get("evidence-gaps").children;
  assert.equal(gaps.length, 2);
  assert.deepEqual(gaps[0].children.map((cell) => cell.textContent),
    ["Spring launch", "email", "دادهٔ تبدیل"]);
  assert.deepEqual(gaps[1].children.map((cell) => cell.textContent),
    ["Brand awareness", "social", "هزینهٔ ثبت‌شده، دادهٔ سرنخ"]);  assert.equal(elements.get("scenario-results").children[0].children[0].textContent,
    "<img src=x onerror=alert(1)>");
  await elements.get("export-csv").dispatch("click");
  assert.equal(elements.get("status").textContent, "فایل CSV گزارش آماده شد.");
  const anchor = downloads.find((item) => item instanceof Element);
  assert.ok(anchor && anchor.clicked && anchor.removed);
  assert.equal(anchor.download, "budget-comparison-2026-10-01-2026-10-14.csv");
  const blob = downloads.find((item) => item instanceof Blob);
  assert.ok(blob);
  const bytes = new Uint8Array(await blob.arrayBuffer());
  assert.deepEqual(Array.from(bytes.slice(0, 3)), [0xef, 0xbb, 0xbf]);
  const csv = new TextDecoder("utf-8", { ignoreBOM: true }).decode(bytes);
  assert.ok(csv.startsWith("\uFEFF"));
  assert.ok(csv.includes('"هزینه ثبت‌شده"'));
  assert.ok(csv.includes('"کمپین دارای دادهٔ تبدیل"'));
  assert.ok(csv.includes('"پوشش کانال"'));
  assert.ok(csv.includes('"social"'));
  assert.ok(csv.includes('"شکاف شواهد"'));
  assert.ok(csv.includes('"دادهٔ تبدیل"'));
  assert.ok(csv.includes('"Spring launch"'));
  assert.ok(csv.includes('"\'=HYPERLINK(""https://evil.example"",""open"")"'),
    "formula-like labels must be neutralized and CSV-escaped");

  const listCall = calls.find((call) => call.path.startsWith("/api/v1/crm/budget-scenarios?"));
  assert.ok(listCall);
  assert.equal(listCall.options.credentials, "same-origin");
  assert.equal(listCall.options.headers["X-Workspace-ID"], workspace.id);
  const listQuery = new URLSearchParams(listCall.path.split("?")[1]);
  assert.equal(listQuery.get("organization_unit_id"), "root-1");
  assert.equal(listQuery.get("status"), "draft");

  const compareCall = calls.find((call) => call.path.startsWith("/api/v1/crm/budget-scenarios/compare/"));
  assert.ok(compareCall);
  assert.equal(compareCall.options.headers["X-Workspace-ID"], workspace.id);
  const compareQuery = new URLSearchParams(compareCall.path.split("?")[1]);
  assert.deepEqual(compareQuery.getAll("scenario_ids"), ["scenario-1", "scenario-2"]);
  assert.equal(compareQuery.get("period_start"), "2026-10-01");
  assert.equal(compareQuery.get("period_end"), "2026-10-14");
  console.log("Budget comparison client behavior passed.");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
