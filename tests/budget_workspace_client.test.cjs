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
    assert.ok(["input[type=checkbox]:checked", 'input[type="checkbox"]'].includes(selector));
    const onlyChecked = selector.endsWith(":checked");
    const matches = [];
    const visit = (node) => {
      if (node.tagName === "INPUT" && node.type === "checkbox" && (!onlyChecked || node.checked)) {
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
  "period-comparison-period", "period-comparison", "channel-period-comparison", "unit-cost-comparison",
  "target-outcomes-note", "target-outcomes",
  "channel-target-summary-note", "channel-target-summary",
  "target-period-comparison-note", "target-period-comparison",
  "lead-conversion-ratio", "campaign-unit-cost", "objective-performance", "objective-budget-reconciliation",
];
const elements = new Map(ids.map((id) => [id, new Element(id.includes("id") ? "select" : "div")]));
elements.get("load-scenarios").tagName = "BUTTON";
elements.get("compare").tagName = "BUTTON";
elements.get("period-start").value = "2026-10-01";
elements.get("period-end").value = "2026-10-14";

const calls = [];
const reportUrls = [];
const pageWindow = {
  location: {
    search: "?workspace_id=workspace-1&organization_unit_id=root-1&period_start=2026-10-01&period_end=2026-10-14&scenario_ids=scenario-1&scenario_ids=scenario-2",
    pathname: "/workspace/budget-scenario-comparison",
    hash: "#results",
  },
  history: { replaceState: (_state, _title, url) => reportUrls.push(url) },
};
const downloads = [];
const body = { appendChild: (node) => downloads.push(node) };
const urlApi = { createObjectURL: (blob) => { downloads.push(blob); return "blob:report"; }, revokeObjectURL: (url) => downloads.push("revoked:" + url) };
const workspace = { id: "workspace-1", name: "Demo workspace", root_organization_id: "root-1" };
const scenarios = [
  { id: "scenario-1", name: "<img src=x onerror=alert(1)>", allocation_count: 2 },
  { id: "scenario-2", name: '=HYPERLINK("https://evil.example","open")', allocation_count: 2 },
];
const targetPortfolio = {
  period_start: "2026-10-01",
  period_end: "2026-10-14",
  organization_unit_id: "root-1",
  grouped_by: "channel",
  campaign_count: 1,
  campaign_list_truncated: false,
  campaigns: [{
    campaign_id: "campaign-1",
    target_plan_id: "target-plan-1",
    name: "Spring launch",
    organization_unit_id: "root-1",
    group_key: "email",
    metrics: {
      leads: { target: 10, actual: 12, status: "met", currency: null, observed_days: 1, period_days: 14, recorded_day_coverage_percent: "7.14" },
      conversions: { target: 4, actual: null, status: "no_data", currency: null, observed_days: 0, period_days: 14, recorded_day_coverage_percent: "0" },
    },
  }],
};
const previousTargetPortfolio = {
  ...targetPortfolio,
  period_start: "2026-09-17",
  period_end: "2026-09-30",
  campaigns: [{
    ...targetPortfolio.campaigns[0],
    target_plan_id: "target-plan-previous",
    metrics: {
      leads: { ...targetPortfolio.campaigns[0].metrics.leads, actual: 8, status: "not_met" },
      conversions: { ...targetPortfolio.campaigns[0].metrics.conversions },
    },
  }],
};
let reportCampaigns = null;
const fetch = async (path, options = {}) => {
  calls.push({ path, options });
  let payload;
  if (path === "/api/v1/system/workspaces") {
    payload = [workspace];
  } else if (path === "/api/v1/system/organization-units") {
    payload = [{ id: "root-1", name: "مرکز اصلی", parent_id: null, unit_type: "root" }];
  } else if (path.startsWith("/api/v1/crm/budget-scenarios?")) {
    payload = scenarios;
  } else if (path.startsWith("/api/v1/crm/analytics/campaign-target-performance/portfolio?")) {
    const query = new URLSearchParams(path.split("?")[1]);
    payload = query.get("period_start") === "2026-09-17" ? previousTargetPortfolio : targetPortfolio;
  } else if (path.startsWith("/api/v1/crm/budget-scenarios/compare/performance-context?")) {
    const query = new URLSearchParams(path.split("?")[1]);
    if (query.get("period_start") === "2026-09-17") {
      payload = {
        period_calendar_days: 14,
        scenarios: [],
        campaigns: [{
          campaign_id: "campaign-1", campaign_name: "Spring launch", channel: "email", objective_key: "acquisition", objective_key: "acquisition", objective_key: "acquisition",
          recorded_spend_by_currency: { USD: 600 },
          metrics: { leads: { actual: 10 }, conversions: { actual: 2 } },
          scenario_allocations: [],
        }],
      };
    } else {
    payload = {
      period_calendar_days: 14,
      scenarios: [
        { name: scenarios[0].name, reconciliation_by_currency: { USD: {
          planned_amount: 1200, comparable_planned_amount: 1000, observed_spend_amount: 900,
          variance_amount: 100, allocation_coverage_percent: 80, currency_mismatch_allocation_count: 1,
        } } },
        { name: scenarios[1].name, reconciliation_by_currency: {} },
      ],
      campaigns: reportCampaigns || [{
        campaign_id: "campaign-1", campaign_name: "Spring launch", channel: "email", objective_key: "acquisition", objective_key: "acquisition",
        recorded_spend_by_currency: { USD: 900 },
        metrics: { leads: { actual: 12, recorded_day_coverage_percent: 80 }, conversions: { actual: null, recorded_day_coverage_percent: 60 } },
        scenario_allocations: [{
          scenario_name: scenarios[1].name, planned_budget_currency: "USD", planned_budget_amount: 1000,
          actual_spend_in_allocation_currency: null, variance_amount: null,
        }],
      }, {
        campaign_id: "campaign-2", campaign_name: "Brand awareness", channel: "email", objective_key: "awareness", objective_key: "awareness", objective_key: "awareness",
        recorded_spend_by_currency: {},
        metrics: { leads: { actual: null }, conversions: { actual: 3 } },
        scenario_allocations: [{
          scenario_name: scenarios[1].name, planned_budget_currency: "EUR", planned_budget_amount: 500,
          actual_spend_in_allocation_currency: null, variance_amount: null,
        }],
      }],
    };
    }
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
  window: pageWindow,
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
  await settle();
  assert.equal(elements.get("workspace-id").value, workspace.id);
  assert.equal(elements.get("organization-id").value, "root-1");
  assert.equal(elements.get("organization-id").children[1].textContent, "مرکز اصلی");
  assert.equal(elements.get("results").hidden, false, "a valid report link should reload its report");
  assert.deepEqual(elements.get("target-outcomes").children.map((row) => row.children.map((cell) => cell.textContent)), [
    ["Spring launch", "تبدیل", "۴", "ثبت نشده", "دادهٔ کافی ثبت نشده", "۰٪"],
    ["Spring launch", "سرنخ", "۱۰", "۱۲", "هدف محقق‌شده", "۷٫۱۴٪"],
  ]);
  assert.deepEqual(elements.get("campaign-unit-cost").children.slice(0, 2).map((row) =>
    row.children.map((cell) => cell.textContent)), [
    ["Spring launch", "email", "هزینه به‌ازای سرنخ", "USD", "۶۰ USD", "۷۵ USD", "۲۵٪"],
    ["Spring launch", "email", "هزینه به‌ازای تبدیل", "USD", "۳۰۰ USD", "شاخص ثبت نشده", "نامشخص"],
  ]);
  assert.deepEqual(elements.get("channel-target-summary").children.map((row) =>
    row.children.map((cell) => cell.textContent)), [
    ["email", "تبدیل", "۱", "۰", "۰", "۱", "۰"],
    ["email", "سرنخ", "۱", "۱", "۰", "۰", "۰"],
  ]);
  assert.match(elements.get("channel-target-summary-note").textContent, /وضعیت‌های نامشخص/);
  assert.deepEqual(elements.get("target-period-comparison").children.map((row) =>
    row.children.map((cell) => cell.textContent)), [
    ["email", "تبدیل", "دادهٔ کافی ثبت نشده", "دادهٔ کافی ثبت نشده", "۱"],
    ["email", "سرنخ", "هدف محقق‌نشده", "هدف محقق‌شده", "۱"],
  ]);
  assert.match(elements.get("target-period-comparison-note").textContent, /تغییرها توصیفی‌اند/);
  assert.match(elements.get("period-comparison-period").textContent, /2026-09-17 تا 2026-09-30/);
  const periodRows = elements.get("period-comparison").children;
  assert.deepEqual(periodRows.map((row) => row.children.map((cell) => cell.textContent)), [
    ["سرنخ", "۱۰", "۱۲", "۲", "۲۰٪"],
    ["تبدیل", "۲", "۳", "۱", "۵۰٪"],
    ["هزینهٔ ثبت‌شده · USD", "۶۰۰ USD", "۹۰۰ USD", "۳۰۰ USD", "۵۰٪"],
  ]);
  const channelComparison = elements.get("channel-period-comparison").children;
  assert.deepEqual(channelComparison.map((row) => row.children.map((cell) => cell.textContent)), [
    ["email", "سرنخ", "۱۰", "۱۲", "۲", "۲۰٪"],
    ["email", "تبدیل", "۲", "۳", "۱", "۵۰٪"],
    ["email", "هزینهٔ ثبت‌شده · USD", "۶۰۰ USD", "۹۰۰ USD", "۳۰۰ USD", "۵۰٪"],
  ]);
  const unitCosts = elements.get("unit-cost-comparison").children;
  assert.deepEqual(unitCosts.map((row) => row.children.map((cell) => cell.textContent)), [
    ["email", "هزینه به‌ازای هر سرنخ", "USD", "۶۰ USD", "۷۵ USD", "۲۵٪", "۱۲", "۱"],
    ["email", "هزینه به‌ازای هر تبدیل", "USD", "۳۰۰ USD", "ثبت نشده", "نامشخص", "—", "۰"],
  ]);
  assert.equal(elements.get("scenario-list").children[0].children[0].checked, true);
  assert.equal(elements.get("scenario-list").children[1].children[0].checked, true);
  assert.ok(reportUrls[0].includes("workspace_id=workspace-1"));
  assert.ok(reportUrls[0].includes("organization_unit_id=root-1"));
  assert.ok(reportUrls[0].includes("scenario_ids=scenario-1"));
  assert.ok(reportUrls[0].includes("scenario_ids=scenario-2"));
  assert.ok(reportUrls[0].endsWith("#results"));

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
  assert.equal(coverage[2].children[1].textContent, "کمپین دارای هزینهٔ ثبت‌شده · ۱ از ۲ کمپین · پوشش ۵۰٪");
  assert.equal(coverage[3].children[1].textContent, "کمپین دارای دادهٔ سرنخ · ۱ از ۲ کمپین · پوشش ۵۰٪");
  assert.equal(coverage[4].children[1].textContent, "کمپین دارای دادهٔ تبدیل · ۱ از ۲ کمپین · پوشش ۵۰٪");
  const channelRows = elements.get("channel-coverage").children;
  assert.equal(channelRows.length, 1);
  assert.deepEqual(channelRows[0].children.map((cell) => cell.textContent),
    ["email", "۲", "۱ / ۲ · ۵۰٪", "۱ / ۲ · ۵۰٪", "۱ / ۲ · ۵۰٪"]);
  const gaps = elements.get("evidence-gaps").children;
  assert.equal(gaps.length, 2);
  assert.deepEqual(gaps[0].children.map((cell) => cell.textContent),
    ["Spring launch", "email", "دادهٔ تبدیل"]);
  assert.deepEqual(gaps[1].children.map((cell) => cell.textContent),
    ["Brand awareness", "email", "هزینهٔ ثبت‌شده، دادهٔ سرنخ"]);
  assert.equal(elements.get("scenario-results").children[0].children[0].textContent,
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
  assert.ok(csv.includes('"نرخ پوشش هزینهٔ ثبت‌شده (درصد)"'));
  assert.ok(csv.includes('"نرخ پوشش دادهٔ تبدیل (درصد)","50"'));
  assert.ok(csv.includes('"نرخ پوشش دادهٔ سرنخ (درصد)","50"'));
  assert.ok(csv.includes('"email"'));
  assert.ok(csv.includes('"مقایسه با بازه قبلی"'));
  assert.ok(csv.includes('"سرنخ · تغییر"'));
  assert.ok(csv.includes('"مقایسه کانال"'));
  assert.ok(csv.includes('"هزینهٔ واحد ثبت‌شده"'));
  assert.ok(csv.includes('"هزینه به‌ازای هر سرنخ"'));
  assert.ok(csv.includes('"هزینهٔ واحد کمپین"'));
  assert.ok(csv.includes('"عملکرد هدف بازاریابی"'));
  assert.ok(csv.includes('"تطبیق بودجه بر اساس هدف"'));
  assert.ok(csv.includes("سهم از بودجه سناریو"));
  assert.ok(csv.includes('"وضعیت هدف کمپین"'));
  assert.ok(csv.includes('وضعیت: هدف محقق‌شده'));
  assert.ok(csv.includes('"خلاصه هدف کانال"'));
  assert.ok(csv.includes('"محقق‌شده: 1؛ محقق‌نشده: 0؛ داده ناکافی: 0؛ نامشخص: 0"'));
  assert.ok(csv.includes('"تغییر وضعیت هدف"'));
  assert.ok(csv.includes('هدف محقق‌نشده ← هدف محقق‌شده'));
  assert.ok(csv.includes('"شکاف شواهد"'));
  assert.ok(csv.includes('"دادهٔ تبدیل"'));
  assert.ok(csv.includes('"Spring launch"'));
  assert.ok(csv.includes('"\'=HYPERLINK(""https://evil.example"",""open"")"'),
    "formula-like labels must be neutralized and CSV-escaped");

  reportCampaigns = [
    {
      campaign_id: "campaign-1", campaign_name: "Spring launch", channel: "email", objective_key: "acquisition",
      recorded_spend_by_currency: { USD: 900 },
      metrics: { leads: { actual: 12 }, conversions: { actual: 3 } },
      scenario_allocations: [{
        scenario_name: scenarios[0].name, planned_budget_currency: "USD", planned_budget_amount: 1000,
        actual_spend_in_allocation_currency: 650, variance_amount: 350,
      }],
    },
    {
      campaign_id: "campaign-2", campaign_name: "Brand awareness", channel: "email", objective_key: "awareness",
      recorded_spend_by_currency: {},
      metrics: { leads: { actual: 5 }, conversions: { actual: 3 } },
      scenario_allocations: [{
        scenario_name: scenarios[1].name, planned_budget_currency: "EUR", planned_budget_amount: 500,
        actual_spend_in_allocation_currency: null, variance_amount: null,
      }, {
        scenario_name: scenarios[0].name, planned_budget_currency: "USD", planned_budget_amount: 500,
        actual_spend_in_allocation_currency: null, variance_amount: null,
      }],
    },
  ];
  await elements.get("compare").dispatch("click");
  assert.deepEqual(elements.get("objective-performance").children.map((row) =>
    row.children.map((cell) => cell.textContent)), [
    ["acquisition", "email", "سرنخ ثبت‌شده", "۱۰", "۱۲", "۲", "۱ / ۱", "۱ / ۱"],
    ["acquisition", "email", "تبدیل ثبت‌شده", "۲", "۳", "۱", "۱ / ۱", "۱ / ۱"],
    ["awareness", "email", "سرنخ ثبت‌شده", "ثبت نشده", "۵", "نامشخص", "۰ / ۰", "۱ / ۱"],
    ["awareness", "email", "تبدیل ثبت‌شده", "ثبت نشده", "۳", "نامشخص", "۰ / ۰", "۱ / ۱"],
  ]);
  assert.deepEqual(elements.get("objective-budget-reconciliation").children.map((row) =>
    row.children.map((cell) => cell.textContent)), [
    ["awareness", scenarios[0].name, "USD", "۵۰۰ USD", "۰ USD", "نامشخص", "نامشخص", "۰ / ۱", "۳۳٫۳۳٪"],
    ["awareness", scenarios[1].name, "EUR", "۵۰۰ EUR", "۰ EUR", "نامشخص", "نامشخص", "۰ / ۱", "۱۰۰٪"],
    ["acquisition", scenarios[0].name, "USD", "۱٬۰۰۰ USD", "۱٬۰۰۰ USD", "۶۵۰ USD", "۳۵۰ USD", "۱ / ۱", "۶۶٫۶۷٪"],
  ]);
  assert.deepEqual(elements.get("lead-conversion-ratio").children.map((row) =>
    row.children.map((cell) => cell.textContent)), [
    ["email", "۲۰٪ · ۱ کمپین · ۲ / ۱۰", "۳۵٫۲۹٪ · ۲ کمپین · ۶ / ۱۷", "۱۵٫۲۹ واحد درصد"],
  ]);
  await elements.get("export-csv").dispatch("click");
  const ratioCsv = new TextDecoder("utf-8", { ignoreBOM: true }).decode(
    new Uint8Array(await downloads.filter((item) => item instanceof Blob).at(-1).arrayBuffer()));
  assert.ok(ratioCsv.includes('"نسبت تبدیل به سرنخ"'));
  assert.ok(ratioCsv.includes('"تبدیل ثبت‌شده به سرنخ ثبت‌شده (درصد)","35.294117647058826"'));

  reportCampaigns = [];
  await elements.get("compare").dispatch("click");
  assert.equal(elements.get("evidence-coverage").children[2].children[1].textContent,
    "کمپین دارای هزینهٔ ثبت‌شده · ۰ از ۰ کمپین · پوشش نامشخص");
  await elements.get("export-csv").dispatch("click");
  const exportedBlobs = downloads.filter((item) => item instanceof Blob);
  const emptyReportCsv = new TextDecoder("utf-8", { ignoreBOM: true }).decode(new Uint8Array(await exportedBlobs.at(-1).arrayBuffer()));
  assert.ok(emptyReportCsv.includes('"نرخ پوشش هزینهٔ ثبت‌شده (درصد)","","مخرج صفر؛ نامشخص"'));

  const listCall = calls.find((call) => call.path.startsWith("/api/v1/crm/budget-scenarios?"));
  assert.ok(listCall);
  assert.equal(listCall.options.credentials, "same-origin");
  assert.equal(listCall.options.headers["X-Workspace-ID"], workspace.id);
  const listQuery = new URLSearchParams(listCall.path.split("?")[1]);
  assert.equal(listQuery.get("organization_unit_id"), "root-1");
  assert.equal(listQuery.get("status"), "draft");

  const targetCall = calls.find((call) => call.path.startsWith("/api/v1/crm/analytics/campaign-target-performance/portfolio?"));
  assert.ok(targetCall);
  assert.equal(targetCall.options.headers["X-Workspace-ID"], workspace.id);
  const targetQuery = new URLSearchParams(targetCall.path.split("?")[1]);
  assert.equal(targetQuery.get("period_start"), "2026-10-01");
  assert.equal(targetQuery.get("period_end"), "2026-10-14");
  assert.equal(targetQuery.get("organization_unit_id"), "root-1");
  const priorTargetCall = calls.find((call) => {
    if (!call.path.startsWith("/api/v1/crm/analytics/campaign-target-performance/portfolio?")) return false;
    return new URLSearchParams(call.path.split("?")[1]).get("period_start") === "2026-09-17";
  });
  assert.ok(priorTargetCall);
  const priorTargetQuery = new URLSearchParams(priorTargetCall.path.split("?")[1]);
  assert.equal(priorTargetQuery.get("period_end"), "2026-09-30");

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
