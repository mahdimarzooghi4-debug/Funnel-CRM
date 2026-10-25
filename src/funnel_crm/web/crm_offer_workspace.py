"""Persian RTL workspace for opportunity offer drafts."""
from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["CRM offer workspace"], include_in_schema=False)
_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'unsafe-inline'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
}

_PAGE = """<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>پیش‌نویس پیشنهاد فروش | فانل CRM</title><style>
:root{font-family:Tahoma,Arial,sans-serif;color:#182638;background:#f4f7fb}*{box-sizing:border-box}body{margin:0}header{background:#12334a;color:white;padding:20px max(16px,calc((100vw - 1050px)/2))}main{max-width:1050px;margin:24px auto;padding:0 16px 48px}h1{font-size:clamp(23px,4vw,32px)}h2{font-size:19px}.panel{background:white;border:1px solid #e0e7ef;border-radius:14px;padding:20px;margin:16px 0;box-shadow:0 5px 18px #142d420d}.grid,.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px}label{display:grid;gap:6px;font-size:13px;color:#405367}select,input,button{font:inherit;min-height:42px;border:1px solid #cbd6e0;border-radius:8px;padding:8px 10px;background:white;color:#182638}button{background:#1578a8;color:white;border:0;font-weight:bold;cursor:pointer}button:disabled{opacity:.5}.actions{display:flex;gap:10px;margin-top:14px}#status{min-height:24px}.muted{color:#687b8d;font-size:13px;line-height:1.8}.card{border:1px solid #dce5ed;border-radius:10px;padding:14px}.line{display:grid;grid-template-columns:minmax(150px,1fr) minmax(180px,2fr) 130px;gap:10px;align-items:end;margin:12px 0}.totals{font-weight:bold;color:#17613b}@media(max-width:600px){.line{grid-template-columns:1fr}.panel{padding:15px}}
</style><script src="/assets/crm-offer-workspace.js" defer></script></head><body><header><strong>فانل CRM</strong></header><main>
<h1>پیش‌نویس پیشنهاد فروش</h1><p class="muted">پیشنهاد از محصول‌ها و خدمات متصل به فرصت ساخته می‌شود. قیمت‌ها snapshot می‌شوند و ساخت پیش‌نویس، سفارش یا تعهد فروش ایجاد نمی‌کند.</p><p id="status" role="status" aria-live="polite"></p>
<section class="panel"><h2>محدوده و فرصت</h2><div class="grid"><label>فضای کاری<select id="workspace" required></select></label><label>واحد سازمانی<select id="organization" required></select></label><label>فرصت فروش<select id="opportunity" required></select></label></div></section>
<section class="panel"><h2>اقلام پیشنهاد</h2><p class="muted">برای هر قلم، نسخهٔ قیمت معتبر امروز و تعداد را انتخاب کنید.</p><div id="lines"></div><div class="actions"><button id="create" type="button">ساخت پیش‌نویس</button></div></section>
<section class="panel"><h2>پیش‌نویس‌های ثبت‌شده</h2><div id="drafts" class="cards"></div></section></main></body></html>"""

_SCRIPT = r"""(() => {
const $=id=>document.getElementById(id), workspace=$("workspace"), organization=$("organization"), opportunity=$("opportunity"), lines=$("lines"), drafts=$("drafts"), status=$("status"), params=new URLSearchParams(location.search);
let attached=[];
function msg(t,e=false){status.textContent=t||"";status.style.color=e?"#8b3b22":"#17613b"}
function opt(n,v,t){const o=document.createElement("option");o.value=v;o.textContent=t;n.appendChild(o)}
async function api(path,method="GET",body,scope=true){const h={Accept:"application/json"};if(scope)h["X-Workspace-ID"]=workspace.value;if(body!==undefined)h["Content-Type"]="application/json";const r=await fetch(path,{method,credentials:"same-origin",headers:h,body:body===undefined?undefined:JSON.stringify(body)});let d={};try{d=await r.json()}catch(_){}if(!r.ok)throw Error(d.detail||`عملیات ناموفق بود (${r.status}).`);return d}
async function loadOrgs(){const data=await api("/api/v1/system/opportunity-organization-units");organization.replaceChildren();opt(organization,"","واحد سازمانی را انتخاب کنید");data.forEach(x=>opt(organization,x.id,x.name));const wanted=data.find(x=>x.id===params.get("organization_unit_id"));organization.value=wanted?.id||data.find(x=>x.unit_type==="root")?.id||""}
async function loadOpps(){opportunity.replaceChildren();opt(opportunity,"","فرصت را انتخاب کنید");if(!organization.value)return;const d=await api(`/api/v1/crm/opportunities?organization_unit_id=${encodeURIComponent(organization.value)}&limit=100`);d.items.forEach(x=>opt(opportunity,x.id,x.name));if(d.items.some(x=>x.id===params.get("opportunity_id")))opportunity.value=params.get("opportunity_id");await loadOpportunity()}
async function loadOpportunity(){lines.replaceChildren();drafts.replaceChildren();attached=[];if(!opportunity.value)return;try{const data=await api(`/api/v1/crm/opportunities/${encodeURIComponent(opportunity.value)}/catalog-items`);attached=data.items||[];for(const item of attached)await addLine(item);await loadDrafts()}catch(e){msg(e.message,true)}}
async function addLine(item){const row=document.createElement("div");row.className="line";const title=document.createElement("strong");title.textContent=`${item.name} · ${item.code}`;const label=document.createElement("label");label.textContent="نسخهٔ قیمت";const prices=document.createElement("select");label.appendChild(prices);opt(prices,"","انتخاب قیمت");try{const d=await api(`/api/v1/crm/catalog/items/${encodeURIComponent(item.catalog_item_id)}/prices`);(d.items||[]).forEach(p=>{const o=document.createElement("option");o.value=String(p.version);o.textContent=`${p.amount} ${p.currency} · نسخه ${p.version} · ${p.effective_start||"—"} تا ${p.effective_end||"—"}`;prices.appendChild(o)})}catch(e){msg(e.message,true)}const quantityLabel=document.createElement("label");quantityLabel.textContent="تعداد";const quantity=document.createElement("input");quantity.type="number";quantity.min="0.000001";quantity.step="0.000001";quantity.value="1";quantityLabel.appendChild(quantity);row.append(title,label,quantityLabel);row.dataset.itemId=item.catalog_item_id;row.dataset.version=String(item.catalog_item_version);row.dataset.price=prices.id||"";row._price=prices;row._quantity=quantity;lines.appendChild(row)}
async function loadDrafts(){const data=await api(`/api/v1/crm/opportunities/${encodeURIComponent(opportunity.value)}/offer-drafts`);drafts.replaceChildren();(data.items||[]).forEach(x=>{const card=document.createElement("article");card.className="card";const head=document.createElement("strong");head.textContent=`پیش‌نویس · ${new Date(x.created_at).toLocaleString("fa-IR")}`;card.appendChild(head);Object.entries(x.totals_by_currency||{}).forEach(([currency,amount])=>{const p=document.createElement("p");p.className="totals";p.textContent=`جمع: ${amount} ${currency}`;card.appendChild(p)});(x.lines||[]).forEach(l=>{const p=document.createElement("p");p.className="muted";p.textContent=`${l.name} × ${l.quantity} = ${l.line_total} ${l.currency}`;card.appendChild(p)});drafts.appendChild(card)});if(!drafts.children.length){const p=document.createElement("p");p.className="muted";p.textContent="هنوز پیش‌نویسی ثبت نشده است.";drafts.appendChild(p)}}
$("create").addEventListener("click",async()=>{if(!opportunity.value)return msg("ابتدا فرصت فروش را انتخاب کنید.",true);const selected=[...lines.children].filter(r=>r._price.value);if(!selected.length)return msg("حداقل یک قلم با قیمت انتخاب کنید.",true);const payload={lines:selected.map(r=>({catalog_item_id:r.dataset.itemId,expected_catalog_version:Number(r.dataset.version),price_version:Number(r._price.value),quantity:r._quantity.value}))};try{await api(`/api/v1/crm/opportunities/${encodeURIComponent(opportunity.value)}/offer-drafts`,"POST",payload);await loadDrafts();msg("پیش‌نویس پیشنهاد ثبت شد.")}catch(e){msg(e.message,true)}});
workspace.addEventListener("change",async()=>{try{await loadOrgs();await loadOpps()}catch(e){msg(e.message,true)}});organization.addEventListener("change",()=>loadOpps().catch(e=>msg(e.message,true)));opportunity.addEventListener("change",()=>loadOpportunity());
async function init(){try{const spaces=await api("/api/v1/system/workspaces","GET",undefined,false);workspace.replaceChildren();opt(workspace,"","فضای کاری را انتخاب کنید");spaces.forEach(x=>opt(workspace,x.id,x.name));const wanted=spaces.find(x=>x.id===params.get("workspace_id"));workspace.value=wanted?.id||(spaces.length===1?spaces[0].id:"");if(workspace.value){await loadOrgs();await loadOpps()}}catch(e){msg(e.message,true)}}init();
})();"""


@router.get("/workspace/crm-offers", response_class=HTMLResponse)
async def crm_offer_workspace_page() -> HTMLResponse:
    return HTMLResponse(_PAGE, headers=_HEADERS)


@router.get("/assets/crm-offer-workspace.js")
async def crm_offer_workspace_script() -> Response:
    return Response(_SCRIPT, media_type="application/javascript", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
