"""Customer profile workspace for the marketing manager CRM."""
from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["CRM customer workspace"], include_in_schema=False)

_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'unsafe-inline'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}

_PAGE = """<!doctype html>
<html lang="fa" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>مشتریان و پرونده‌ها | فانل CRM</title>
  <style>
    :root{font-family:Tahoma,Arial,sans-serif;color:#172c42;background:#f4f7fb;font-synthesis:none}
    *{box-sizing:border-box}body{margin:0}.app{min-height:100vh;display:grid;grid-template-columns:230px minmax(0,1fr)}
    aside{background:#fff;border-left:1px solid #e3e9f0;padding:22px 14px;position:sticky;top:0;height:100vh}
    .brand{font-size:19px;font-weight:800;padding:0 10px 25px}.brand b{color:#158b91}
    nav{display:grid;gap:5px}.nav{display:block;padding:11px;border-radius:9px;color:#54677a;text-decoration:none;font-size:12px}.nav.active,.nav:hover{background:#eaf4f7;color:#125d77;font-weight:700}
    main{min-width:0;padding:24px clamp(16px,3vw,42px) 48px}.top{display:flex;align-items:center;gap:10px;margin-bottom:22px}.top h1{font-size:24px;margin:0}.top a{color:#176687;text-decoration:none;font-size:12px}.spacer{flex:1}
    .filters{display:flex;gap:9px;flex-wrap:wrap;align-items:end;margin-bottom:16px}.filters label,.form-grid label{display:grid;gap:5px;color:#7c8a99;font-size:11px}
    input,select{height:39px;border:1px solid #dce4ec;border-radius:8px;padding:0 10px;background:#fff;color:#243c53;font:inherit;font-size:12px;min-width:150px}
    button{font:inherit;cursor:pointer}.primary{border:0;border-radius:8px;background:#126b91;color:#fff;height:39px;padding:0 15px;font-size:12px;font-weight:700}.secondary{border:1px solid #d8e1e9;border-radius:8px;background:#fff;color:#31566d;height:38px;padding:0 12px;font-size:12px}
    .status{min-height:22px;margin:0 0 12px;color:#718091;font-size:12px}.status.error{color:#a43b37}
    .layout{display:grid;grid-template-columns:minmax(320px,.85fr) minmax(0,1.4fr);gap:14px;align-items:start}
    .panel{background:#fff;border:1px solid #e3e9ef;border-radius:12px;padding:16px;min-width:0;box-shadow:0 4px 16px #22354b08}
    .panel-head{display:flex;align-items:center;gap:9px;margin-bottom:12px}.panel-head h2{font-size:15px;margin:0}.count{color:#82909e;font-size:11px}.panel-head .spacer{flex:1}
    .search{width:100%;margin-bottom:10px}.search input{width:100%}
    .profile-list{display:grid;gap:7px}.profile-row{width:100%;text-align:right;border:1px solid #edf0f4;border-radius:9px;background:#fff;padding:12px;cursor:pointer;color:#263e54}.profile-row:hover,.profile-row.selected{border-color:#79b9c6;background:#f4fafb}.profile-row strong{display:block;font-size:12px;margin-bottom:6px}.profile-meta{font-size:10px;color:#7c8a98;display:flex;gap:10px;flex-wrap:wrap}
    .empty{border:1px dashed #d7e0e8;border-radius:9px;padding:18px;color:#758493;text-align:center;font-size:12px;line-height:1.8}
    .formbox{background:#f7fafc;border:1px solid #e7edf2;border-radius:9px;padding:13px;margin-bottom:13px}.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.form-grid .wide{grid-column:1/-1}.form-actions{display:flex;gap:8px;margin-top:11px}
    .detail-head{display:flex;align-items:flex-start;gap:10px}.detail-head h2{margin:0 0 5px;font-size:18px}.badge{font-size:10px;color:#1d6979;background:#e9f5f5;border-radius:20px;padding:5px 8px}
    .tabs{display:flex;gap:6px;border-bottom:1px solid #e8edf1;margin:15px 0 12px;overflow:auto}.tab{border:0;background:none;color:#6f8090;font-size:11px;padding:9px;white-space:nowrap;border-bottom:2px solid transparent}.tab.active{color:#126b91;border-color:#126b91;font-weight:700}
    .detail-section[hidden],#create-form[hidden],#profile-detail[hidden]{display:none}.detail-section{display:grid;gap:8px}.record{background:#fbfcfd;border:1px solid #e8edf1;border-radius:9px;padding:11px;font-size:11px;color:#566b7e;line-height:1.8}.record strong{display:block;color:#27465d;font-size:12px}
    .pagination{display:flex;align-items:center;justify-content:space-between;gap:9px;margin-top:10px;color:#7e8b98;font-size:11px}.foot{font-size:10px;line-height:1.8;color:#8a96a1;margin-top:12px}
    @media(max-width:900px){.app{grid-template-columns:190px minmax(0,1fr)}.layout{grid-template-columns:1fr}.profile-list{grid-template-columns:repeat(2,minmax(0,1fr))}}
    @media(max-width:650px){.app{display:block}aside{position:relative;height:auto;border:0;border-bottom:1px solid #e3e9f0;padding:12px}.brand{padding:0 8px 8px}nav{display:flex;overflow:auto}.nav{white-space:nowrap}.top{flex-wrap:wrap}.top h1{font-size:20px}.filters{display:grid;grid-template-columns:1fr 1fr}.filters label,.filters select,.filters input{min-width:0;width:100%}.filters .wide-button{grid-column:1/-1}.profile-list{grid-template-columns:1fr}.form-grid{grid-template-columns:1fr}.form-grid .wide{grid-column:auto}main{padding:16px 12px 32px}}
  </style>
  <script src="/assets/crm-customer-workspace.js" defer></script>
</head>
<body>
<div class="app">
  <aside><div class="brand"><b>ف</b> فانل CRM</div><nav aria-label="ماژول‌های CRM">
    <a class="nav" href="/workspace/marketing-manager">اتاق تصمیم‌گیری</a>
    <a class="nav active" href="/workspace/crm-customers" aria-current="page">مشتریان و پرونده‌ها</a>
    <a class="nav" href="/workspace/crm-catalog">محصول و پیشنهاد</a>
    <a class="nav" href="/workspace/crm-activity-capture">ثبت فعالیت</a>
  </nav></aside>
  <main>
    <header class="top"><h1>مشتریان و پرونده‌ها</h1><span class="spacer"></span><a href="/workspace/marketing-manager">بازگشت به اتاق تصمیم‌گیری</a></header>
    <div class="filters">
      <label>فضای کاری<select id="workspace-id"><option value="">در حال دریافت…</option></select></label>
      <label>واحد سازمانی<select id="organization-unit"><option value="">همهٔ واحدهای مجاز</option></select></label>
      <button id="new-profile" class="primary" type="button">مشتری جدید</button>
      <button id="refresh" class="secondary wide-button" type="button">به‌روزرسانی فهرست</button>
    </div>
    <p id="status" class="status" role="status" aria-live="polite">در حال آماده‌سازی…</p>
    <div class="layout">
      <section class="panel" aria-labelledby="profiles-title">
        <div class="panel-head"><h2 id="profiles-title">فهرست مشتریان</h2><span id="total" class="count">—</span><span class="spacer"></span></div>
        <label class="search"><input id="search" type="search" placeholder="جست‌وجو در مشتریان دریافت‌شده" aria-label="جست‌وجوی مشتری"></label>
        <form id="create-form" class="formbox" hidden>
          <div class="panel-head"><h2>ثبت مشتری</h2></div>
          <div class="form-grid">
            <label>نوع پرونده<select id="profile-kind"><option value="person">شخص</option><option value="organization">سازمان</option></select></label>
            <label>مرحلهٔ چرخهٔ عمر<input id="create-stage" value="lead" maxlength="80" required></label>
            <label class="wide">نام نمایشی<input id="create-name" maxlength="240" required></label>
          </div>
          <div class="form-actions"><button class="primary" type="submit">ثبت پرونده</button><button id="cancel-create" class="secondary" type="button">انصراف</button></div>
        </form>
        <div id="profile-list" class="profile-list"><div class="empty">برای دیدن پرونده‌ها، فضای کاری را انتخاب کنید.</div></div>
        <div class="pagination"><span id="page-meta">—</span><button id="load-more" class="secondary" type="button" hidden>بارگذاری بیشتر</button></div>
        <p class="foot">نمایش بر اساس دسترسی حساب انجام می‌شود. جست‌وجو در رکوردهای دریافت‌شدهٔ فعلی است.</p>
      </section>
      <section id="profile-detail" class="panel" hidden aria-live="polite">
        <div class="detail-head"><div><h2 id="detail-name"></h2><div id="detail-meta" class="profile-meta"></div></div><span class="spacer"></span><span id="detail-kind" class="badge"></span></div>
        <p><a id="customer-support-link" class="secondary" href="/workspace/crm-support">درخواست‌های پشتیبانی این مشتری</a></p><form id="edit-form" class="formbox" style="margin-top:13px">
          <div class="form-grid">
            <label>نام نمایشی<input id="edit-name" maxlength="240" required></label>
            <label>مرحلهٔ چرخهٔ عمر<input id="edit-stage" maxlength="80" required></label>
          </div>
          <div class="form-actions"><button class="primary" type="submit">ذخیرهٔ تغییر</button></div>
        </form>
        <div class="tabs" role="tablist" aria-label="بخش‌های پرونده">
          <button class="tab active" data-tab="contacts" type="button">راه‌های ارتباطی</button>
          <button class="tab" data-tab="activities" type="button">تاریخچهٔ تعامل</button>
          <button class="tab" data-tab="custom" type="button">اطلاعات سفارشی</button><button class="tab" data-tab="consents" type="button">رضایت ارتباطی</button>
        </div>
        <section id="section-contacts" class="detail-section"></section>
        <section id="section-activities" class="detail-section" hidden></section>
        <section id="section-custom" class="detail-section" hidden></section><section id="section-consents" class="detail-section" hidden></section>
      </section>
      <section id="detail-empty" class="panel empty">یک مشتری را از فهرست انتخاب کنید تا پرونده و تاریخچهٔ آن را ببینید.</section>
    </div>
  </main>
</div>
</body>
</html>"""

_SCRIPT = r"""(() => {
  const $ = (id) => document.getElementById(id);
  const workspace = $("workspace-id"), unitSelect = $("organization-unit");
  const status = $("status"), listHost = $("profile-list");
  let units = [], profiles = [], offset = 0, total = 0, selectedProfile = null, customGeneration = 0;
  const LIMIT = 50, number = new Intl.NumberFormat("fa-IR");
  const esc = (value) => String(value ?? "");
  function say(message, error = false) { status.textContent = message; status.classList.toggle("error", error); }
  function append(parent, tag, value, className = "") {
    const node = document.createElement(tag); if (className) node.className = className;
    node.textContent = esc(value); parent.appendChild(node); return node;
  }
  async function api(path, options = {}, noWorkspace = false) {
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    if (options.body) headers["Content-Type"] = "application/json";
    if (!noWorkspace) headers["X-Workspace-ID"] = workspace.value;
    const response = await fetch(path, { credentials: "same-origin", ...options, headers });
    let result = {};
    try { result = response.status === 204 ? {} : await response.json(); } catch (_) {}
    if (!response.ok) {
      const detail = typeof result.detail === "string" ? result.detail : (result.detail?.message || result.message);
      throw new Error(detail || "درخواست ناموفق بود (" + response.status + ").");
    }
    return result;
  }
  function selectedUnitQuery() {
    return unitSelect.value ? "&organization_unit_id=" + encodeURIComponent(unitSelect.value) : "";
  }
  async function loadUnits() {
    const rows = await api("/api/v1/system/organization-units");
    units = rows;
    unitSelect.replaceChildren();
    const all = document.createElement("option"); all.value = ""; all.textContent = "همهٔ واحدهای مجاز"; unitSelect.appendChild(all);
    rows.forEach((unit) => { const option = document.createElement("option"); option.value = unit.id; option.textContent = unit.name; unitSelect.appendChild(option); });
  }
  function drawList() {
    const term = $("search").value.trim().toLocaleLowerCase();
    const visible = profiles.filter((profile) => !term || profile.display_name.toLocaleLowerCase().includes(term));
    listHost.replaceChildren();
    if (!visible.length) { append(listHost, "div", "مشتری منطبق با جست‌وجو در داده‌های دریافت‌شده پیدا نشد.", "empty"); }
    visible.forEach((profile) => {
      const button = document.createElement("button"); button.type = "button";
      button.className = "profile-row" + (selectedProfile?.id === profile.id ? " selected" : "");
      append(button, "strong", profile.display_name);
      const meta = document.createElement("span"); meta.className = "profile-meta";
      append(meta, "span", profile.profile_kind === "organization" ? "سازمان" : "شخص");
      append(meta, "span", profile.lifecycle_stage);
      const org = units.find((unit) => unit.id === profile.organization_unit_id);
      if (org) append(meta, "span", org.name);
      button.appendChild(meta); button.addEventListener("click", () => openProfile(profile)); listHost.appendChild(button);
    });
    $("total").textContent = number.format(total) + " پرونده";
    $("page-meta").textContent = number.format(profiles.length) + " از " + number.format(total) + " مورد دریافت شده";
    $("load-more").hidden = profiles.length >= total;
  }
  async function loadProfiles(reset = true) {
    if (!workspace.value) return;
    if (reset) { offset = 0; profiles = []; selectedProfile = null; ++customGeneration; $("profile-detail").hidden=true; $("detail-empty").hidden=false; }
    say("در حال دریافت فهرست مشتریان…");
    try {
      const query = "?limit=" + LIMIT + "&offset=" + offset + selectedUnitQuery();
      const page = await api("/api/v1/crm/profiles" + query);
      profiles = reset ? page.items : profiles.concat(page.items);
      total = page.total; offset += page.items.length; drawList();
      say("فهرست مشتریان به‌روز شد.");
    } catch (error) { say(error.message, true); }
  }
  function activateTab(name) {
    document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
    ["contacts", "activities", "consents", "custom"].forEach((key) => { $("section-" + key).hidden = key !== name; });
  }
  function recordCard(host, title, pairs) {
    const card = document.createElement("article"); card.className = "record"; append(card, "strong", title);
    pairs.forEach(([key, value]) => append(card, "div", key + ": " + (value ?? "ثبت نشده")));
    host.appendChild(card);
  }
  function customScope(profile) { return workspace.value+":"+unitSelect.value+":"+profile.id; }
  function parseCustomValue(field, input) {
    const value=input.value;
    if(value==="")throw Error("مقدار فیلد را وارد کنید؛ پاک‌کردن مقدار در این API پشتیبانی نمی‌شود.");
    if(field.value_type==="boolean")return value==="true";
    if(field.value_type==="number"){const n=Number(value);if(!Number.isFinite(n)||!value.trim())throw Error("عدد معتبر وارد کنید.");return n}
    return value;
  }
  async function saveCustomValue(field,input,button,message,profile,scope) {
    if(button.disabled||!selectedProfile||selectedProfile.id!==profile.id||scope!==customScope(profile))return;
    let value;try{value=parseCustomValue(field,input)}catch(error){message.textContent=error.message;return}
    button.disabled=true;message.textContent="در حال ذخیره…";
    try{const result=await api("/api/v1/crm/profiles/"+encodeURIComponent(profile.id)+"/custom-fields/"+encodeURIComponent(field.field_key),{method:"PUT",body:JSON.stringify({value})});if(!selectedProfile||selectedProfile.id!==profile.id||scope!==customScope(profile))return;input.value=String(result.value);message.textContent="مقدار ذخیره شد."}catch(error){if(selectedProfile&&selectedProfile.id===profile.id&&scope===customScope(profile))message.textContent="ذخیره انجام نشد: "+error.message}finally{button.disabled=false}
  }
  function renderCustomFields(host,fields,profile,scope) {
    if(!fields.length){append(host,"div","فیلد سفارشی فعالی برای این نوع پرونده تعریف نشده است.","empty");return}
    for(const field of fields){const form=document.createElement("form");form.className="formbox";const label=document.createElement("label");label.textContent=field.display_name+(field.is_required?" (اجباری)":"");const input=document.createElement(["boolean","choice"].includes(field.value_type)?"select":"input");
      if(["boolean","choice"].includes(field.value_type)){const empty=document.createElement("option");empty.value="";empty.textContent="انتخاب کنید";input.appendChild(empty);const options=field.value_type==="boolean"?[["true","بله"],["false","خیر"]]:field.options.map(x=>[x,x]);for(const [value,text] of options){const option=document.createElement("option");option.value=value;option.textContent=text;input.appendChild(option)}}else{input.type=field.value_type==="number"?"number":field.value_type==="date"?"date":"text";if(field.value_type==="number")input.step="any";if(field.value_type==="text")input.maxLength=4000}
      input.value=field.value==null?"":String(field.value);input.required=true;label.appendChild(input);form.appendChild(label);const button=document.createElement("button");button.type="submit";button.className="primary";button.textContent="ذخیرهٔ مقدار";const message=document.createElement("p");message.setAttribute("role","status");message.setAttribute("aria-live","polite");form.appendChild(button);form.appendChild(message);form.addEventListener("submit",event=>{event.preventDefault();saveCustomValue(field,input,button,message,profile,scope)});host.appendChild(form)}
  }
  async function loadDetailSection(name, profile) {
    const host = $("section-" + name); host.replaceChildren();
    try {
      if (name === "custom") {
        const version=++customGeneration,scope=customScope(profile);
        try{const result=await api("/api/v1/crm/profiles/"+encodeURIComponent(profile.id)+"/custom-fields");if(version!==customGeneration||!selectedProfile||selectedProfile.id!==profile.id||scope!==customScope(profile))return;renderCustomFields(host,result.items,profile,scope)}catch(error){if(version===customGeneration&&selectedProfile&&selectedProfile.id===profile.id&&scope===customScope(profile))append(host,"div",error.message,"empty")}
      } else if (name === "contacts") {
        const result = await api("/api/v1/crm/profiles/" + encodeURIComponent(profile.id) + "/contact-points");
        const items = result.items || [];
        if (items.length) items.forEach((item) => recordCard(host, item.channel, [["مقدار", item.value], ["وضعیت راستی‌آزمایی", item.verification_status], ["اصلی", item.is_primary ? "بله" : "خیر"]]));
        else append(host, "div", "راه ارتباطی ثبت‌شده‌ای وجود ندارد.", "empty");
        const form = document.createElement("form"); form.className = "formbox";
        const grid = document.createElement("div"); grid.className = "form-grid";
        const channelLabel = document.createElement("label"); channelLabel.textContent = "نوع راه ارتباطی";
        const channel = document.createElement("select");
        [["phone","تلفن"],["email","ایمیل"],["postal_address","نشانی"],["social_handle","شناسهٔ شبکهٔ اجتماعی"],["website","وب‌سایت"]].forEach(([value,label]) => { const o=document.createElement("option");o.value=value;o.textContent=label;channel.appendChild(o);});
        channelLabel.appendChild(channel); grid.appendChild(channelLabel);
        const valueLabel = document.createElement("label"); valueLabel.textContent = "مقدار";
        const value = document.createElement("input"); value.required = true; value.maxLength = 1000; valueLabel.appendChild(value); grid.appendChild(valueLabel);
        const primaryLabel = document.createElement("label"); primaryLabel.style.display = "flex"; primaryLabel.style.alignItems = "center"; primaryLabel.style.gap = "8px"; primaryLabel.textContent = "راه ارتباطی اصلی";
        const primary = document.createElement("input"); primary.type = "checkbox"; primaryLabel.appendChild(primary); grid.appendChild(primaryLabel);
        form.appendChild(grid); const submit=document.createElement("button");submit.type="submit";submit.className="primary";submit.textContent="ثبت راه ارتباطی";form.appendChild(submit);
        form.addEventListener("submit", async (event) => { event.preventDefault(); submit.disabled=true; try { await api("/api/v1/crm/profiles/"+encodeURIComponent(profile.id)+"/contact-points",{method:"POST",body:JSON.stringify({channel:channel.value,value:value.value,is_primary:primary.checked})}); await loadDetailSection("contacts",profile); say("راه ارتباطی با موفقیت ثبت شد."); } catch(error){say(error.message,true);} finally{submit.disabled=false;} });
        host.appendChild(form);
      } else {
        const suffix = name === "activities" ? "/activities?limit=50" : "/communication-consents?limit=100";
        const result = await api("/api/v1/crm/profiles/" + encodeURIComponent(profile.id) + suffix);
        const items = result.items || [];
        if (!items.length) { append(host, "div", name === "activities" ? "تعامل ثبت‌شده‌ای وجود ندارد." : "رویداد رضایت ارتباطی ثبت نشده است.", "empty"); return; }
        items.forEach((item) => {
          const title = name === "activities" ? (item.activity_type || "تعامل") : (item.purpose_key || "رضایت ارتباطی");
          const fields = name === "activities"
            ? [["کانال", item.channel], ["محصول مبدأ", item.source_product], ["زمان رخداد", item.occurred_at]]
            : [["کانال", item.channel], ["تصمیم", item.decision], ["نسخهٔ سیاست", item.policy_version], ["زمان ثبت تصمیم", item.decision_at]];
          recordCard(host, title, fields);
        });
      }
    } catch (error) { append(host, "div", error.message, "empty"); }
  }
  async function openProfile(profile) {
    selectedProfile = profile; drawList(); $("detail-empty").hidden = true; $("profile-detail").hidden = false;
    $("customer-support-link").href = "/workspace/crm-support?" + new URLSearchParams({workspace_id: workspace.value, organization_unit_id: profile.organization_unit_id, profile_id: profile.id});
    $("detail-name").textContent = profile.display_name;
    $("detail-kind").textContent = profile.profile_kind === "organization" ? "سازمان" : "شخص";
    const unit = units.find((item) => item.id === profile.organization_unit_id);
    $("detail-meta").textContent = "مرحله: " + profile.lifecycle_stage + " · " + (unit?.name || "واحد سازمانی");
    $("edit-name").value = profile.display_name; $("edit-stage").value = profile.lifecycle_stage;
    activateTab("contacts"); await loadDetailSection("contacts", profile);
  }
  $("edit-form").addEventListener("submit", async (event) => {
    event.preventDefault(); if (!selectedProfile) return;
    const button = $("edit-form").querySelector("button[type=submit]"); button.disabled = true;
    try {
      await api("/api/v1/crm/profiles/" + encodeURIComponent(selectedProfile.id), {method:"PATCH",body:JSON.stringify({display_name:$("edit-name").value,lifecycle_stage:$("edit-stage").value})});
      selectedProfile.display_name=$("edit-name").value; selectedProfile.lifecycle_stage=$("edit-stage").value;
      $("detail-name").textContent=selectedProfile.display_name; $("detail-meta").textContent="مرحله: "+selectedProfile.lifecycle_stage+" · "+(units.find((item)=>item.id===selectedProfile.organization_unit_id)?.name||"واحد سازمانی");
      drawList(); say("پروندهٔ مشتری به‌روز شد.");
    } catch(error){say(error.message,true);} finally{button.disabled=false;}
  });
  $("create-form").addEventListener("submit", async (event) => {
    event.preventDefault(); if (!unitSelect.value) { say("برای ثبت مشتری، یک واحد سازمانی انتخاب کنید.",true); return; }
    const button = $("create-form").querySelector("button[type=submit]"); button.disabled=true;
    try {
      const profile = await api("/api/v1/crm/profiles",{method:"POST",body:JSON.stringify({organization_unit_id:unitSelect.value,profile_kind:$("profile-kind").value,display_name:$("create-name").value,lifecycle_stage:$("create-stage").value,custom_fields:{}})});
      $("create-form").reset(); $("create-stage").value="lead"; $("create-form").hidden=true;
      await loadProfiles(true); const created=profiles.find((row)=>row.id===profile.id); if(created) await openProfile(created);
      say("پروندهٔ مشتری ثبت شد.");
    } catch(error){say(error.message,true);} finally{button.disabled=false;}
  });
  $("new-profile").addEventListener("click",()=>{$("create-form").hidden=!$("create-form").hidden; $("profile-detail").hidden=true; $("detail-empty").hidden=false;});
  $("cancel-create").addEventListener("click",()=>{$("create-form").hidden=true;});
  $("refresh").addEventListener("click",()=>loadProfiles(true));
  $("search").addEventListener("input",drawList);
  $("load-more").addEventListener("click",()=>loadProfiles(false));
  unitSelect.addEventListener("change",()=>loadProfiles(true));
  document.querySelectorAll(".tab").forEach((tab)=>tab.addEventListener("click",async()=>{activateTab(tab.dataset.tab);if(selectedProfile)await loadDetailSection(tab.dataset.tab,selectedProfile);}));
  workspace.addEventListener("change",async()=>{
    if(!workspace.value)return;
    try{await loadUnits();await loadProfiles(true);}catch(error){say(error.message,true);}
  });
  async function init(){
    try{
      const spaces=await api("/api/v1/system/workspaces",{},true);
      workspace.replaceChildren();const placeholder=document.createElement("option");placeholder.value="";placeholder.textContent="فضای کاری را انتخاب کنید";workspace.appendChild(placeholder);
      spaces.forEach((space)=>{const option=document.createElement("option");option.value=space.id;option.textContent=space.name;workspace.appendChild(option);});
      const params=new URLSearchParams(location.search), requested=spaces.find((space)=>space.id===params.get("workspace_id"));
      workspace.value=requested?requested.id:(spaces.length===1?spaces[0].id:"");
      if(workspace.value){await loadUnits();await loadProfiles(true);}else say("فضای کاری را انتخاب کنید تا پرونده‌های مجاز نمایش داده شوند.");
    }catch(error){say(error.message,true);}
  }
  init();
})();"""

@router.get("/workspace/crm-customers", response_class=HTMLResponse)
async def crm_customer_workspace_page() -> HTMLResponse:
    return HTMLResponse(_PAGE, headers=_HEADERS)


@router.get("/assets/crm-customer-workspace.js")
async def crm_customer_workspace_script() -> Response:
    return Response(
        _SCRIPT,
        media_type="application/javascript",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
