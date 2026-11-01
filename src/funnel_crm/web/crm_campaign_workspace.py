"""Campaign planning, content approval, and marketing calendar workspace."""
from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["CRM campaign workspace"], include_in_schema=False)

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
<title>کمپین و محتوا | فانل CRM</title>
<style>
:root{font-family:Tahoma,Arial,sans-serif;color:#172c42;background:#f4f7fb;font-synthesis:none}*{box-sizing:border-box}body{margin:0}.app{min-height:100vh;display:grid;grid-template-columns:230px minmax(0,1fr)}aside{background:#fff;border-left:1px solid #e3e9f0;padding:20px 14px;position:sticky;top:0;height:100vh}.brand{font-size:19px;font-weight:800;padding:0 10px 24px}.brand b{color:#158b91}nav{display:grid;gap:5px}.nav{display:block;padding:11px;border-radius:9px;color:#54677a;text-decoration:none;font-size:12px}.nav.active,.nav:hover{background:#eaf4f7;color:#125d77;font-weight:700}main{min-width:0;padding:24px clamp(16px,3vw,42px) 48px}.top{display:flex;align-items:center;gap:12px;margin-bottom:20px}.top h1{font-size:24px;margin:0}.spacer{flex:1}.top a{color:#176687;text-decoration:none;font-size:12px}.filters{display:flex;align-items:end;gap:9px;flex-wrap:wrap;margin-bottom:14px}.filters label,.form-grid label{display:grid;gap:5px;color:#7c8a99;font-size:11px}input,select,textarea{border:1px solid #dce4ec;border-radius:8px;padding:9px 10px;background:#fff;color:#243c53;font:inherit;font-size:12px;min-width:145px}input,select{height:39px}textarea{width:100%;min-height:90px;resize:vertical}.primary,.secondary,.danger{font:inherit;cursor:pointer;border-radius:8px;height:39px;padding:0 13px;font-size:12px;font-weight:700}.primary{border:0;background:#126b91;color:#fff}.secondary{border:1px solid #d8e1e9;background:#fff;color:#31566d}.danger{border:1px solid #ebd7d5;background:#fff8f7;color:#9c4039}.status{min-height:22px;color:#718091;font-size:12px;margin:0 0 12px}.status.error{color:#a43b37}.panel{background:#fff;border:1px solid #e3e9ef;border-radius:12px;padding:16px;box-shadow:0 4px 16px #22354b08}.tabs{display:flex;gap:7px;border-bottom:1px solid #e7edf2;margin:12px 0 14px;overflow:auto}.tab{border:0;background:none;color:#6f8090;padding:10px;font:inherit;font-size:12px;white-space:nowrap;border-bottom:2px solid transparent;cursor:pointer}.tab.active{color:#126b91;border-color:#126b91;font-weight:700}.view[hidden],#campaign-form[hidden],#asset-form[hidden]{display:none}.view{display:grid;gap:12px}.head{display:flex;align-items:center;gap:10px;margin-bottom:10px}.head h2{font-size:15px;margin:0}.muted{font-size:11px;color:#81909e}.list{display:grid;gap:9px}.item{border:1px solid #e7edf2;background:#fbfcfd;border-radius:10px;padding:13px}.item-head{display:flex;align-items:flex-start;gap:10px}.item-head strong{font-size:13px;color:#25445d}.item-meta{display:flex;gap:7px;flex-wrap:wrap;margin-top:7px;color:#778797;font-size:10px}.badge{border-radius:20px;background:#edf4f6;color:#276579;padding:4px 8px;font-size:10px}.actions{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}.formbox{background:#f8fafc;border:1px solid #e7edf2;border-radius:10px;padding:14px}.form-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.wide{grid-column:1/-1}.form-actions{display:flex;gap:8px;margin-top:11px}.empty{border:1px dashed #d7e0e8;border-radius:9px;padding:18px;color:#758493;text-align:center;font-size:12px;line-height:1.8}.conflict{border-right:3px solid #d7972b;background:#fff9ed;padding:10px;border-radius:8px;color:#745821;font-size:11px;line-height:1.8}.basis{font-size:10px;line-height:1.8;color:#8b96a2}.pagination{font-size:11px;color:#7e8b98;display:flex;justify-content:space-between;align-items:center;margin-top:8px}
@media(max-width:900px){.app{grid-template-columns:190px minmax(0,1fr)}.form-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:650px){.app{display:block}aside{position:relative;height:auto;border:0;border-bottom:1px solid #e3e9f0;padding:12px}.brand{padding:0 8px 8px}nav{display:flex;overflow:auto}.nav{white-space:nowrap}main{padding:16px 12px 32px}.top{flex-wrap:wrap}.top h1{font-size:20px}.filters{display:grid;grid-template-columns:1fr 1fr}.filters label,.filters input,.filters select{min-width:0;width:100%}.filters .primary{grid-column:1/-1}.form-grid{grid-template-columns:1fr}.wide{grid-column:auto}.item-head{display:block}}
</style>
<script src="/assets/crm-campaign-workspace.js" defer></script>
</head>
<body><div class="app">
<aside><div class="brand"><b>ف</b> فانل CRM</div><nav aria-label="ماژول‌های CRM">
<a class="nav" href="/workspace/marketing-manager">اتاق تصمیم‌گیری</a>
<a class="nav" href="/workspace/crm-customers">مشتریان و پرونده‌ها</a>
<a class="nav active" href="/workspace/crm-campaigns" aria-current="page">کمپین و محتوا</a>
<a class="nav" href="/workspace/budget-scenario-comparison">بودجه و سناریو</a>
</nav></aside>
<main>
<header class="top"><h1>مدیریت کمپین و محتوا</h1><span class="spacer"></span><a href="/workspace/marketing-manager">بازگشت به اتاق تصمیم‌گیری</a></header>
<div class="filters">
<label>فضای کاری<select id="workspace-id"><option value="">در حال دریافت…</option></select></label>
<label>واحد سازمانی<select id="organization-unit"><option value="">واحد مجاز را انتخاب کنید</option></select></label>
<button id="refresh" class="primary" type="button">به‌روزرسانی</button>
</div>
<p id="status" class="status" role="status" aria-live="polite">در حال آماده‌سازی…</p>
<section class="panel">
<div class="tabs" role="tablist" aria-label="بخش‌های بازاریابی">
<button class="tab active" data-view="campaigns" type="button">کمپین‌ها</button>
<button class="tab" data-view="assets" type="button">محتوا و دارایی‌ها</button>
<button class="tab" data-view="calendar" type="button">تقویم اجرا</button>
</div>
<section id="view-campaigns" class="view">
<div class="head"><h2>کمپین‌های این واحد</h2><span class="spacer"></span><button id="new-campaign" class="primary" type="button">کمپین جدید</button></div>
<form id="campaign-form" class="formbox" hidden>
<div class="head"><h2 id="campaign-form-title">تعریف کمپین</h2></div>
<div class="form-grid">
<label class="wide">نام کمپین<input id="campaign-name" maxlength="160" required></label>
<label>گروه مخاطب<select id="campaign-segment" required><option value="">انتخاب گروه فعال</option></select></label>
<label>هدف کمپین<input id="campaign-objective" value="lead_generation" pattern="[a-z][a-z0-9_.-]{0,79}" required></label>
<label>کانال<select id="campaign-channel"><option value="email">ایمیل</option><option value="phone">تلفن</option><option value="messaging">پیام‌رسان</option><option value="social">شبکهٔ اجتماعی</option><option value="web">وب</option><option value="store">فروشگاه</option><option value="field">میدانی</option><option value="other">سایر</option></select></label>
<label>شروع<input id="campaign-start" type="datetime-local"></label>
<label>پایان<input id="campaign-end" type="datetime-local"></label>
<label>بودجه<input id="campaign-budget" type="number" min="0" step="0.01"></label>
<label>واحد پول<select id="campaign-currency"><option value="">بدون بودجهٔ ثبت‌شده</option><option value="IRR">IRR</option><option value="USD">USD</option><option value="EUR">EUR</option></select></label>
</div>
<div class="form-actions"><button id="save-campaign" class="primary" type="submit">ثبت کمپین</button><button id="cancel-campaign" class="secondary" type="button">انصراف</button></div>
</form>
<div id="campaign-list" class="list"><div class="empty">برای نمایش کمپین‌ها، فضای کاری و واحد سازمانی را انتخاب کنید.</div></div>
<div class="pagination"><span id="campaign-count">—</span><button id="campaign-more" class="secondary" type="button" hidden>بارگذاری بیشتر</button></div>
</section>
<section id="view-assets" class="view" hidden>
<div class="head"><h2>دارایی‌های محتوایی</h2><span class="spacer"></span><button id="new-asset" class="primary" type="button">محتوای جدید</button></div>
<form id="asset-form" class="formbox" hidden>
<div class="form-grid">
<label>کمپین مرتبط<select id="asset-campaign"><option value="">بدون اتصال به کمپین</option></select></label>
<label>کانال<select id="asset-channel"><option value="email">ایمیل</option><option value="phone">تلفن</option><option value="messaging">پیام‌رسان</option><option value="social">شبکهٔ اجتماعی</option><option value="web">وب</option><option value="store">فروشگاه</option><option value="field">میدانی</option><option value="other">سایر</option></select></label>
<label>نوع محتوا<select id="asset-kind"><option value="copy">متن</option><option value="image">تصویر</option><option value="video">ویدئو</option><option value="landing_page">صفحهٔ فرود</option><option value="document">سند</option><option value="other">سایر</option></select></label>
<label class="wide">عنوان<input id="asset-title" maxlength="160" required></label>
<label class="wide">متن یا توضیح<textarea id="asset-body" maxlength="12000"></textarea></label>
<label class="wide">پیوند منبع (اختیاری)<input id="asset-url" type="url" maxlength="2000" placeholder="https://"></label>
<label>زبان<input id="asset-locale" value="fa-IR" pattern="[a-z]{2}(-[A-Z]{2})?"></label>
</div><div class="form-actions"><button class="primary" type="submit">ثبت پیش‌نویس محتوا</button><button id="cancel-asset" class="secondary" type="button">انصراف</button></div>
</form>
<div id="asset-list" class="list"><div class="empty">برای نمایش محتوا، واحد سازمانی را انتخاب کنید.</div></div>
<p class="basis">محتوا پس از ثبت پیش‌نویس منتشر نمی‌شود. ارسال برای بازبینی و تأیید مدیر، مرحله‌های جداگانه‌اند.</p>
</section>
<section id="view-calendar" class="view" hidden>
<div class="head"><h2>رویدادهای بازاریابی</h2><span id="calendar-range" class="muted"></span><span class="spacer"></span><button id="calendar-refresh" class="secondary" type="button">به‌روزرسانی تقویم</button></div>
<div id="calendar-conflicts" class="list"></div><div id="calendar-events" class="list"><div class="empty">تقویم اجرا پس از انتخاب واحد سازمانی بارگذاری می‌شود.</div></div>
<p id="calendar-basis" class="basis"></p>
</section>
</section>
</main></div></body></html>"""

_SCRIPT = r"""(() => {
  const $ = (id) => document.getElementById(id);
  const workspace = $("workspace-id"), unit = $("organization-unit"), status = $("status");
  const LIMIT = 50, number = new Intl.NumberFormat("fa-IR");
  let campaigns = [], segments = [], assets = [], campaignOffset = 0, campaignTotal = 0, editingId = null, currentView = "campaigns";
  const channels = {email:"ایمیل",phone:"تلفن",messaging:"پیام‌رسان",social:"شبکهٔ اجتماعی",web:"وب",store:"فروشگاه",field:"میدانی",other:"سایر"};
  const campaignStates = {draft:"پیش‌نویس",scheduled:"زمان‌بندی‌شده",active:"فعال",paused:"متوقف",completed:"تکمیل‌شده",archived:"بایگانی"};
  const assetStates = {draft:"پیش‌نویس",in_review:"در بازبینی",approved:"تأییدشده",rejected:"نیازمند اصلاح",retired:"بازنشسته"};
  function say(message,error=false){status.textContent=message;status.classList.toggle("error",error);}
  function el(tag,text,className=""){const n=document.createElement(tag);if(className)n.className=className;n.textContent=String(text??"");return n;}
  async function api(path,options={}) {
    const headers={Accept:"application/json",...(options.headers||{})};if(options.body)headers["Content-Type"]="application/json";
    if(workspace.value)headers["X-Workspace-ID"]=workspace.value;
    const response=await fetch(path,{credentials:"same-origin",...options,headers});let data={};
    try{data=response.status===204?{}:await response.json();}catch(_){}
    if(!response.ok){const d=typeof data.detail==="string"?data.detail:(data.detail?.message||data.message);throw new Error(d||"درخواست ناموفق بود ("+response.status+").");}
    return data;
  }
  function unitQuery(){return unit.value?"&organization_unit_id="+encodeURIComponent(unit.value):"";}
  function localIso(id){const value=$(id).value;return value?new Date(value).toISOString():null;}
  function dateLabel(value){return value?new Date(value).toLocaleString("fa-IR"):"تعیین نشده";}
  async function loadSegments(){
    const q=unitQuery();const page=await api("/api/v1/crm/segments?limit=100"+q);segments=(page.items||[]).filter(item=>item.is_active);
    const select=$("campaign-segment");select.replaceChildren();const placeholder=el("option","گروه مخاطب را انتخاب کنید");placeholder.value="";select.appendChild(placeholder);
    segments.forEach(item=>{const o=el("option",item.name);o.value=item.id;select.appendChild(o);});
  }
  function syncAssetCampaigns(){
    const select=$("asset-campaign");select.replaceChildren();const none=el("option","بدون اتصال به کمپین");none.value="";select.appendChild(none);
    campaigns.filter(c=>c.status!=="archived").forEach(c=>{const o=el("option",c.name+" · "+campaignStates[c.status]);o.value=c.id;select.appendChild(o);});
  }
  function renderCampaigns(){
    const host=$("campaign-list");host.replaceChildren();
    if(!campaigns.length){host.appendChild(el("div","کمپینی برای این واحد سازمانی ثبت نشده است.","empty"));}
    campaigns.forEach(c=>{
      const card=document.createElement("article");card.className="item";const head=document.createElement("div");head.className="item-head";
      const info=document.createElement("div");info.appendChild(el("strong",c.name));const meta=document.createElement("div");meta.className="item-meta";
      const seg=segments.find(x=>x.id===c.segment_id);[campaignStates[c.status]||c.status,channels[c.channel]||c.channel,seg?.name||"گروه مخاطب",c.objective_key,dateLabel(c.starts_at)+" تا "+dateLabel(c.ends_at),c.planned_budget_amount===null?"بودجه ثبت نشده":number.format(Number(c.planned_budget_amount))+" "+c.planned_budget_currency].forEach(v=>meta.appendChild(el("span",v)));
      info.appendChild(meta);head.appendChild(info);head.appendChild(el("span",campaignStates[c.status]||c.status,"badge"));card.appendChild(head);
      if(c.status==="draft"){const actions=document.createElement("div");actions.className="actions";const edit=el("button","ویرایش","secondary");edit.type="button";edit.addEventListener("click",()=>editCampaign(c));actions.appendChild(edit);card.appendChild(actions);}
      host.appendChild(card);
    });
    $("campaign-count").textContent=number.format(campaigns.length)+" از "+number.format(campaignTotal)+" کمپین دریافت شد";
    $("campaign-more").hidden=campaigns.length>=campaignTotal;syncAssetCampaigns();
  }
  async function loadCampaigns(reset=true){
    if(!workspace.value||!unit.value)return;
    if(reset){campaigns=[];campaignOffset=0;}say("در حال دریافت کمپین‌ها…");
    try{const page=await api("/api/v1/crm/campaigns?limit="+LIMIT+"&offset="+campaignOffset+unitQuery());campaigns=reset?page.items:campaigns.concat(page.items);campaignTotal=page.total;campaignOffset+=page.items.length;renderCampaigns();say("فهرست کمپین‌ها به‌روز شد.");}
    catch(error){say(error.message,true);}
  }
  function clearCampaignForm(){editingId=null;$("campaign-form").reset();$("campaign-objective").value="lead_generation";$("campaign-form-title").textContent="تعریف کمپین";$("save-campaign").textContent="ثبت کمپین";}
  function editCampaign(c){
    editingId=c.id;$("campaign-form").hidden=false;$("campaign-form-title").textContent="ویرایش کمپین پیش‌نویس";$("save-campaign").textContent="ذخیرهٔ تغییر";
    $("campaign-name").value=c.name;$("campaign-segment").value=c.segment_id;$("campaign-objective").value=c.objective_key;$("campaign-channel").value=c.channel;
    $("campaign-start").value=c.starts_at?new Date(c.starts_at).toISOString().slice(0,16):"";
    $("campaign-end").value=c.ends_at?new Date(c.ends_at).toISOString().slice(0,16):"";
    $("campaign-budget").value=c.planned_budget_amount??"";$("campaign-currency").value=c.planned_budget_currency??"";
    $("campaign-form").scrollIntoView({behavior:"smooth",block:"start"});
  }
  $("campaign-form").addEventListener("submit",async event=>{
    event.preventDefault();if(!unit.value){say("ابتدا واحد سازمانی را انتخاب کنید.",true);return;}
    const amount=$("campaign-budget").value,currency=$("campaign-currency").value;
    if(Boolean(amount)!==Boolean(currency)){say("مبلغ و واحد پول بودجه را با هم وارد کنید.",true);return;}
    const body={name:$("campaign-name").value,segment_id:$("campaign-segment").value,objective_key:$("campaign-objective").value,communication_purpose_key:"marketing",channel:$("campaign-channel").value,starts_at:localIso("campaign-start"),ends_at:localIso("campaign-end"),planned_budget_amount:amount?Number(amount):null,planned_budget_currency:currency||null};
    const button=$("save-campaign");button.disabled=true;
    try{
      if(editingId){await api("/api/v1/crm/campaigns/"+encodeURIComponent(editingId),{method:"PATCH",body:JSON.stringify(body)});say("تغییرات کمپین ذخیره شد.");}
      else{await api("/api/v1/crm/campaigns",{method:"POST",body:JSON.stringify({...body,organization_unit_id:unit.value})});say("پیش‌نویس کمپین ثبت شد.");}
      $("campaign-form").hidden=true;clearCampaignForm();await loadCampaigns(true);
    }catch(error){say(error.message,true);}finally{button.disabled=false;}
  });
  $("new-campaign").addEventListener("click",async()=>{clearCampaignForm();$("campaign-form").hidden=false;try{await loadSegments();}catch(error){say(error.message,true);}});
  $("cancel-campaign").addEventListener("click",()=>{$("campaign-form").hidden=true;clearCampaignForm();});
  async function loadAssets(){
    if(!workspace.value||!unit.value)return;say("در حال دریافت محتوا…");
    try{assets=await api("/api/v1/crm/marketing-assets?organization_unit_id="+encodeURIComponent(unit.value)+"&limit=100");renderAssets();say("فهرست دارایی‌های محتوا به‌روز شد.");}
    catch(error){say(error.message,true);$("asset-list").replaceChildren(el("div",error.message,"empty"));}
  }
  function renderAssets(){
    const host=$("asset-list");host.replaceChildren();
    if(!assets.length){host.appendChild(el("div","دارایی محتوایی برای این واحد ثبت نشده است.","empty"));return;}
    assets.forEach(a=>{
      const card=document.createElement("article");card.className="item";const head=document.createElement("div");head.className="item-head";const info=document.createElement("div");
      info.appendChild(el("strong",a.title));const meta=document.createElement("div");meta.className="item-meta";const campaign=campaigns.find(c=>c.id===a.campaign_id);
      [assetStates[a.status]||a.status,channels[a.channel]||a.channel,a.asset_kind,campaign?.name||"بدون کمپین",a.locale||"زبان نامشخص"].forEach(v=>meta.appendChild(el("span",v)));
      info.appendChild(meta);head.appendChild(info);head.appendChild(el("span",assetStates[a.status]||a.status,"badge"));card.appendChild(head);
      if(a.body)card.appendChild(el("p",a.body));if(a.external_url){const link=document.createElement("a");link.href=a.external_url;link.rel="noopener noreferrer";link.target="_blank";link.textContent="مشاهدهٔ منبع";card.appendChild(link);}
      if(a.review_note)card.appendChild(el("p","یادداشت بازبینی: "+a.review_note));
      const actions=document.createElement("div");actions.className="actions";
      if(a.status==="draft"||a.status==="rejected"){const submit=el("button","ارسال برای بازبینی","secondary");submit.type="button";submit.addEventListener("click",()=>assetAction(a,"submit"));actions.appendChild(submit);}
      if(a.status==="in_review"){
        const approve=el("button","تأیید محتوا","primary");approve.type="button";approve.addEventListener("click",()=>assetAction(a,"review",{decision:"approve"}));actions.appendChild(approve);
        const reject=el("button","درخواست اصلاح","danger");reject.type="button";reject.addEventListener("click",()=>{const note=window.prompt("دلیل درخواست اصلاح را وارد کنید:");if(note?.trim())assetAction(a,"review",{decision:"reject",note:note.trim()});});actions.appendChild(reject);
      }
      if(actions.childElementCount)card.appendChild(actions);host.appendChild(card);
    });
  }
  async function assetAction(asset,action,payload={}){
    try{await api("/api/v1/crm/marketing-assets/"+encodeURIComponent(asset.id)+"/"+action,{method:"POST",body:action==="review"?JSON.stringify(payload):undefined});await loadAssets();}
    catch(error){say(error.message,true);}
  }
  $("asset-form").addEventListener("submit",async event=>{
    event.preventDefault();if(!unit.value){say("ابتدا واحد سازمانی را انتخاب کنید.",true);return;}
    const campaignId=$("asset-campaign").value, linked=campaigns.find(c=>c.id===campaignId);
    const body=$("asset-body").value.trim(),url=$("asset-url").value.trim();
    if(!body&&!url){say("متن محتوا یا پیوند منبع را وارد کنید.",true);return;}
    const payload={organization_unit_id:unit.value,campaign_id:campaignId||null,channel:linked?linked.channel:$("asset-channel").value,asset_kind:$("asset-kind").value,title:$("asset-title").value,body:body||null,external_url:url||null,locale:$("asset-locale").value||null};
    const button=$("asset-form").querySelector('button[type="submit"]');button.disabled=true;
    try{await api("/api/v1/crm/marketing-assets",{method:"POST",body:JSON.stringify(payload)});$("asset-form").reset();$("asset-locale").value="fa-IR";$("asset-form").hidden=true;await loadAssets();say("محتوا به‌صورت پیش‌نویس ثبت شد.");}
    catch(error){say(error.message,true);}finally{button.disabled=false;}
  });
  $("asset-campaign").addEventListener("change",()=>{const c=campaigns.find(item=>item.id===$("asset-campaign").value);if(c)$("asset-channel").value=c.channel;});
  $("new-asset").addEventListener("click",()=>{$("asset-form").hidden=!$("asset-form").hidden;syncAssetCampaigns();});
  $("cancel-asset").addEventListener("click",()=>{$("asset-form").hidden=true;});
  function renderCalendar(data){
    const host=$("calendar-events"),conflicts=$("calendar-conflicts");host.replaceChildren();conflicts.replaceChildren();
    (data.schedule_conflicts||[]).forEach(c=>{const msg=c.campaign_name+" با "+c.conflicting_campaign_name+" هم‌پوشانی دارد؛ "+c.overlap_start+" تا "+c.overlap_end;conflicts.appendChild(el("div",msg,"conflict"));});
    const rows=data.events||[];
    if(!rows.length)host.appendChild(el("div","در این بازه رویدادی ثبت نشده است.","empty"));
    rows.forEach(event=>{const card=document.createElement("article");card.className="item";card.appendChild(el("strong",event.title));const meta=document.createElement("div");meta.className="item-meta";[event.kind==="campaign"?"کمپین":"کار",event.status,event.start_date+" تا "+event.end_date,channels[event.channel]||event.channel||"کانال نامشخص"].forEach(v=>meta.appendChild(el("span",v)));card.appendChild(meta);host.appendChild(card);});
    $("calendar-basis").textContent=data.basis||"";$("calendar-range").textContent=data.period_start+" تا "+data.period_end;
  }
  async function loadCalendar(){
    if(!workspace.value||!unit.value)return;
    const now=new Date(),start=new Date(now),end=new Date(now);start.setDate(start.getDate()-30);end.setDate(end.getDate()+60);
    const fmt=d=>d.toISOString().slice(0,10);
    say("در حال دریافت تقویم کمپین…");
    try{const data=await api("/api/v1/crm/marketing-calendar/events?period_start="+fmt(start)+"&period_end="+fmt(end)+unitQuery());renderCalendar(data);say("تقویم به‌روز شد.");}
    catch(error){say(error.message,true);}
  }
  async function activateView(view){
    currentView=view;document.querySelectorAll(".tab").forEach(t=>t.classList.toggle("active",t.dataset.view===view));
    ["campaigns","assets","calendar"].forEach(key=>{$("view-"+key).hidden=key!==view;});
    if(!unit.value)return;
    if(view==="campaigns")await loadCampaigns(true);if(view==="assets"){if(!campaigns.length)await loadCampaigns(true);await loadAssets();}if(view==="calendar")await loadCalendar();
  }
  document.querySelectorAll(".tab").forEach(t=>t.addEventListener("click",()=>activateView(t.dataset.view)));
  $("refresh").addEventListener("click",()=>activateView(currentView));$("calendar-refresh").addEventListener("click",loadCalendar);
  $("campaign-more").addEventListener("click",()=>loadCampaigns(false));
  unit.addEventListener("change",async()=>{if(!unit.value)return;try{await loadSegments();await loadCampaigns(true);if(currentView==="assets")await loadAssets();if(currentView==="calendar")await loadCalendar();}catch(error){say(error.message,true);}});
  async function loadUnits(){
    const rows=await api("/api/v1/system/organization-units");unit.replaceChildren();const placeholder=el("option","واحد سازمانی را انتخاب کنید");placeholder.value="";unit.appendChild(placeholder);
    rows.forEach(row=>{const o=el("option",row.name);o.value=row.id;unit.appendChild(o);});
    if(rows.length===1)unit.value=rows[0].id;
  }
  async function init(){
    try{const spaces=await api("/api/v1/system/workspaces");workspace.replaceChildren();const p=el("option","فضای کاری را انتخاب کنید");p.value="";workspace.appendChild(p);spaces.forEach(s=>{const o=el("option",s.name);o.value=s.id;workspace.appendChild(o);});
      const params=new URLSearchParams(location.search),requested=spaces.find(s=>s.id===params.get("workspace_id"));workspace.value=requested?requested.id:(spaces.length===1?spaces[0].id:"");
      if(workspace.value){await loadUnits();if(unit.value){await loadSegments();await loadCampaigns(true);}}
      else say("فضای کاری را انتخاب کنید.");
    }catch(error){say(error.message,true);}
  }
  workspace.addEventListener("change",async()=>{unit.value="";if(!workspace.value)return;try{await loadUnits();if(unit.value){await loadSegments();await loadCampaigns(true);}}catch(error){say(error.message,true);}});
  init();
})();"""

@router.get("/workspace/crm-campaigns", response_class=HTMLResponse)
async def crm_campaign_workspace_page() -> HTMLResponse:
    return HTMLResponse(_PAGE, headers=_HEADERS)


@router.get("/assets/crm-campaign-workspace.js")
async def crm_campaign_workspace_script() -> Response:
    return Response(
        _SCRIPT,
        media_type="application/javascript",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
