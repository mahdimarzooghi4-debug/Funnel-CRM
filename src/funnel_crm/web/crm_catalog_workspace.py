"""Persian RTL workspace for catalog items and immutable price versions."""
from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["CRM catalog workspace"], include_in_schema=False)

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
  <title>کاتالوگ محصول و خدمت | فانل CRM</title>
  <style>
    :root{font-family:Tahoma,Arial,sans-serif;color:#182638;background:#f4f7fb}*{box-sizing:border-box}body{margin:0}
    header{background:#12334a;color:#fff;padding:20px max(16px,calc((100vw - 1120px)/2))}main{max-width:1120px;margin:24px auto;padding:0 16px 48px}
    h1{font-size:clamp(23px,4vw,32px);margin:0 0 8px}h2{font-size:19px;margin:0 0 14px}p{line-height:1.8}
    .panel{background:#fff;border:1px solid #e0e7ef;border-radius:14px;padding:20px;margin:16px 0;box-shadow:0 5px 18px #142d420d}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}label{display:grid;gap:6px;color:#405367;font-size:13px}
    input,select,textarea,button{font:inherit;min-height:42px;border:1px solid #cbd6e0;border-radius:8px;padding:8px 10px;background:#fff;color:#182638}textarea{min-height:88px;resize:vertical}
    button{background:#1578a8;color:#fff;border:0;font-weight:700;cursor:pointer}button:disabled{opacity:.5;cursor:not-allowed}.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}
    #status{min-height:24px;color:#17613b}.muted{color:#687b8d;font-size:13px;line-height:1.8}.items,.prices{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px}
    .card{border:1px solid #dce5ed;border-radius:10px;padding:14px}.tag{display:inline-block;border-radius:99px;padding:4px 9px;background:#e8f3ed;color:#17613b;font-size:12px}.off{background:#f3eeee;color:#824545}
    @media(max-width:560px){.panel{padding:15px}header{line-height:2}}
  </style>
  <script src="/assets/crm-catalog-workspace.js" defer></script>
</head>
<body><header><strong>فانل CRM</strong></header><main>
  <h1>کاتالوگ محصول و خدمت</h1>
  <p class="muted">محصول‌ها و خدمات را برای هر واحد سازمانی جدا ثبت کنید. قیمت‌های قبلی حفظ می‌شوند و تغییر قیمت یک نسخهٔ تازه می‌سازد.</p>
  <p id="status" role="status" aria-live="polite"></p>
  <section class="panel"><h2>محدودهٔ کاری</h2><div class="grid">
    <label for="workspace-id">فضای کاری<select id="workspace-id" required></select></label>
    <label for="organization-id">واحد سازمانی<select id="organization-id" required></select></label>
  </div></section>
  <section class="panel"><h2>ثبت محصول یا خدمت</h2><form id="create-form"><div class="grid">
    <label for="item-code">کد<input id="item-code" maxlength="80" required></label>
    <label for="item-name">نام<input id="item-name" maxlength="200" required></label>
    <label for="item-type">نوع<select id="item-type"><option value="product">محصول</option><option value="service">خدمت</option></select></label>
  </div><label for="item-description">توضیح<input id="item-description" maxlength="2000"></label>
  <div class="actions"><button type="submit">ثبت در کاتالوگ</button></div></form></section>
  <section class="panel"><h2>فهرست کاتالوگ</h2><div id="item-list" class="items"></div></section>
  <section class="panel" id="item-detail" hidden><h2>ویرایش مورد انتخاب‌شده</h2><p id="item-summary" class="muted"></p>
    <form id="update-form"><div class="grid">
      <label for="edit-name">نام<input id="edit-name" maxlength="200" required></label>
      <label for="edit-type">نوع<select id="edit-type"><option value="product">محصول</option><option value="service">خدمت</option></select></label>
      <label for="edit-active">وضعیت<select id="edit-active"><option value="true">فعال</option><option value="false">غیرفعال</option></select></label>
    </div><label for="edit-description">توضیح<input id="edit-description" maxlength="2000"></label>
    <div class="actions"><button type="submit">ذخیرهٔ تغییرات</button></div></form>
  </section>
  <section class="panel" id="price-panel" hidden><h2>افزودن نسخهٔ قیمت</h2><p class="muted">قیمت را با ارز خودش ثبت کنید؛ تبدیل ارز انجام نمی‌شود.</p>
    <form id="price-form"><div class="grid">
      <label for="price-amount">مبلغ<input id="price-amount" type="number" min="0" step="0.000001" required></label>
      <label for="price-currency">ارز (سه‌حرفی)<input id="price-currency" maxlength="3" pattern="[A-Z]{3}" placeholder="IRR" required></label>
      <label for="price-start">شروع اعتبار<input id="price-start" type="date"></label>
      <label for="price-end">پایان اعتبار<input id="price-end" type="date"></label>
    </div><div class="actions"><button type="submit">ثبت نسخهٔ قیمت</button><button id="show-prices" type="button">تاریخچهٔ قیمت‌ها</button></div></form>
    <div id="price-history" class="prices"></div>
  </section>
</main></body></html>"""

_SCRIPT = r"""(() => {
  const $ = (id) => document.getElementById(id);
  const workspace = $("workspace-id"), organization = $("organization-id"), list = $("item-list");
  const status = $("status"), detail = $("item-detail"), pricePanel = $("price-panel"), priceHistory = $("price-history");
  const params = new URLSearchParams(location.search); let items = [], selected = null;
  function message(text, error = false) { status.textContent = text || ""; status.style.color = error ? "#8b3b22" : "#17613b"; }
  function option(node, value, label) { const el = document.createElement("option"); el.value = value; el.textContent = label; node.appendChild(el); }
  function clear(node) { node.replaceChildren(); }
  async function api(path, method = "GET", body = undefined, needsWorkspace = true) {
    const headers = { Accept: "application/json" };
    if (needsWorkspace) headers["X-Workspace-ID"] = workspace.value;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const response = await fetch(path, { method, credentials: "same-origin", headers, body: body === undefined ? undefined : JSON.stringify(body) });
    let data = {}; try { data = await response.json(); } catch (_) {}
    if (!response.ok) throw new Error(data.detail || `عملیات ناموفق بود (${response.status}).`);
    return data;
  }
  async function loadOrganizations() {
    const units = await api("/api/v1/system/catalog-organization-units");
    organization.replaceChildren(); option(organization, "", "واحد سازمانی را انتخاب کنید");
    units.forEach((unit) => option(organization, unit.id, unit.name));
    const requested = units.find((unit) => unit.id === params.get("organization_unit_id"));
    const root = units.find((unit) => unit.unit_type === "root"); organization.value = requested?.id || root?.id || "";
  }
  function renderItems() {
    clear(list); const visible = items.filter((item) => item.organization_unit_id === organization.value);
    if (!visible.length) { const p = document.createElement("p"); p.className = "muted"; p.textContent = "موردی در این واحد ثبت نشده است."; list.appendChild(p); return; }
    visible.forEach((item) => {
      const card = document.createElement("article"); card.className = "card";
      const title = document.createElement("strong"); title.textContent = `${item.name} · ${item.code}`;
      const meta = document.createElement("p"); meta.className = "muted"; meta.textContent = `${item.item_type === "product" ? "محصول" : "خدمت"} · نسخه ${item.version}`;
      const state = document.createElement("span"); state.className = `tag${item.is_active ? "" : " off"}`; state.textContent = item.is_active ? "فعال" : "غیرفعال";
      const button = document.createElement("button"); button.type = "button"; button.textContent = "مدیریت"; button.addEventListener("click", () => selectItem(item));
      card.append(title, meta, state, button); list.appendChild(card);
    });
  }
  async function loadItems() { items = (await api(`/api/v1/crm/catalog/items?organization_unit_id=${encodeURIComponent(organization.value)}&active_only=false`)).items || []; renderItems(); }
  function selectItem(item) {
    selected = item; detail.hidden = false; pricePanel.hidden = false; priceHistory.replaceChildren();
    $("item-summary").textContent = `${item.code} · نسخه ${item.version}`;
    $("edit-name").value = item.name; $("edit-type").value = item.item_type; $("edit-active").value = String(item.is_active); $("edit-description").value = item.description || "";
  }
  $("create-form").addEventListener("submit", async (event) => {
    event.preventDefault(); if (!organization.value) return message("واحد سازمانی را انتخاب کنید.", true);
    try {
      const item = await api("/api/v1/crm/catalog/items", "POST", { organization_unit_id: organization.value, code: $("item-code").value, name: $("item-name").value, item_type: $("item-type").value, description: $("item-description").value || null });
      event.currentTarget.reset(); await loadItems(); selectItem(item); message("مورد در کاتالوگ ثبت شد.");
    } catch (error) { message(error.message, true); }
  });
  $("update-form").addEventListener("submit", async (event) => {
    event.preventDefault(); if (!selected) return;
    try {
      selected = await api(`/api/v1/crm/catalog/items/${encodeURIComponent(selected.id)}`, "PATCH", { expected_version: selected.version, name: $("edit-name").value, item_type: $("edit-type").value, is_active: $("edit-active").value === "true", description: $("edit-description").value || null });
      await loadItems(); selectItem(selected); message("تغییرات ذخیره شد.");
    } catch (error) { message(error.message, true); }
  });
  $("price-form").addEventListener("submit", async (event) => {
    event.preventDefault(); if (!selected) return;
    const start = $("price-start").value, end = $("price-end").value;
    if (start && end && start > end) return message("بازهٔ اعتبار قیمت را درست وارد کنید.", true);
    try {
      await api(`/api/v1/crm/catalog/items/${encodeURIComponent(selected.id)}/prices`, "POST", { amount: $("price-amount").value, currency: $("price-currency").value, effective_start: start || null, effective_end: end || null });
      event.currentTarget.reset(); await loadPrices(); message("نسخهٔ قیمت ثبت شد.");
    } catch (error) { message(error.message, true); }
  });
  async function loadPrices() {
    if (!selected) return; const data = await api(`/api/v1/crm/catalog/items/${encodeURIComponent(selected.id)}/prices`); clear(priceHistory);
    (data.items || []).forEach((price) => {
      const card = document.createElement("article"); card.className = "card";
      const title = document.createElement("strong"); title.textContent = `نسخه ${price.version} · ${price.amount} ${price.currency}`;
      const dates = document.createElement("p"); dates.className = "muted"; dates.textContent = `اعتبار: ${price.effective_start || "بدون شروع"} تا ${price.effective_end || "بدون پایان"}`;
      const created = document.createElement("p"); created.className = "muted"; created.textContent = `ثبت‌شده: ${new Date(price.created_at).toLocaleString("fa-IR")}`;
      card.append(title, dates, created); priceHistory.appendChild(card);
    });
    if (!priceHistory.children.length) { const p = document.createElement("p"); p.className = "muted"; p.textContent = "هنوز قیمتی ثبت نشده است."; priceHistory.appendChild(p); }
  }
  $("show-prices").addEventListener("click", () => loadPrices().catch((error) => message(error.message, true)));
  workspace.addEventListener("change", async () => { try { await loadOrganizations(); await loadItems(); detail.hidden = true; pricePanel.hidden = true; } catch (error) { message(error.message, true); } });
  organization.addEventListener("change", () => { loadItems().catch((error) => message(error.message, true)); detail.hidden = true; pricePanel.hidden = true; });
  async function init() {
    try {
      const spaces = await api("/api/v1/system/workspaces", "GET", undefined, false);
      workspace.replaceChildren(); option(workspace, "", "فضای کاری را انتخاب کنید"); spaces.forEach((space) => option(workspace, space.id, space.name));
      const requested = spaces.find((space) => space.id === params.get("workspace_id")); workspace.value = requested?.id || (spaces.length === 1 ? spaces[0].id : "");
      if (workspace.value) { await loadOrganizations(); await loadItems(); }
    } catch (error) { message(error.message, true); }
  }
  init();
})();"""


@router.get("/workspace/crm-catalog", response_class=HTMLResponse)
async def crm_catalog_workspace_page() -> HTMLResponse:
    return HTMLResponse(_PAGE, headers=_HEADERS)


@router.get("/assets/crm-catalog-workspace.js")
async def crm_catalog_workspace_script() -> Response:
    return Response(
        _SCRIPT,
        media_type="application/javascript",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
