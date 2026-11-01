"""Sales pipeline and revenue workspace."""
from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["CRM sales workspace"], include_in_schema=False)

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
<title>مدیریت فروش و درآمد | فانل CRM</title>
<style>
:root{font-family:Tahoma,Arial,sans-serif;color:#172c42;background:#f4f7fb;font-synthesis:none}*{box-sizing:border-box}body{margin:0}.app{min-height:100vh;display:grid;grid-template-columns:230px minmax(0,1fr)}aside{background:#fff;border-left:1px solid #e3e9f0;padding:20px 14px;position:sticky;top:0;height:100vh}.brand{font-size:19px;font-weight:800;padding:0 10px 24px}.brand b{color:#158b91}nav{display:grid;gap:5px}.nav{display:block;padding:11px;border-radius:9px;color:#54677a;text-decoration:none;font-size:12px}.nav.active,.nav:hover{background:#eaf4f7;color:#125d77;font-weight:700}main{min-width:0;padding:24px clamp(16px,3vw,42px) 48px}.top{display:flex;align-items:center;gap:12px;margin-bottom:20px}.top h1{font-size:24px;margin:0}.spacer{flex:1}.top a{color:#176687;text-decoration:none;font-size:12px}.filters{display:flex;align-items:end;gap:9px;flex-wrap:wrap;margin-bottom:14px}.filters label,.form-grid label{display:grid;gap:5px;color:#7c8a99;font-size:11px}input,select{height:39px;border:1px solid #dce4ec;border-radius:8px;padding:0 10px;background:#fff;color:#243c53;font:inherit;font-size:12px;min-width:145px}button{font:inherit;cursor:pointer}.primary,.secondary{border-radius:8px;height:39px;padding:0 13px;font-size:12px;font-weight:700}.primary{border:0;background:#126b91;color:#fff}.secondary{border:1px solid #d8e1e9;background:#fff;color:#31566d}.status{min-height:22px;color:#718091;font-size:12px;margin:0 0 12px}.status.error{color:#a43b37}.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:13px}.card,.panel{background:#fff;border:1px solid #e3e9ef;border-radius:12px;padding:15px;box-shadow:0 4px 16px #22354b08;min-width:0}.kpi-label{font-size:11px;color:#718091}.kpi-value{font-size:20px;font-weight:800;margin-top:9px;color:#24435b}.tabs{display:flex;gap:7px;border-bottom:1px solid #e7edf2;margin:12px 0 14px;overflow:auto}.tab{border:0;background:none;color:#6f8090;padding:10px;font:inherit;font-size:12px;white-space:nowrap;border-bottom:2px solid transparent}.tab.active{color:#126b91;border-color:#126b91;font-weight:700}.view[hidden],#opportunity-form[hidden],#target-form[hidden]{display:none}.view{display:grid;gap:12px}.head{display:flex;align-items:center;gap:10px}.head h2{font-size:15px;margin:0}.muted{font-size:11px;color:#81909e}.board{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;align-items:start}.stage{border:1px solid #e6ecf1;border-radius:10px;background:#f8fafc;padding:11px;min-height:100px}.stage h3{font-size:12px;margin:0 0 9px;display:flex;justify-content:space-between}.opp{background:#fff;border:1px solid #e6ecf1;border-radius:8px;padding:10px;margin-bottom:7px}.opp strong{font-size:12px;display:block;color:#27475d}.opp p{font-size:10px;line-height:1.7;color:#728293;margin:5px 0}.opp button{font-size:10px;height:30px}.formbox{background:#f8fafc;border:1px solid #e7edf2;border-radius:10px;padding:14px}.form-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.wide{grid-column:1/-1}.form-actions{display:flex;gap:8px;margin-top:11px}.empty{border:1px dashed #d7e0e8;border-radius:9px;padding:18px;color:#758493;text-align:center;font-size:12px;line-height:1.8}.rows{display:grid;gap:8px}.row{border:1px solid #e7edf2;background:#fbfcfd;border-radius:9px;padding:11px;font-size:11px;color:#546a7d}.row strong{font-size:12px;color:#29495f}.row-meta{display:flex;flex-wrap:wrap;gap:9px;margin-top:5px;color:#7c8b99}.foot{font-size:10px;color:#8995a0;line-height:1.8}.target-grid{display:grid;grid-template-columns:1.3fr 1fr;gap:12px}
@media(max-width:900px){.app{grid-template-columns:190px minmax(0,1fr)}.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.target-grid{grid-template-columns:1fr}}
@media(max-width:650px){.app{display:block}aside{position:relative;height:auto;border:0;border-bottom:1px solid #e3e9f0;padding:12px}.brand{padding:0 8px 8px}nav{display:flex;overflow:auto}.nav{white-space:nowrap}main{padding:16px 12px 32px}.top{flex-wrap:wrap}.top h1{font-size:20px}.filters{display:grid;grid-template-columns:1fr 1fr}.filters label,.filters input,.filters select{min-width:0;width:100%}.filters .primary{grid-column:1/-1}.form-grid{grid-template-columns:1fr}.wide{grid-column:auto}.board{grid-template-columns:1fr}.item-head{display:block}}
</style>
<script src="/assets/crm-sales-workspace.js" defer></script>
</head>
<body><div class="app">
<aside><div class="brand"><b>ف</b> فانل CRM</div><nav aria-label="ماژول‌های CRM">
<a class="nav" href="/workspace/marketing-manager">اتاق تصمیم‌گیری</a>
<a class="nav" href="/workspace/crm-customers">مشتریان و پرونده‌ها</a>
<a class="nav" href="/workspace/crm-campaigns">کمپین و محتوا</a>
<a class="nav active" href="/workspace/crm-sales" aria-current="page">مدیریت فروش و درآمد</a>
<a class="nav" href="/workspace/crm-offers">پیشنهادهای فروش</a>
<a class="nav" href="/workspace/crm-commissions">کمیسیون</a>
</nav></aside>
<main>
<header class="top"><h1>مدیریت فروش و درآمد</h1><span class="spacer"></span><a href="/workspace/marketing-manager">بازگشت به اتاق تصمیم‌گیری</a></header>
<div class="filters">
<label>فضای کاری<select id="workspace-id"><option value="">در حال دریافت…</option></select></label>
<label>واحد سازمانی<select id="organization-unit"><option value="">واحد مجاز را انتخاب کنید</option></select></label>
<label>پایپ‌لاین<select id="pipeline"><option value="">پایپ‌لاین را انتخاب کنید</option></select></label>
<button id="refresh" class="primary" type="button">به‌روزرسانی</button>
</div>
<p id="status" class="status" role="status" aria-live="polite">در حال آماده‌سازی…</p>
<section class="kpis" aria-label="شاخص‌های فروش">
<article class="card"><div class="kpi-label">کل فرصت‌های پایپ‌لاین</div><div id="kpi-total" class="kpi-value">—</div></article>
<article class="card"><div class="kpi-label">موعد گذشته</div><div id="kpi-overdue" class="kpi-value">—</div></article>
<article class="card"><div class="kpi-label">موعد ۷ روز آینده</div><div id="kpi-soon" class="kpi-value">—</div></article>
<article class="card"><div class="kpi-label">پیش‌بینی وزنی</div><div id="kpi-forecast" class="kpi-value">—</div></article>
</section>
<section class="panel">
<div class="tabs" role="tablist" aria-label="نمای فروش">
<button class="tab active" data-view="pipeline" type="button">فرصت‌ها و پایپ‌لاین</button>
<button class="tab" data-view="followups" type="button">پیگیری موعدها</button>
<button class="tab" data-view="forecast" type="button">پیش‌بینی درآمد</button>
<button class="tab" data-view="targets" type="button">اهداف فروش</button>
</div>
<section id="view-pipeline" class="view">
<div class="head"><h2>فرصت‌های فروش</h2><span class="spacer"></span><button id="new-opportunity" class="primary" type="button">فرصت جدید</button></div>
<form id="opportunity-form" class="formbox" hidden>
<div class="form-grid">
<label class="wide">نام فرصت<input id="opportunity-name" maxlength="200" required></label>
<label>مشتری (اختیاری)<select id="profile-id"><option value="">بدون اتصال به پروندهٔ مشتری</option></select></label>
<label>مرحله<select id="opportunity-stage" required></select></label>
<label>تاریخ پیش‌بینی بستن<input id="close-date" type="date"></label>
<label>مبلغ<input id="amount" type="number" min="0" step="0.01"></label>
<label>واحد پول<select id="currency"><option value="">بدون مبلغ</option><option value="IRR">IRR</option><option value="USD">USD</option><option value="EUR">EUR</option></select></label>
</div>
<div class="form-actions"><button id="save-opportunity" class="primary" type="submit">ثبت فرصت</button><button id="cancel-opportunity" class="secondary" type="button">انصراف</button></div>
</form>
<div id="pipeline-board" class="board"><div class="empty">برای نمایش پایپ‌لاین، فضای کاری، واحد سازمانی و پایپ‌لاین را انتخاب کنید.</div></div>
<p class="foot">تغییر مرحله، مبلغ یا تاریخ در پرونده ثبت می‌شود و تاریخچهٔ تغییرات API را حفظ می‌کند.</p>
</section>
<section id="view-followups" class="view" hidden>
<div class="head"><h2>موعدهای بستن فرصت‌ها</h2><span class="muted">امروز تا ۷ روز آینده و موارد عقب‌افتاده</span></div>
<div id="followup-summary" class="kpis"></div><div id="followup-list" class="rows"></div>
</section>
<section id="view-forecast" class="view" hidden>
<div class="head"><h2>پیش‌بینی درآمد</h2><span class="muted">بر اساس احتمال مرحلهٔ تعریف‌شده</span></div>
<div class="filters"><label>از تاریخ<input id="forecast-start" type="date"></label><label>تا تاریخ<input id="forecast-end" type="date"></label><button id="forecast-refresh" class="secondary" type="button">محاسبه</button></div>
<div id="forecast-detail" class="rows"></div><p id="forecast-basis" class="foot"></p>
</section>
<section id="view-targets" class="view" hidden>
<div class="target-grid">
<div><div class="head"><h2>اهداف فروش ثبت‌شده</h2></div><div id="target-list" class="rows"></div></div>
<div><div class="head"><h2>ثبت هدف دوره</h2></div>
<form id="target-form" class="formbox">
<div class="form-grid">
<label>شروع دوره<input id="target-start" type="date" required></label>
<label>پایان دوره<input id="target-end" type="date" required></label>
<label>هدف مبلغ<input id="target-amount" type="number" min="0.01" step="0.01" required></label>
<label>واحد پول<select id="target-currency"><option value="IRR">IRR</option><option value="USD">USD</option><option value="EUR">EUR</option></select></label>
</div><div class="form-actions"><button class="primary" type="submit">ثبت هدف فروش</button></div></form>
<p class="foot">ثبت هدف نیازمند مجوز مدیریت هدف فروش در واحد انتخابی است.</p></div>
</div>
</section>
</section>
</main></div></body></html>"""

_SCRIPT = r"""(() => {
  const $ = (id) => document.getElementById(id);
  const workspace=$("workspace-id"),unit=$("organization-unit"),pipelineSelect=$("pipeline"),status=$("status");
  const number=new Intl.NumberFormat("fa-IR",{maximumFractionDigits:0});
  let pipelines=[],opportunities=[],profiles=[],offset=0,total=0,editing=null,view="pipeline";
  const outcomes={open:"در جریان",won:"برد",lost:"باخت"};
  function say(message,error=false){status.textContent=message;status.classList.toggle("error",error);}
  function node(tag,text,className=""){const n=document.createElement(tag);n.textContent=String(text??"");if(className)n.className=className;return n;}
  async function api(path,options={}){
    const headers={Accept:"application/json",...(options.headers||{})};if(options.body)headers["Content-Type"]="application/json";if(workspace.value)headers["X-Workspace-ID"]=workspace.value;
    const response=await fetch(path,{credentials:"same-origin",...options,headers});let data={};try{data=response.status===204?{}:await response.json();}catch(_){}
    if(!response.ok){const d=typeof data.detail==="string"?data.detail:(data.detail?.message||data.message);throw new Error(d||"درخواست ناموفق بود ("+response.status+").");}return data;
  }
  function unitQuery(){return unit.value?"organization_unit_id="+encodeURIComponent(unit.value):"";}
  function pipeline(){return pipelines.find(p=>p.id===pipelineSelect.value);}
  function stages(){return (pipeline()?.stages||[]).slice().sort((a,b)=>a.position-b.position);}
  function fillStages(selected=""){
    const select=$("opportunity-stage");select.replaceChildren();
    stages().forEach(stage=>{const o=node("option",stage.name+" · "+(outcomes[stage.outcome_key]||stage.outcome_key));o.value=stage.key;select.appendChild(o);});
    if(selected)select.value=selected;
  }
  async function loadPipelines(){
    pipelines=await api("/api/v1/crm/opportunities/pipelines");pipelineSelect.replaceChildren();
    const first=node("option","پایپ‌لاین را انتخاب کنید");first.value="";pipelineSelect.appendChild(first);
    pipelines.forEach(item=>{const o=node("option",item.display_name+(item.is_default?" · پیش‌فرض":""));o.value=item.id;pipelineSelect.appendChild(o);});
    if(pipelines.length===1)pipelineSelect.value=pipelines[0].id;
    else if(pipelines.some(p=>p.is_default))pipelineSelect.value=pipelines.find(p=>p.is_default).id;
  }
  async function loadUnits(){
    const rows=await api("/api/v1/system/opportunity-organization-units");unit.replaceChildren();const p=node("option","واحد سازمانی را انتخاب کنید");p.value="";unit.appendChild(p);
    rows.forEach(item=>{const o=node("option",item.name);o.value=item.id;unit.appendChild(o);});if(rows.length===1)unit.value=rows[0].id;
  }
  async function loadProfiles(){
    profiles=[];$("profile-id").replaceChildren();const p=node("option","بدون اتصال به پروندهٔ مشتری");p.value="";$("profile-id").appendChild(p);
    if(!unit.value)return;
    try{const data=await api("/api/v1/crm/profiles?limit=100&organization_unit_id="+encodeURIComponent(unit.value));profiles=data.items||[];profiles.forEach(profile=>{const o=node("option",profile.display_name);o.value=profile.id;$("profile-id").appendChild(o);});}
    catch(_){/* CRM profile access is optional for opportunity creation. */}
  }
  function money(amount,currency){return amount===null||amount===undefined?"مبلغ ثبت نشده":number.format(Number(amount))+" "+(currency||"");}
  function renderBoard(){
    const host=$("pipeline-board");host.replaceChildren();
    const defs=stages();if(!defs.length){host.appendChild(node("div","پایپ‌لاین قابل‌نمایشی برای حساب پیدا نشد.","empty"));return;}
    defs.forEach(stage=>{
      const col=document.createElement("section");col.className="stage";const heading=document.createElement("h3");heading.appendChild(node("span",stage.name));heading.appendChild(node("span",number.format(opportunities.filter(o=>o.stage_key===stage.key).length)));col.appendChild(heading);
      opportunities.filter(o=>o.stage_key===stage.key).forEach(opportunity=>{
        const card=document.createElement("article");card.className="opp";card.appendChild(node("strong",opportunity.name));
        card.appendChild(node("p",money(opportunity.amount,opportunity.currency)+" · موعد: "+(opportunity.expected_close_date||"تعیین نشده")));
        const profile=profiles.find(p=>p.id===opportunity.profile_id);if(profile)card.appendChild(node("p","مشتری: "+profile.display_name));
        const edit=node("button","ویرایش","secondary");edit.type="button";edit.addEventListener("click",()=>editOpportunity(opportunity));card.appendChild(edit);col.appendChild(card);
      });
      if(!opportunities.some(o=>o.stage_key===stage.key))col.appendChild(node("p","فرصتی ثبت نشده است.","foot"));
      host.appendChild(col);
    });
    $("kpi-total").textContent=number.format(total);
  }
  async function loadOpportunities(reset=true){
    if(!workspace.value||!unit.value||!pipelineSelect.value)return;
    if(reset){opportunities=[];offset=0;}say("در حال دریافت فرصت‌ها…");
    try{const data=await api("/api/v1/crm/opportunities?pipeline_id="+encodeURIComponent(pipelineSelect.value)+"&limit=100&offset="+offset+"&"+unitQuery());opportunities=reset?data.items:opportunities.concat(data.items);total=data.total;offset+=data.items.length;renderBoard();say("پایپ‌لاین به‌روز شد.");}
    catch(error){say(error.message,true);}
  }
  function clearForm(){editing=null;$("opportunity-form").reset();$("save-opportunity").textContent="ثبت فرصت";fillStages();}
  function editOpportunity(item){
    editing=item.id;$("opportunity-form").hidden=false;$("opportunity-name").value=item.name;$("profile-id").value=item.profile_id||"";
    fillStages(item.stage_key);$("close-date").value=item.expected_close_date||"";$("amount").value=item.amount??"";$("currency").value=item.currency||"";
    $("save-opportunity").textContent="ذخیرهٔ تغییر";$("opportunity-form").scrollIntoView({behavior:"smooth",block:"start"});
  }
  $("opportunity-form").addEventListener("submit",async event=>{
    event.preventDefault();if(!unit.value||!pipelineSelect.value){say("واحد و پایپ‌لاین را انتخاب کنید.",true);return;}
    const amount=$("amount").value,currency=$("currency").value;if(Boolean(amount)!==Boolean(currency)){say("مبلغ و واحد پول را با هم وارد کنید.",true);return;}
    const values={name:$("opportunity-name").value,stage_key:$("opportunity-stage").value,amount:amount?Number(amount):null,currency:currency||null,expected_close_date:$("close-date").value||null};
    const button=$("save-opportunity");button.disabled=true;
    try{
      if(editing){await api("/api/v1/crm/opportunities/"+encodeURIComponent(editing),{method:"PATCH",body:JSON.stringify(values)});say("فرصت فروش به‌روز شد.");}
      else{await api("/api/v1/crm/opportunities",{method:"POST",body:JSON.stringify({...values,organization_unit_id:unit.value,pipeline_id:pipelineSelect.value,profile_id:$("profile-id").value||null})});say("فرصت فروش ثبت شد.");}
      $("opportunity-form").hidden=true;clearForm();await loadOpportunities(true);await loadFollowups();
    }catch(error){say(error.message,true);}finally{button.disabled=false;}
  });
  $("new-opportunity").addEventListener("click",async()=>{clearForm();$("opportunity-form").hidden=false;await loadProfiles();fillStages();});
  $("cancel-opportunity").addEventListener("click",()=>{$("opportunity-form").hidden=true;clearForm();});
  async function loadFollowups(){
    if(!unit.value||!pipelineSelect.value)return;
    try{
      const result=await api("/api/v1/crm/opportunities/worklist?date_state=all&days_ahead=7&limit=100&organization_unit_id="+encodeURIComponent(unit.value)+"&pipeline_id="+encodeURIComponent(pipelineSelect.value));
      const counts=result.counts_by_state||{};$("kpi-overdue").textContent=number.format(counts.overdue||0);$("kpi-soon").textContent=number.format(counts.due_soon||0);
      const summary=$("followup-summary");summary.replaceChildren();
      [["موعد گذشته",counts.overdue||0],["۷ روز آینده",counts.due_soon||0],["موعدهای دورتر",counts.later||0],["بدون موعد",counts.unscheduled||0]].forEach(([label,value])=>{const card=document.createElement("article");card.className="card";card.appendChild(node("div",label,"kpi-label"));card.appendChild(node("div",number.format(value),"kpi-value"));summary.appendChild(card);});
      const host=$("followup-list");host.replaceChildren();
      if(!result.items?.length){host.appendChild(node("div","فرصت موعددار یا عقب‌افتاده‌ای برای نمایش نیست.","empty"));return;}
      result.items.forEach(item=>{const row=document.createElement("article");row.className="row";row.appendChild(node("strong",item.name));row.appendChild(node("div",(item.date_state==="overdue"?"عقب‌افتاده":item.date_state==="due_soon"?"موعد نزدیک":item.date_state==="later"?"موعد بعدی":"بدون موعد")+" · "+(item.expected_close_date||"تعیین نشده")+" · "+money(item.amount,item.currency),"row-meta"));host.appendChild(row);});
    }catch(error){$("followup-list").replaceChildren(node("div",error.message,"empty"));}
  }
  function dateString(date){return date.toISOString().slice(0,10);}
  function setDefaultRange(){
    const today=new Date(),end=new Date(today);end.setDate(end.getDate()+90);$("forecast-start").value=dateString(today);$("forecast-end").value=dateString(end);
    $("target-start").value=dateString(new Date(today.getFullYear(),today.getMonth(),1));$("target-end").value=dateString(new Date(today.getFullYear(),today.getMonth()+1,0));
  }
  function renderCurrencies(title,values){
    const card=document.createElement("article");card.className="row";card.appendChild(node("strong",title));
    const entries=Object.entries(values||{});card.appendChild(node("div",entries.length?entries.map(([currency,value])=>number.format(Number(value))+" "+currency).join(" · "):"داده‌ای برای این بازه ثبت نشده است.","row-meta"));return card;
  }
  async function loadForecast(){
    if(!pipelineSelect.value)return;
    const start=$("forecast-start").value,end=$("forecast-end").value;if(!start||!end||start>end){say("بازهٔ پیش‌بینی را بررسی کنید.",true);return;}
    try{
      const result=await api("/api/v1/crm/sales-forecast/opportunities?pipeline_id="+encodeURIComponent(pipelineSelect.value)+"&period_start="+start+"&period_end="+end+"&organization_unit_id="+encodeURIComponent(unit.value));
      const host=$("forecast-detail");host.replaceChildren();
      host.appendChild(renderCurrencies("مبلغ ناخالص فرصت‌های این بازه",result.gross_amount_by_currency));
      host.appendChild(renderCurrencies("پیش‌بینی وزنی بر اساس احتمال مرحله",result.weighted_expected_amount_by_currency));
      host.appendChild(renderCurrencies("مبلغ بدون احتمال تعریف‌شده",result.amount_without_probability_by_currency));
      (result.stages||[]).forEach(stage=>{const row=document.createElement("article");row.className="row";row.appendChild(node("strong",stage.stage_name+" · "+number.format(stage.opportunity_count)+" فرصت"));row.appendChild(node("div","احتمال: "+(stage.probability_percent===null?"تعریف نشده":number.format(stage.probability_percent)+"٪")+" · بدون مبلغ: "+number.format(stage.unpriced_opportunity_count)+" · مبلغ وزنی: "+Object.entries(stage.weighted_expected_amount_by_currency||{}).map(([c,v])=>number.format(Number(v))+" "+c).join("، "),"row-meta"));host.appendChild(row);});
      $("kpi-forecast").textContent=Object.entries(result.weighted_expected_amount_by_currency||{}).map(([c,v])=>number.format(Number(v))+" "+c).join(" · ")||"نامشخص";
      $("forecast-basis").textContent=result.forecast_basis+" · فرصت‌های بدون تاریخ بستن: "+number.format(result.unscheduled_opportunity_count)+" · موارد بدون احتمال: "+number.format(result.unknown_probability_opportunity_count);
    }catch(error){$("forecast-detail").replaceChildren(node("div",error.message,"empty"));$("kpi-forecast").textContent="نامشخص";}
  }
  async function loadTargets(){
    if(!unit.value||!pipelineSelect.value)return;
    try{
      const data=await api("/api/v1/crm/sales-targets?organization_unit_id="+encodeURIComponent(unit.value)+"&pipeline_id="+encodeURIComponent(pipelineSelect.value));
      const host=$("target-list");host.replaceChildren();const rows=data.items||[];
      if(!rows.length){host.appendChild(node("div","برای این پایپ‌لاین هدف فروشی ثبت نشده است.","empty"));return;}
      rows.forEach(target=>{const row=document.createElement("article");row.className="row";row.appendChild(node("strong",number.format(Number(target.target_amount))+" "+target.currency));row.appendChild(node("div",target.period_start+" تا "+target.period_end,"row-meta"));host.appendChild(row);});
    }catch(error){$("target-list").replaceChildren(node("div",error.message,"empty"));}
  }
  $("target-form").addEventListener("submit",async event=>{
    event.preventDefault();if(!unit.value||!pipelineSelect.value){say("واحد و پایپ‌لاین را انتخاب کنید.",true);return;}
    const payload={organization_unit_id:unit.value,pipeline_id:pipelineSelect.value,period_start:$("target-start").value,period_end:$("target-end").value,currency:$("target-currency").value,target_amount:Number($("target-amount").value)};
    try{await api("/api/v1/crm/sales-targets",{method:"POST",body:JSON.stringify(payload)});$("target-form").reset();setDefaultRange();await loadTargets();say("هدف فروش ثبت شد.");}
    catch(error){say(error.message,true);}
  });
  async function activate(viewName){
    view=viewName;document.querySelectorAll(".tab").forEach(tab=>tab.classList.toggle("active",tab.dataset.view===viewName));
    ["pipeline","followups","forecast","targets"].forEach(key=>{$("view-"+key).hidden=key!==viewName;});
    if(viewName==="pipeline")await loadOpportunities(true);
    if(viewName==="followups")await loadFollowups();
    if(viewName==="forecast")await loadForecast();
    if(viewName==="targets")await loadTargets();
  }
  document.querySelectorAll(".tab").forEach(tab=>tab.addEventListener("click",()=>activate(tab.dataset.view)));
  $("refresh").addEventListener("click",()=>activate(view));$("forecast-refresh").addEventListener("click",loadForecast);
  unit.addEventListener("change",async()=>{if(!unit.value)return;await loadProfiles();await activate(view);});
  pipelineSelect.addEventListener("change",()=>activate(view));
  async function init(){
    setDefaultRange();
    try{
      const spaces=await api("/api/v1/system/workspaces");workspace.replaceChildren();const p=node("option","فضای کاری را انتخاب کنید");p.value="";workspace.appendChild(p);
      spaces.forEach(space=>{const o=node("option",space.name);o.value=space.id;workspace.appendChild(o);});
      const params=new URLSearchParams(location.search),requested=spaces.find(s=>s.id===params.get("workspace_id"));workspace.value=requested?requested.id:(spaces.length===1?spaces[0].id:"");
      if(workspace.value){await loadUnits();await loadPipelines();if(unit.value&&pipelineSelect.value){await loadProfiles();await activate("pipeline");}}
      else say("فضای کاری را انتخاب کنید.");
    }catch(error){say(error.message,true);}
  }
  workspace.addEventListener("change",async()=>{unit.value="";pipelineSelect.value="";if(!workspace.value)return;try{await loadUnits();await loadPipelines();if(unit.value&&pipelineSelect.value){await loadProfiles();await activate("pipeline");}}catch(error){say(error.message,true);}});
  init();
})();"""

@router.get("/workspace/crm-sales", response_class=HTMLResponse)
async def crm_sales_workspace_page() -> HTMLResponse:
    return HTMLResponse(_PAGE, headers=_HEADERS)


@router.get("/assets/crm-sales-workspace.js")
async def crm_sales_workspace_script() -> Response:
    return Response(
        _SCRIPT,
        media_type="application/javascript",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
