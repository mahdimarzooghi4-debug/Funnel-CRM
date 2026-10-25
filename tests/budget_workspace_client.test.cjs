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
  "target-variance-summary-note", "target-variance-summary",
  "campaign-target-variance-note", "campaign-target-variance",
  "variance-review-panel", "variance-review-assessment", "variance-review-action",
  "save-variance-review", "cancel-variance-review", "variance-review-next-step",
  "variance-review-created-note", "create-variance-review-work-item",
  "assign-follow-up-to-me", "follow-up-due-at",
  "learning-portfolio-note", "learning-lesson-query", "search-learning-lessons", "export-learning-csv",
  "learning-campaign-query", "learning-review-status",
  "learning-overdue-only", "learning-portfolio-counts", "learning-portfolio-items",
  "learning-portfolio-pagination", "learning-page-previous", "learning-page-range", "learning-page-next",
  "target-period-comparison-note", "target-period-comparison",
  "lead-conversion-ratio", "campaign-unit-cost", "objective-performance", "objective-budget-reconciliation", "objective-unit-cost", "scenario-objective-evidence", "objective-unit-cost-distribution",
];
const elements = new Map(ids.map((id) => [id, new Element(id.includes("id") ? "select" : "div")]));
elements.get("load-scenarios").tagName = "BUTTON";
elements.get("compare").tagName = "BUTTON";
elements.get("save-variance-review").tagName = "BUTTON";
elements.get("cancel-variance-review").tagName = "BUTTON";
elements.get("create-variance-review-work-item").tagName = "BUTTON";
elements.get("search-learning-lessons").tagName = "BUTTON";
elements.get("export-learning-csv").tagName = "BUTTON";
elements.get("learning-page-previous").tagName = "BUTTON";
elements.get("learning-page-next").tagName = "BUTTON";
elements.get("learning-review-status").tagName = "SELECT";
elements.get("variance-review-panel").hidden = true;
elements.get("variance-review-next-step").hidden = true;
elements.get("assign-follow-up-to-me").checked = true;
elements.get("follow-up-due-at").value = "2026-10-26T12:00";
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
const workspace = { id: "workspace-1", membership_id: "membership-1", name: "Demo workspace", root_organization_id: "root-1" };
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
  groups: [{
    key: "email",
    campaign_count: 1,
    metric_variances: {
      leads: {
        targeted_campaign_count: 1, complete_campaign_count: 0, incomplete_campaign_count: 1,
        target_total: 10, complete_actual_total: 0, complete_campaign_target_total: 0,
        complete_variance: 0, incomplete_target_total: 10, partial_actual_total: 12,
      },
    },
  }],
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
const learningPortfolio = {
  total_count: 1, planned_count: 1, evaluated_count: 0,
  can_update_work_items: true,
  can_manage_marketing_reviews: true,
  work_item_counts: { linked: 1, without_work_item: 0, open: 1, in_progress: 0, completed: 0, cancelled: 0, overdue: 0 },
  items: [{
    campaign_name: "Spring launch",
    baseline_period_start: "2026-10-01", baseline_period_end: "2026-10-14",
    review: { id: "review-portfolio-1", campaign_id: "campaign-portfolio-1", status: "planned", assessment: "بررسی افت سرنخ", corrective_action: "بررسی داده منبع", follow_up_effectiveness: null, lesson_learned: null },
    work_item: { id: "work-portfolio-1", status: "open", assigned_membership_id: "membership-other", due_at: null },
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
  } else if (path === "/api/v1/crm/work-items/work-portfolio-1" && options.method === "PATCH") {
    payload = { id: "work-portfolio-1", status: JSON.parse(options.body).status };
  } else if (path === "/api/v1/crm/campaigns/campaign-portfolio-1/targets" && options.method === "GET") {
    payload = [{ id: "target-follow-up-1", period_start: "2026-10-15", period_end: "2026-10-28" }];
  } else if (path === "/api/v1/crm/marketing-learning/reviews/review-portfolio-1/evaluation" && options.method === "PATCH") {
    learningPortfolio.items[0].review.status = "evaluated";
    learningPortfolio.items[0].review.follow_up_effectiveness = "دادهٔ مشاهده‌شده پس از اقدام بهبود را نشان می‌دهد.";
    learningPortfolio.items[0].review.lesson_learned = "زمان‌بندی پیگیری باید در برنامهٔ کمپین ثبت شود.";
    payload = { review: { status: "evaluated" } };
  } else if (path === "/api/v1/crm/marketing-learning/reviews/review-portfolio-1" && options.method === "GET") {
    payload = {
      review: { ...learningPortfolio.items[0].review },
      baseline: { period_start: "2026-10-01", period_end: "2026-10-14", metrics: {
        leads: { target: 12, actual: 8, currency: null, observed_days: 7, period_days: 14, recorded_day_coverage_percent: "50.00" },
        conversions: { target: 2, actual: 0, currency: null, observed_days: 0, period_days: 14, recorded_day_coverage_percent: "0.00" },
      } },
      follow_up: { period_start: "2026-10-15", period_end: "2026-10-28", metrics: {
        leads: { target: 15, actual: 13, currency: null, observed_days: 14, period_days: 14, recorded_day_coverage_percent: "100.00" },
        conversions: { target: 3, actual: 2, currency: null, observed_days: 4, period_days: 14, recorded_day_coverage_percent: "28.57" },
      } },
    };
  } else if (path.startsWith("/api/v1/crm/marketing-learning/reviews/portfolio?") && (options.method || "GET") === "GET") {
    const query = new URLSearchParams(path.split("?")[1]);
    assert.equal(query.get("organization_unit_id"), "root-1");
    assert.equal(query.get("period_start"), "2026-10-01");
    assert.equal(query.get("period_end"), "2026-10-14");
    const offset = Number(query.get("offset") || 0);
    const pageItems = offset === 0 ? learningPortfolio.items : [{
      ...learningPortfolio.items[0], campaign_name: "Spring follow-up",
      review: { ...learningPortfolio.items[0].review, id: "review-portfolio-2", lesson_learned: "=SUM(A1:A2)" },
    }];
    payload = { ...learningPortfolio, items: pageItems, total_count: 101, offset, limit: Number(query.get("limit") || 50), has_more: offset === 0,
      lesson_query: query.get("lesson_query"), campaign_query: query.get("campaign_query"), status_filter: query.get("status") };
  } else if (path === "/api/v1/crm/marketing-learning/reviews" && options.method === "POST") {
    payload = { id: "review-1", status: "planned" };
  } else if (path === "/api/v1/crm/marketing-learning/reviews/review-1/work-item" && options.method === "POST") {
    payload = { created: true, work_item: { id: "work-1", status: "open", assigned_membership_id: "membership-1", due_at: "2026-10-26T12:00:00Z" } };
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
  assert.deepEqual(elements.get("objective-unit-cost").children.map((row) =>
    row.children.map((cell) => cell.textContent)), [
    ["acquisition", "USD", "سرنخ ثبت‌شده", "۹۰۰ USD", "۱۲", "۷۵ USD", "۱ / ۱"],
    ["acquisition", "USD", "تبدیل ثبت‌شده", "ثبت نشده", "ثبت نشده", "نامشخص", "۰ / ۱"],
  ]);
  assert.deepEqual(elements.get("channel-target-summary").children.map((row) =>
    row.children.map((cell) => cell.textContent)), [
    ["email", "تبدیل", "۱", "۰", "۰", "۱", "۰"],
    ["email", "سرنخ", "۱", "۱", "۰", "۰", "۰"],
  ]);
  assert.match(elements.get("channel-target-summary-note").textContent, /وضعیت‌های نامشخص/);
  assert.deepEqual(elements.get("target-variance-summary").children.map((row) => row.children.map((cell) => cell.textContent)), [
    ["email", "سرنخ", "۱", "۰ / ۱", "۱۰", "نامشخص", "نامشخص", "۱۰", "۱۲"],
  ]);
  assert.match(elements.get("target-variance-summary-note").textContent, /علت را ثابت نمی‌کند/);
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
  assert.equal(elements.get("learning-portfolio-counts").children.length, 6);
  assert.equal(elements.get("learning-portfolio-items").children.length, 1);
  elements.get("learning-overdue-only").checked = true;
  await elements.get("learning-overdue-only").dispatch("change");
  const overduePortfolioCall = calls.find((call) => call.path.startsWith("/api/v1/crm/marketing-learning/reviews/portfolio?") && new URLSearchParams(call.path.split("?")[1]).get("overdue_only") === "true");
  assert.ok(overduePortfolioCall, "overdue filter must be applied by the portfolio API");
  elements.get("learning-lesson-query").value = "زمان‌بندی پیگیری";
  await elements.get("search-learning-lessons").dispatch("click");
  const lessonSearchCall = calls.find((call) => call.path.startsWith("/api/v1/crm/marketing-learning/reviews/portfolio?") && new URLSearchParams(call.path.split("?")[1]).get("lesson_query") === "زمان‌بندی پیگیری");
  assert.ok(lessonSearchCall, "lesson search must be applied by the portfolio API");
  const taskRow = elements.get("learning-portfolio-items").children[0];
  const statusSelect = taskRow.children[8].children[0];
  const selfAssignControl = taskRow.children[8].children[1].children[0];
  const dueControl = taskRow.children[8].children[2];
  const saveTaskStatus = taskRow.children[8].children[3];
  assert.equal(statusSelect.children[1].value, "in_progress");
  statusSelect.value = "in_progress";
  dueControl.value = "2026-10-26T12:00";
  await saveTaskStatus.dispatch("click");
  const taskStatusCall = calls.find((call) => call.path === "/api/v1/crm/work-items/work-portfolio-1");
  assert.ok(taskStatusCall);
  assert.equal(taskStatusCall.options.method, "PATCH");
  assert.deepEqual(JSON.parse(taskStatusCall.options.body), {
    status: "in_progress",
    due_at: new Date("2026-10-26T12:00").toISOString(),
  });
  const refreshedTaskRow = elements.get("learning-portfolio-items").children[0];
  const assignmentCell = refreshedTaskRow.children[8];
  assignmentCell.children[1].children[0].checked = true;
  await assignmentCell.children[3].dispatch("click");
  const assignmentCall = calls.filter((call) => call.path === "/api/v1/crm/work-items/work-portfolio-1")[1];
  assert.deepEqual(JSON.parse(assignmentCall.options.body), { assigned_membership_id: "membership-1" });
  const postAssignmentRow = elements.get("learning-portfolio-items").children[0];
  const evaluationButton = postAssignmentRow.children[8].children[4];
  await evaluationButton.dispatch("click");
  const evaluationForm = postAssignmentRow.children[8].children[5];
  evaluationForm.children[1].value = "target-follow-up-1";
  evaluationForm.children[2].value = "دادهٔ مشاهده‌شده پس از اقدام بهبود را نشان می‌دهد.";
  evaluationForm.children[3].value = "زمان‌بندی پیگیری باید در برنامهٔ کمپین ثبت شود.";
  await evaluationForm.children[4].dispatch("click");
  const evaluationCall = calls.find((call) => call.path === "/api/v1/crm/marketing-learning/reviews/review-portfolio-1/evaluation");
  assert.ok(evaluationCall);
  assert.deepEqual(JSON.parse(evaluationCall.options.body), {
    follow_up_target_plan_id: "target-follow-up-1",
    follow_up_effectiveness: "دادهٔ مشاهده‌شده پس از اقدام بهبود را نشان می‌دهد.",
    lesson_learned: "زمان‌بندی پیگیری باید در برنامهٔ کمپین ثبت شود.",
    status: "evaluated",
  });
  assert.deepEqual(elements.get("learning-portfolio-items").children[0].children.map((cell) => cell.textContent), [
    "Spring launch", "2026-10-01 تا 2026-10-14", "ارزیابی‌شده",
    "بررسی افت سرنخ", "بررسی داده منبع", "باز", "دارای مسئول", "—", "",
  ]);
  const evidenceRow = elements.get("learning-portfolio-items").children[0];
  assert.equal(evidenceRow.children[8].children[4].textContent, "مشاهدهٔ شواهد");
  await evidenceRow.children[8].children[4].dispatch("click");
  const evidenceCall = calls.find((call) => call.path === "/api/v1/crm/marketing-learning/reviews/review-portfolio-1" && call.options.method === "GET");
  assert.ok(evidenceCall);
  const evidencePanel = evidenceRow.children[8].children[5];
  const evidenceTableRows = evidencePanel.children[2].children[1].children;
  const leadEvidence = evidenceTableRows[0];
  const followUpActual = leadEvidence.children[4].textContent;
  assert.ok(["13", "۱۳"].some((digits) => followUpActual.includes(digits)));
  assert.ok(leadEvidence.children[5].textContent.includes("+"));
  assert.ok(leadEvidence.children[6].textContent.includes("+"));
  assert.ok(["62", "۶۲"].some((digits) => leadEvidence.children[6].textContent.includes(digits)));
  assert.ok(leadEvidence.children[7].textContent.includes("7 از 14 روز"));
  assert.ok(evidenceTableRows[1].children[6].textContent.includes("مبنای صفر"));
  assert.ok(evidencePanel.children[5].textContent.includes("رابطهٔ علّی را اثبات نمی‌کند"));
  elements.get("learning-campaign-query").value = "Spring";
  elements.get("learning-review-status").value = "evaluated";
  await elements.get("search-learning-lessons").dispatch("click");
  const combinedFilterCall = calls.filter((call) => call.path.startsWith("/api/v1/crm/marketing-learning/reviews/portfolio?")).at(-1);
  const combinedFilterQuery = new URLSearchParams(combinedFilterCall.path.split("?")[1]);
  assert.equal(combinedFilterQuery.get("campaign_query"), "Spring");
  assert.equal(combinedFilterQuery.get("status"), "evaluated");
  await elements.get("learning-page-next").dispatch("click");
  const nextPageCall = calls.filter((call) => call.path.startsWith("/api/v1/crm/marketing-learning/reviews/portfolio?")).at(-1);
  assert.equal(new URLSearchParams(nextPageCall.path.split("?")[1]).get("offset"), "100");
  assert.equal(new URLSearchParams(nextPageCall.path.split("?")[1]).get("lesson_query"), "زمان‌بندی پیگیری");
  assert.equal(new URLSearchParams(nextPageCall.path.split("?")[1]).get("campaign_query"), "Spring");
  assert.equal(new URLSearchParams(nextPageCall.path.split("?")[1]).get("status"), "evaluated");
  assert.equal(elements.get("learning-page-range").textContent, "۱۰۱ تا ۱۰۱ از ۱۰۱");
  assert.equal(elements.get("learning-page-next").disabled, true);
  await elements.get("learning-page-previous").dispatch("click");
  const previousPageCall = calls.filter((call) => call.path.startsWith("/api/v1/crm/marketing-learning/reviews/portfolio?")).at(-1);
  assert.equal(new URLSearchParams(previousPageCall.path.split("?")[1]).get("offset"), "0");
  await elements.get("export-learning-csv").dispatch("click");
  const learningCsvBlob = downloads.filter((item) => item instanceof Blob).at(-1);
  const learningCsv = new TextDecoder("utf-8", { ignoreBOM: true }).decode(new Uint8Array(await learningCsvBlob.arrayBuffer()));
  assert.ok(learningCsv.includes('"Spring launch"'));
  assert.ok(learningCsv.includes('"Spring follow-up"'));
  assert.ok(learningCsv.includes("'=SUM(A1:A2)"));
  const exportCalls = calls.filter((call) => call.path.startsWith("/api/v1/crm/marketing-learning/reviews/portfolio?")).slice(-2);
  assert.deepEqual(exportCalls.map((call) => new URLSearchParams(call.path.split("?")[1]).get("offset")), ["0", "100"]);
  exportCalls.forEach((call) => {
    const query = new URLSearchParams(call.path.split("?")[1]);
    assert.equal(query.get("campaign_query"), "Spring");
    assert.equal(query.get("status"), "evaluated");
    assert.equal(query.get("lesson_query"), "زمان‌بندی پیگیری");
    assert.equal(call.options.headers["X-Workspace-ID"], workspace.id);
  });
  const learningPortfolioCall = calls.find((call) => call.path.startsWith("/api/v1/crm/marketing-learning/reviews/portfolio?"));
  assert.ok(learningPortfolioCall);
  assert.equal(learningPortfolioCall.options.headers["X-Workspace-ID"], workspace.id);
  assert.equal(new URLSearchParams(learningPortfolioCall.path.split("?")[1]).get("include_work_items"), "true");
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
  const anchor = downloads.find((item) => item instanceof Element && item.download.startsWith("budget-comparison-"));
  assert.ok(anchor && anchor.clicked && anchor.removed);
  assert.equal(anchor.download, "budget-comparison-2026-10-01-2026-10-14.csv");
  const blob = downloads.filter((item) => item instanceof Blob)[1];
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
  assert.ok(csv.includes('"هزینهٔ واحد هدف بازاریابی"'));
  assert.ok(csv.includes('"سناریو و شواهد هدف"'));
  assert.ok(csv.includes("سهم از بودجه سناریو"));
  assert.ok(csv.includes('"وضعیت هدف کمپین"'));
  assert.ok(csv.includes('وضعیت: هدف محقق‌شده'));
  assert.ok(csv.includes('"خلاصه هدف کانال"'));
  assert.ok(csv.includes('"فاصله هدف و عملکرد"'));
  assert.ok(csv.includes('"فاصله هدف در سطح کمپین"'));
  assert.ok(csv.includes('هدف دوره ناقص: 10؛ عملکرد ناقص ثبت‌شده: 12'));
  assert.ok(csv.includes('دوره ناقص؛ فاصله محاسبه نشده'));
  assert.ok(csv.includes('"محقق‌شده: 1؛ محقق‌نشده: 0؛ داده ناکافی: 0؛ نامشخص: 0"'));
  assert.ok(csv.includes('"تغییر وضعیت هدف"'));
  assert.ok(csv.includes('هدف محقق‌نشده ← هدف محقق‌شده'));
  assert.ok(csv.includes('"شکاف شواهد"'));
  assert.ok(csv.includes('"دادهٔ تبدیل"'));
  assert.ok(csv.includes('"Spring launch"'));
  const campaignVariance = elements.get("campaign-target-variance").children;
  assert.equal(campaignVariance.length, 2);
  assert.deepEqual(campaignVariance[0].children.slice(0, 7).map((cell) => cell.textContent),
    ["Spring launch", "email", "تبدیل", "۴", "ثبت نشده", "نامشخص", "0% · ناقص"]);
  assert.deepEqual(campaignVariance[1].children.slice(0, 7).map((cell) => cell.textContent),
    ["Spring launch", "email", "سرنخ", "۱۰", "۱۲", "نامشخص", "7.14% · ناقص"]);
  const reviewButton = campaignVariance[1].children[7].children[0];
  await reviewButton.dispatch("click");
  assert.equal(elements.get("variance-review-panel").hidden, false);
  assert.ok(elements.get("variance-review-assessment").value.includes("فاصله: محاسبه نشده"));
  elements.get("variance-review-action").value = "بررسی منبع دادهٔ سرنخ";
  await elements.get("save-variance-review").dispatch("click");
  assert.equal(elements.get("variance-review-panel").hidden, false);
  assert.equal(elements.get("variance-review-next-step").hidden, false);
  assert.equal(elements.get("status").textContent,
    "بررسی مدیریتی ثبت شد؛ هیچ بودجه یا اقدامی به‌صورت خودکار تغییر نکرد.");
  const reviewCall = calls.find((call) => call.path === "/api/v1/crm/marketing-learning/reviews");
  assert.ok(reviewCall);
  assert.equal(reviewCall.options.method, "POST");
  assert.equal(reviewCall.options.credentials, "same-origin");
  assert.equal(reviewCall.options.headers["X-Workspace-ID"], workspace.id);
  assert.deepEqual(JSON.parse(reviewCall.options.body), {
    campaign_id: "campaign-1", target_plan_id: "target-plan-1", experiment_id: null,
    assessment: elements.get("variance-review-assessment").value,
    corrective_action: "بررسی منبع دادهٔ سرنخ",
  });
  await elements.get("create-variance-review-work-item").dispatch("click");
  assert.equal(elements.get("status").textContent, "کار پیگیری CRM آمادهٔ واگذاری است.");
  assert.equal(elements.get("variance-review-created-note").textContent,
    "کار پیگیری در صف CRM ایجاد شد؛ به خودتان واگذار شد و موعد آن ثبت شد.");
  const workItemCall = calls.find((call) => call.path.endsWith("/reviews/review-1/work-item"));
  assert.ok(workItemCall);
  assert.equal(workItemCall.options.method, "POST");
  assert.equal(workItemCall.options.credentials, "same-origin");
  assert.equal(workItemCall.options.headers["X-Workspace-ID"], workspace.id);
  assert.deepEqual(JSON.parse(workItemCall.options.body), {
    assigned_membership_id: "membership-1",
    due_at: new Date("2026-10-26T12:00").toISOString(),
    priority: "normal",
  });
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
    ["acquisition", scenarios[0].name, "USD", "۱٬۰۰۰ USD", "۱٬۰۰۰ USD", "۶۵۰ USD", "۳۵۰ USD", "۱ / ۱", "۶۶٫۶۷٪"],
    ["awareness", scenarios[0].name, "USD", "۵۰۰ USD", "۰ USD", "نامشخص", "نامشخص", "۰ / ۱", "۳۳٫۳۳٪"],
    ["awareness", scenarios[1].name, "EUR", "۵۰۰ EUR", "۰ EUR", "نامشخص", "نامشخص", "۰ / ۱", "۱۰۰٪"],
  ]);
  assert.deepEqual(elements.get("scenario-objective-evidence").children.map((row) =>
    row.children.map((cell) => cell.textContent)), [
    ["acquisition", scenarios[0].name, "USD", "۱٬۰۰۰ USD", "۶۶٫۶۷٪", "۷۵ USD", "۱ / ۱", "۳۰۰ USD", "۱ / ۱"],
    ["awareness", scenarios[0].name, "USD", "۵۰۰ USD", "۳۳٫۳۳٪", "نامشخص", "بدون سابقهٔ قابل‌مقایسه", "نامشخص", "بدون سابقهٔ قابل‌مقایسه"],
    ["awareness", scenarios[1].name, "EUR", "۵۰۰ EUR", "۱۰۰٪", "نامشخص", "بدون سابقهٔ قابل‌مقایسه", "نامشخص", "بدون سابقهٔ قابل‌مقایسه"],
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

  reportCampaigns = [
    {
      campaign_id: "campaign-1", campaign_name: "Spring launch", channel: "email", objective_key: "acquisition",
      recorded_spend_by_currency: { USD: 900 },
      metrics: { leads: { actual: 12 }, conversions: { actual: 3 } },
      scenario_allocations: [],
    },
    {
      campaign_id: "campaign-2", campaign_name: "Follow up", channel: "email", objective_key: "acquisition",
      recorded_spend_by_currency: { USD: 100 },
      metrics: { leads: { actual: 2 }, conversions: { actual: 2 } },
      scenario_allocations: [],
    },
  ];
  await elements.get("compare").dispatch("click");
  assert.deepEqual(elements.get("objective-unit-cost-distribution").children.map((row) =>
    row.children.map((cell) => cell.textContent)), [
    ["acquisition", "USD", "هزینه به‌ازای سرنخ", "۲", "۶۲٫۵ USD", "۵۰ USD", "۷۵ USD"],
    ["acquisition", "USD", "هزینه به‌ازای تبدیل", "۲", "۱۷۵ USD", "۵۰ USD", "۳۰۰ USD"],
  ]);
  await elements.get("export-csv").dispatch("click");
  const distributionCsv = new TextDecoder("utf-8", { ignoreBOM: true }).decode(
    new Uint8Array(await downloads.filter((item) => item instanceof Blob).at(-1).arrayBuffer()));
  assert.ok(distributionCsv.includes('"پراکندگی هزینهٔ واحد هدف"'));

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
