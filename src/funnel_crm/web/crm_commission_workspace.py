"""Persian manager workspace for commission plans and calculation snapshots."""

from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["CRM commission workspace"], include_in_schema=False)

_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'unsafe-inline'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}

_PAGE = """<!doctype html>
<html lang="fa" dir="rtl">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <title>مدیریت کمیسیون فروش | فانل CRM</title>
  <style>
    :root{font-family:Tahoma,Arial,sans-serif;color:#182638;background:#f4f7fb}*{box-sizing:border-box}body{margin:0}
    header{background:#12334a;color:#fff;padding:20px max(16px,calc((100vw - 1120px)/2))}header a{color:#fff;margin-inline-start:18px}
    main{max-width:1120px;margin:24px auto;padding:0 16px 48px}h1{font-size:clamp(23px,4vw,32px);margin:0 0 8px}h2{font-size:19px;margin:0 0 14px}
    p{line-height:1.8}.panel{background:#fff;border:1px solid #e0e7ef;border-radius:14px;padding:20px;margin:16px 0;box-shadow:0 5px 18px #142d420d}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}label{display:grid;gap:6px;color:#405367;font-size:13px}
    input,select,button{font:inherit;min-height:42px;border:1px solid #cbd6e0;border-radius:8px;padding:8px 10px;background:#fff;color:#182638}
    button{background:#1578a8;color:#fff;border:0;font-weight:700;cursor:pointer}button:disabled{opacity:.5;cursor:wait}.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}
    #status{min-height:24px;color:#8b3b22}.muted{color:#687b8d;font-size:13px;line-height:1.8}.plan-list,.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}
    .plan,.card{border:1px solid #dce5ed;border-radius:10px;padding:14px}.plan button{margin-top:10px}.table-wrap{overflow:auto}
    table{border-collapse:collapse;width:100%;min-width:660px}th,td{text-align:right;padding:10px;border-bottom:1px solid #e8edf2;vertical-align:top}th{background:#f7f9fb;color:#536579;font-size:13px}
    .tag{display:inline-block;border-radius:99px;padding:4px 9px;background:#e8f3ed;color:#17613b;font-size:12px}.tag.off{background:#f3eeee;color:#824545}
    @media(max-width:560px){.panel{padding:15px}header{line-height:2}}
  </style>
  <script src="/assets/crm-commission-workspace.js" defer></script>
</head>
<body>
  <header><strong>فانل CRM</strong><a href="/workspace/budget-scenario-comparison">تحلیل بودجه</a><a href="/workspace/crm-activity-capture">فعالیت میدانی</a></header>
  <main>
    <h1>مدیریت پلن‌های کمیسیون فروش</h1>
    <p class="muted">پلن‌ها و محاسبه‌های ثبت‌شده را در محدودهٔ مجاز خود مدیریت کنید. محاسبه فقط snapshot پیشنهادی می‌سازد و دستور پرداخت یا حقوق صادر نمی‌کند.</p>
    <p id="status" role="status" aria-live="polite"></p>
    <section class="panel" aria-labelledby="scope-title"><h2 id="scope-title">محدودهٔ کاری</h2>
      <div class="grid"><label for="workspace-id">فضای کاری<select id="workspace-id" required></select></label>
      <label for="organization-id">واحد سازمانی<select id="organization-id" required></select></label></div>
    </section>
    <section class="panel" aria-labelledby="create-title"><h2 id="create-title">ساخت پلن</h2>
      <form id="create-form"><div class="grid">
        <label for="plan-name">نام پلن<input id="plan-name" maxlength="160" required></label>
        <label for="plan-rate">درصد کمیسیون<input id="plan-rate" type="number" min="0.0001" max="100" step="0.0001" required></label>
        <label for="plan-effective-start">شروع اعتبار (اختیاری)<input id="plan-effective-start" type="date"></label>
        <label for="plan-effective-end">پایان اعتبار (اختیاری)<input id="plan-effective-end" type="date"></label>
        <label for="seller-id">شناسهٔ عضویت فروشنده (اختیاری)<input id="seller-id" pattern="[0-9a-fA-F-]{36}" placeholder="خالی = پلن سازمانی"></label>
      </div><div class="actions"><button type="submit">ثبت پلن</button></div></form>
    </section>
    <section class="panel"><h2>پلن‌های قابل مشاهده</h2><div id="plan-list" class="plan-list" aria-live="polite"></div></section>
    <section class="panel" id="selected-plan" hidden><h2>جزئیات پلن</h2><div id="plan-summary"></div>
      <form id="update-form"><div class="grid">
        <label for="update-name">نام جدید<input id="update-name" maxlength="160" required></label>
        <label for="update-rate">درصد جدید<input id="update-rate" type="number" min="0.0001" max="100" step="0.0001" required></label>
        <label for="update-effective-start">شروع اعتبار<input id="update-effective-start" type="date"></label>
        <label for="update-effective-end">پایان اعتبار<input id="update-effective-end" type="date"></label>
        <label for="update-active">وضعیت<select id="update-active"><option value="true">فعال</option><option value="false">غیرفعال</option></select></label>
      </div><div class="actions"><button type="submit">ثبت نسخهٔ جدید</button></div></form>
      <div class="actions"><button id="show-versions" type="button">تاریخچهٔ نسخه‌ها</button><button id="show-calculations" type="button">محاسبه‌های قبلی</button></div>
      <div id="history" class="cards"></div>
    </section>
    <section class="panel" id="calculation-panel" hidden><h2>محاسبهٔ کمیسیون</h2>
      <form id="calculate-form"><div class="grid">
        <label for="period-start">از تاریخ<input id="period-start" type="date" required></label>
        <label for="period-end">تا تاریخ<input id="period-end" type="date" required></label>
      </div><p class="muted">شناسهٔ درخواست برای retry حفظ می‌شود؛ با ثبت موفق، محاسبهٔ بعدی شناسهٔ تازه می‌گیرد.</p>
      <div class="actions"><button id="preview-calculation" type="button">پیش‌نمایش محاسبه</button><button type="submit">ثبت snapshot محاسبه</button></div></form>
      <div id="calculation-result"></div>
    </section>
  </main>
</body>
</html>"""

_SCRIPT = r"""(() => {
  const $ = (id) => document.getElementById(id);
  const workspace = $("workspace-id"), organization = $("organization-id");
  const status = $("status"), plansNode = $("plan-list"), selectedPanel = $("selected-plan");
  const calculationPanel = $("calculation-panel"), historyNode = $("history"), resultNode = $("calculation-result");
  let plans = [], selectedPlan = null;
  const params = new URLSearchParams(location.search);
  function message(text, error = false) { status.textContent = text || ""; status.style.color = error ? "#8b3b22" : "#17613b"; }
  function option(select, value, label) { const node = document.createElement("option"); node.value = value; node.textContent = label; select.appendChild(node); }
  async function api(path, method = "GET", body = undefined, needsWorkspace = true) {
    const headers = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (needsWorkspace) headers["X-Workspace-ID"] = workspace.value;
    const response = await fetch(path, { method, credentials: "same-origin", headers, body: body === undefined ? undefined : JSON.stringify(body) });
    let data = {}; try { data = await response.json(); } catch (_) {}
    if (!response.ok) {
      if (response.status === 401) throw new Error("برای ادامه وارد حساب کاربری شوید.");
      if (response.status === 403) throw new Error("مجوز این عملیات یا محدوده برای حساب شما فعال نیست.");
      throw new Error(data.detail || `عملیات ناموفق بود (${response.status}).`);
    }
    return data;
  }
  function clear(node) { node.replaceChildren(); }
  async function loadOrganizations() {
    organization.replaceChildren(); option(organization, "", "در حال بارگذاری…");
    const units = await api("/api/v1/system/commission-organization-units");
    organization.replaceChildren(); option(organization, "", "واحد سازمانی را انتخاب کنید");
    units.forEach((unit) => option(organization, unit.id, unit.name));
    const requested = units.find((unit) => unit.id === params.get("organization_unit_id"));
    const root = units.find((unit) => unit.unit_type === "root");
    organization.value = requested?.id || root?.id || "";
  }
  function renderPlans() {
    clear(plansNode);
    const visible = plans.filter((plan) => !organization.value || plan.organization_unit_id === organization.value);
    if (!visible.length) { const empty = document.createElement("p"); empty.className = "muted"; empty.textContent = "پلنی در این محدوده ثبت نشده است."; plansNode.appendChild(empty); return; }
    visible.forEach((plan) => {
      const card = document.createElement("article"); card.className = "plan";
      const title = document.createElement("strong"); title.textContent = plan.name;
      const details = document.createElement("p"); details.className = "muted";
      details.textContent = `${plan.rate_percent}% · نسخه ${plan.version} · اعتبار ${plan.effective_start || "بدون شروع"} تا ${plan.effective_end || "بدون پایان"} · ${plan.seller_membership_id || "پلن سازمانی"}`;
      const state = document.createElement("span"); state.className = `tag${plan.is_active ? "" : " off"}`; state.textContent = plan.is_active ? "فعال" : "غیرفعال";
      const button = document.createElement("button"); button.type = "button"; button.textContent = "مدیریت پلن";
      button.addEventListener("click", () => selectPlan(plan)); card.append(title, details, state, button); plansNode.appendChild(card);
    });
  }
  async function loadPlans() { plans = (await api("/api/v1/crm/commission-plans")).items || []; renderPlans(); }
  function selectPlan(plan) {
    selectedPlan = plan; selectedPanel.hidden = false; calculationPanel.hidden = false;
    const summary = $("plan-summary"); clear(summary);
    const p = document.createElement("p"); p.className = "muted";
    p.textContent = `${plan.name} · ${plan.rate_percent}% · نسخه ${plan.version} · اعتبار ${plan.effective_start || "بدون شروع"} تا ${plan.effective_end || "بدون پایان"} · ${plan.is_active ? "فعال" : "غیرفعال"}`; summary.appendChild(p);
    $("update-name").value = plan.name; $("update-rate").value = plan.rate_percent; $("update-active").value = String(plan.is_active);
    $("update-effective-start").value = plan.effective_start || ""; $("update-effective-end").value = plan.effective_end || "";
    historyNode.replaceChildren(); resultNode.replaceChildren();
  }
  function renderHistory(items, type) {
    clear(historyNode);
    if (!items.length) { const p = document.createElement("p"); p.className = "muted"; p.textContent = "سابقه‌ای ثبت نشده است."; historyNode.appendChild(p); return; }
    items.forEach((item) => {
      const card = document.createElement("article"); card.className = "card";
      const title = document.createElement("strong"); title.textContent = type === "versions" ? `نسخه ${item.version}` : `${item.period_start} تا ${item.period_end}`;
      const body = document.createElement("p"); body.className = "muted";
      body.textContent = type === "versions" ? `${item.name} · ${item.rate_percent}% · اعتبار ${item.effective_start || "بدون شروع"} تا ${item.effective_end || "بدون پایان"} · ${item.is_active ? "فعال" : "غیرفعال"}` : `نسخه پلن ${item.plan_version} · نرخ ${item.rate_percent}% · ${item.rows.length} ردیف`;
      card.append(title, body);
      if (type === "calculations") {
        item.rows.forEach((row) => { const line = document.createElement("p"); line.className = "muted"; line.textContent = `${row.seller_membership_id || "بدون انتساب فروشنده"} · ${row.currency} · خالص ${row.net_amount} · کمیسیون ${row.commission_amount}`; card.appendChild(line); });
        const exportButton = document.createElement("button"); exportButton.type = "button"; exportButton.textContent = "دریافت CSV";
        exportButton.addEventListener("click", () => downloadCalculationCsv(item.id)); card.appendChild(exportButton);
      }
      historyNode.appendChild(card);
    });
  }
  async function downloadCalculationCsv(calculationId) {
    try {
      const response = await fetch(`/api/v1/crm/commission-plans/${encodeURIComponent(selectedPlan.id)}/calculations/${encodeURIComponent(calculationId)}/export.csv`, {
        credentials: "same-origin", headers: { Accept: "text/csv", "X-Workspace-ID": workspace.value },
      });
      if (!response.ok) {
        let data = {}; try { data = await response.json(); } catch (_) {}
        throw new Error(data.detail || `دریافت فایل ناموفق بود (${response.status}).`);
      }
      const url = URL.createObjectURL(await response.blob()), link = document.createElement("a");
      link.href = url; link.download = `commission-${calculationId}.csv`; document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url);
      message("فایل CSV دریافت شد.");
    } catch (error) { message(error.message, true); }
  }
  function renderCalculation(data) {
    clear(resultNode); const h = document.createElement("h3");
    h.textContent = data.status === "preview" ? `پیش‌نمایش · نسخه ${data.plan_version}` : `محاسبه ثبت شد · نسخه ${data.plan_version}`;
    resultNode.appendChild(h);
    const note = document.createElement("p"); note.className = "muted";
    note.textContent = data.status === "preview"
      ? "این پیش‌نمایش ذخیره نشده است؛ هنگام ثبت snapshot، داده‌های فروش دوباره خوانده می‌شوند."
      : "این snapshot فقط محاسبهٔ پیشنهادی است و دستور پرداخت یا حقوق صادر نمی‌کند.";
    resultNode.appendChild(note);
    const table = document.createElement("table"), head = document.createElement("thead"), body = document.createElement("tbody"), row = document.createElement("tr");
    ["فروشنده", "ارز", "فروش", "بازپرداخت", "خالص", "کمیسیون"].forEach((label) => { const th = document.createElement("th"); th.textContent = label; row.appendChild(th); });
    head.appendChild(row);
    data.rows.forEach((item) => { const tr = document.createElement("tr");
      [item.seller_membership_id || "بدون انتساب", item.currency, item.paid_amount, item.refunded_amount, item.net_amount, item.commission_amount].forEach((value) => { const td = document.createElement("td"); td.textContent = String(value); tr.appendChild(td); }); body.appendChild(tr);
    }); table.append(head, body); const wrap = document.createElement("div"); wrap.className = "table-wrap"; wrap.appendChild(table); resultNode.appendChild(wrap);
  }
  $("create-form").addEventListener("submit", async (event) => {
    event.preventDefault(); if (!organization.value) return message("واحد سازمانی را انتخاب کنید.", true);
    try {
      const data = await api("/api/v1/crm/commission-plans", "POST", { organization_unit_id: organization.value, name: $("plan-name").value, rate_percent: $("plan-rate").value, effective_start: $("plan-effective-start").value || null, effective_end: $("plan-effective-end").value || null, seller_membership_id: $("seller-id").value.trim() || null });
      event.currentTarget.reset(); await loadPlans(); selectPlan(data); message("پلن با موفقیت ساخته شد.");
    } catch (error) { message(error.message, true); }
  });
  $("update-form").addEventListener("submit", async (event) => {
    event.preventDefault(); if (!selectedPlan) return;
    try {
      const data = await api(`/api/v1/crm/commission-plans/${encodeURIComponent(selectedPlan.id)}`, "PATCH", { expected_version: selectedPlan.version, name: $("update-name").value, rate_percent: $("update-rate").value, effective_start: $("update-effective-start").value || null, effective_end: $("update-effective-end").value || null, is_active: $("update-active").value === "true" });
      selectedPlan = data; await loadPlans(); selectPlan(data); message("نسخهٔ جدید پلن ثبت شد.");
    } catch (error) { message(error.message, true); }
  });
  $("show-versions").addEventListener("click", async () => { if (!selectedPlan) return; try { const data = await api(`/api/v1/crm/commission-plans/${encodeURIComponent(selectedPlan.id)}/versions`); renderHistory(data.items || [], "versions"); } catch (error) { message(error.message, true); } });
  $("show-calculations").addEventListener("click", async () => { if (!selectedPlan) return; try { const data = await api(`/api/v1/crm/commission-plans/${encodeURIComponent(selectedPlan.id)}/calculations`); renderHistory(data.items || [], "calculations"); } catch (error) { message(error.message, true); } });
  $("preview-calculation").addEventListener("click", async () => {
    if (!selectedPlan) return; const start = $("period-start").value, end = $("period-end").value;
    if (!start || !end || start > end) return message("بازهٔ تاریخ را درست وارد کنید.", true);
    try {
      const data = await api(`/api/v1/crm/commission-plans/${encodeURIComponent(selectedPlan.id)}/calculations/preview`, "POST", { period_start: start, period_end: end });
      renderCalculation(data); message("پیش‌نمایش آماده شد؛ هنوز snapshot ذخیره نشده است.");
    } catch (error) { message(error.message, true); }
  });
  $("calculate-form").addEventListener("submit", async (event) => {
    event.preventDefault(); if (!selectedPlan) return; const start = $("period-start").value, end = $("period-end").value;
    if (!start || !end || start > end) return message("بازهٔ تاریخ را درست وارد کنید.", true);
    const storageKey = `funnel-crm:commission:${selectedPlan.id}:${start}:${end}`;
    let requestId = sessionStorage.getItem(storageKey);
    if (!requestId) { if (!crypto.randomUUID) return message("ساخت شناسهٔ امن درخواست در این مرورگر ممکن نیست.", true); requestId = crypto.randomUUID(); sessionStorage.setItem(storageKey, requestId); }
    try { const data = await api(`/api/v1/crm/commission-plans/${encodeURIComponent(selectedPlan.id)}/calculations`, "POST", { period_start: start, period_end: end, request_id: requestId }); sessionStorage.removeItem(storageKey); renderCalculation(data); message("Snapshot محاسبه ساخته شد."); }
    catch (error) { message(`${error.message} شناسهٔ درخواست برای تلاش مجدد حفظ شد.`, true); }
  });
  workspace.addEventListener("change", async () => { try { await loadOrganizations(); await loadPlans(); selectedPanel.hidden = true; calculationPanel.hidden = true; } catch (error) { message(error.message, true); } });
  organization.addEventListener("change", renderPlans);
  async function init() {
    try {
      const data = await api("/api/v1/system/workspaces", "GET", undefined, false);
      workspace.replaceChildren(); option(workspace, "", "فضای کاری را انتخاب کنید"); data.forEach((item) => option(workspace, item.id, item.name));
      const requested = data.find((item) => item.id === params.get("workspace_id"));
      workspace.value = requested?.id || (data.length === 1 ? data[0].id : "");
      if (workspace.value) { await loadOrganizations(); await loadPlans(); }
      else { organization.replaceChildren(); plansNode.textContent = "ابتدا فضای کاری را انتخاب کنید."; }
    } catch (error) { message(error.message, true); }
  }
  init();
})();"""


@router.get("/workspace/crm-commissions", response_class=HTMLResponse)
async def commission_workspace_page() -> HTMLResponse:
    """Serve a data-free shell; the API remains responsible for authorization."""
    return HTMLResponse(_PAGE, headers=_HEADERS)


@router.get("/assets/crm-commission-workspace.js")
async def commission_workspace_script() -> Response:
    return Response(
        _SCRIPT,
        media_type="application/javascript",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
