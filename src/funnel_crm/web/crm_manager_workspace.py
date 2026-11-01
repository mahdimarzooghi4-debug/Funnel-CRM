"""Persian RTL shell and live data workspace for marketing managers."""
from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["CRM marketing manager workspace"], include_in_schema=False)

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
  <title>اتاق تصمیم‌گیری مدیر بازاریابی | فانل CRM</title>
  <style>
    :root{font-family:Tahoma,Arial,sans-serif;color:#14253a;background:#f5f7fb;font-synthesis:none}
    *{box-sizing:border-box}body{margin:0}.app{min-height:100vh;display:grid;grid-template-columns:250px minmax(0,1fr)}
    aside{background:#fff;border-left:1px solid #e5eaf1;padding:22px 14px;position:sticky;top:0;height:100vh;overflow:auto}
    .brand{display:flex;align-items:center;gap:10px;padding:0 10px 22px;color:#14253a;font-weight:800;font-size:20px}
    .mark{width:31px;height:31px;border-radius:10px;background:linear-gradient(145deg,#0c587e,#25b7a6);display:grid;place-items:center;color:#fff}
    .nav-label{padding:12px 11px 7px;color:#8290a0;font-size:11px;font-weight:700}
    nav{display:grid;gap:4px}.nav-item{display:flex;align-items:center;gap:10px;width:100%;text-decoration:none;text-align:right;border:0;border-radius:9px;background:transparent;color:#4c5b6d;padding:10px 11px;min-height:39px;font:inherit;font-size:12px;cursor:pointer}
    .nav-item:hover{background:#f4f8fb;color:#174e70}.nav-item[aria-current="page"]{background:#e8f4f8;color:#125779;font-weight:700}
    .nav-icon{width:19px;text-align:center;color:#52728a;font-size:15px;flex:0 0 19px}
    .side-foot{border-top:1px solid #edf0f4;margin-top:18px;padding:14px 10px;color:#768394;font-size:11px;line-height:1.8}
    main{min-width:0;padding:22px clamp(16px,3vw,42px) 48px}.topbar{display:flex;align-items:center;gap:12px;margin-bottom:24px}
    .search{flex:1;max-width:430px;position:relative}.search input{width:100%;height:42px;border:1px solid #e1e7ed;border-radius:10px;padding:0 38px 0 12px;background:#fff;font:inherit}
    .search span{position:absolute;right:13px;top:10px;color:#7d8b99}.top-spacer{flex:1}.profile{display:flex;align-items:center;gap:9px;color:#33465c;font-size:12px}
    .avatar{width:35px;height:35px;border-radius:50%;background:#e4f1f2;color:#127078;display:grid;place-items:center;font-weight:700}
    .header-row{display:flex;align-items:flex-start;justify-content:space-between;gap:18px;margin-bottom:20px}.title h1{font-size:25px;margin:0 0 8px}.title p{margin:0;color:#718092;font-size:13px;line-height:1.8}
    .filters{display:flex;gap:9px;flex-wrap:wrap;justify-content:flex-end}.filters label{display:grid;gap:5px;color:#8290a0;font-size:10px}
    select,input[type=date]{height:39px;border:1px solid #dfe6ed;background:#fff;border-radius:9px;padding:0 10px;color:#33465c;font:inherit;font-size:12px;min-width:134px}
    button{font:inherit;cursor:pointer}.primary{border:0;background:#126b91;color:#fff;border-radius:9px;padding:0 16px;height:39px;font-size:12px;font-weight:700}.primary:hover{background:#0c5678}
    #status{min-height:21px;color:#718092;font-size:12px;margin:0 0 10px}#status.error{color:#a74137}
    .notice{background:#fff8e9;border:1px solid #f2dfb8;border-right:3px solid #e6a337;color:#725218;padding:12px 15px;border-radius:10px;font-size:12px;line-height:1.8;margin:12px 0 16px}
    .kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:14px}
    .card{background:#fff;border:1px solid #e5eaf0;border-radius:12px;padding:16px;box-shadow:0 4px 14px #1c334408;min-width:0}
    .kpi-label{color:#657487;font-size:12px}.kpi-value{font-size:22px;font-weight:800;color:#1a334c;margin:12px 0 5px}.kpi-meta{font-size:11px;color:#8290a0;line-height:1.7}
    .grid-main{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(300px,1fr);gap:14px;margin-bottom:14px}
    .card-heading{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:13px}.card-heading h2{font-size:15px;margin:0}.card-heading small{color:#8894a2;font-size:10px}
    .chart{display:grid;gap:11px}.chart-row{display:grid;grid-template-columns:minmax(92px,140px) minmax(0,1fr) 90px;align-items:center;gap:9px;font-size:11px}
    .bar-track{height:9px;border-radius:99px;background:#edf2f6;overflow:hidden}.bar{height:100%;background:linear-gradient(90deg,#24b5a5,#17658e);border-radius:99px;min-width:2px}
    .bar-value{text-align:left;color:#526477;font-variant-numeric:tabular-nums}
    .funnel{display:grid;gap:9px}.funnel-row{display:grid;grid-template-columns:88px minmax(0,1fr) 68px;gap:9px;align-items:center;font-size:11px}
    .funnel-row strong{font-size:12px}.funnel-track{height:24px;background:#eef3f6;border-radius:6px;overflow:hidden}.funnel-fill{height:100%;background:#2ca8a7;border-radius:6px;min-width:2px}
    .table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;min-width:520px;font-size:11px}th,td{text-align:right;padding:10px 8px;border-bottom:1px solid #eef1f4}th{background:#f8fafc;color:#728092;font-weight:600}td{color:#33465c}
    .signals{display:grid;gap:9px}.signal{border:1px solid #f0e4cf;background:#fffaf1;border-radius:9px;padding:11px}.signal strong{display:block;font-size:12px;color:#634818;margin-bottom:5px}.signal p{font-size:11px;color:#7b6a4a;line-height:1.8;margin:0}
    .empty{border:1px dashed #d4dde6;border-radius:9px;padding:16px;color:#7b8998;font-size:12px;text-align:center;line-height:1.8}
    .lower-grid{display:grid;grid-template-columns:1.4fr 1fr;gap:14px}.link-row{display:flex;flex-wrap:wrap;gap:8px}.module-link{border:1px solid #dfe7ee;background:#fff;color:#27536d;text-decoration:none;border-radius:8px;padding:9px 12px;font-size:11px}
    .module-link:hover{background:#f2f8fa}.coverage{height:9px;background:#edf1f4;border-radius:9px;overflow:hidden;margin:10px 0}.coverage span{display:block;height:100%;width:0;background:#1aa38f;border-radius:9px;transition:width .3s}
    .footnote{color:#8a96a3;font-size:10px;line-height:1.8;margin-top:12px}
    @media(max-width:1050px){.app{grid-template-columns:210px minmax(0,1fr)}.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.header-row{display:block}.filters{justify-content:flex-start;margin-top:14px}}
    @media(max-width:760px){.app{display:block}aside{position:relative;height:auto;border-left:0;border-bottom:1px solid #e5eaf1;padding:12px}.brand{padding-bottom:8px}.nav-label,.side-foot{display:none}nav{display:flex;overflow:auto;padding-bottom:3px}.nav-item{white-space:nowrap;width:auto;flex:0 0 auto;padding:9px}.topbar{margin-bottom:18px}.grid-main,.lower-grid{grid-template-columns:1fr}.profile span:not(.avatar){display:none}}
    @media(max-width:480px){main{padding:15px 12px 32px}.kpis{gap:8px}.card{padding:12px}.kpi-value{font-size:18px}.filters{display:grid;grid-template-columns:1fr 1fr}.filters label{min-width:0}select,input[type=date]{min-width:0;width:100%}.primary{width:100%}.chart-row{grid-template-columns:85px minmax(0,1fr) 66px}.funnel-row{grid-template-columns:75px minmax(0,1fr) 58px}}
  </style>
  <script src="/assets/crm-manager-home.js" defer></script>
</head>
<body>
<div class="app">
  <aside>
    <div class="brand"><span class="mark">ف</span><span>فانل CRM</span></div>
    <div class="nav-label">میزکار</div>
    <nav aria-label="ماژول‌های CRM">
      <a class="nav-item" href="/workspace/marketing-manager" aria-current="page"><span class="nav-icon">▦</span>میزکار و داشبورد نقش‌محور</a>
      <div class="nav-label">ماژول‌ها</div>
      <a class="nav-item" href="/workspace/crm-market-research"><span class="nav-icon">⌕</span>تحقیق و شناخت بازار</a>
      <a class="nav-item" href="/workspace/crm-marketing-planning"><span class="nav-icon">◎</span>استراتژی و برنامه‌ریزی بازاریابی</a>
      <a class="nav-item" href="/workspace/crm-catalog"><span class="nav-icon">◇</span>محصول، قیمت و پیشنهاد فروش</a>
      <a class="nav-item" href="/workspace/crm-campaigns"><span class="nav-icon">◉</span>کمپین و محتوا</a>
      <a class="nav-item" href="/workspace/crm-channels"><span class="nav-icon">⌘</span>کانال‌ها و شرکای فروش</a>
      <a class="nav-item" href="/workspace/crm-sales"><span class="nav-icon">↗</span>مدیریت فروش و درآمد</a>
      <a class="nav-item" href="/workspace/crm-marketing-operations"><span class="nav-icon">☷</span>عملیات و منابع بازاریابی</a>
      <a class="nav-item" href="/workspace/crm-analytics"><span class="nav-icon">◷</span>تحلیل و هوش تجاری</a>
      <a class="nav-item" href="/workspace/crm-ai-assistant"><span class="nav-icon">✦</span>دستیار هوشمند مدیر بازاریابی</a>
      <a class="nav-item" href="/workspace/crm-automation"><span class="nav-icon">⤳</span>اتوماسیون و گردش‌کار</a>
      <a class="nav-item" href="/workspace/crm-customer-lifecycle"><span class="nav-icon">♡</span>چرخه عمر و تجربه مشتری</a>
      <a class="nav-item" href="/workspace/crm-learning"><span class="nav-icon">⌁</span>یادگیری و بهبود مستمر</a>
      <a class="nav-item" href="/workspace/crm-local-marketing"><span class="nav-icon">⌖</span>شعب و بازاریابی محلی</a>
      <a class="nav-item" href="/workspace/crm-brand"><span class="nav-icon">◈</span>برند و اعتبار بازار</a>
      <a class="nav-item" href="/workspace/crm-admin"><span class="nav-icon">⚙</span>مدیریت، امنیت و اتصال</a>
    </nav>
    <div class="side-foot">CRM مستقل و قابل استفاده است.<br>اتصال محصولات اجرایی فانل اختیاری است.</div>
  </aside>
  <main>
    <div class="topbar">
      <label class="search"><span>⌕</span><input aria-label="جست‌وجوی سراسری" placeholder="جست‌وجوی مشتری، کمپین، فرصت یا فعالیت"></label>
      <div class="top-spacer"></div><div class="profile"><span class="avatar">م</span><span>اتاق تصمیم‌گیری</span></div>
    </div>
    <section class="header-row">
      <div class="title"><h1>اتاق تصمیم‌گیری مدیر بازاریابی و فروش</h1><p>هدف و عملکرد واقعی، بودجه، فرصت‌ها و اقدام‌های نیازمند پیگیری</p></div>
      <div class="filters">
        <label>فضای کاری<select id="workspace-id"><option value="">در حال دریافت…</option></select></label>
        <label>از تاریخ<input id="period-start" type="date"></label>
        <label>تا تاریخ<input id="period-end" type="date"></label>
        <button class="primary" id="refresh" type="button">به‌روزرسانی</button>
      </div>
    </section>
    <p id="status" role="status" aria-live="polite">در حال آماده‌سازی میزکار…</p>
    <div id="data-warning" class="notice" hidden></div>
    <section class="kpis" aria-label="شاخص‌های اصلی">
      <article class="card"><div class="kpi-label">فروش منتسب</div><div class="kpi-value" id="revenue-value">—</div><div class="kpi-meta" id="revenue-meta">در انتظار داده</div></article>
      <article class="card"><div class="kpi-label">هزینهٔ بازاریابی</div><div class="kpi-value" id="spend-value">—</div><div class="kpi-meta" id="spend-meta">در انتظار داده</div></article>
      <article class="card"><div class="kpi-label">کمپین‌های گزارش</div><div class="kpi-value" id="campaign-count">—</div><div class="kpi-meta" id="measured-count">در انتظار داده</div></article>
      <article class="card"><div class="kpi-label">پوشش داده</div><div class="kpi-value" id="coverage-value">—</div><div class="coverage"><span id="coverage-bar"></span></div><div class="kpi-meta" id="coverage-meta">تعریف: روزهای دارای داده به روزهای مورد انتظار</div></article>
    </section>
    <section class="grid-main">
      <article class="card">
        <div class="card-heading"><h2>عملکرد کانال‌ها</h2><small id="channels-meta">منبع: گزارش دوره</small></div>
        <div class="chart" id="channel-chart"><div class="empty">پس از انتخاب فضای کاری، داده‌های کانال نمایش داده می‌شود.</div></div>
      </article>
      <article class="card">
        <div class="card-heading"><h2>قیف قابل‌تنظیم مشتری</h2><small>بر پایهٔ دادهٔ ثبت‌شده</small></div>
        <div class="funnel" id="funnel"><div class="empty">دادهٔ مراحل مشتری برای بازهٔ انتخابی موجود نیست.</div></div>
      </article>
    </section>
    <section class="lower-grid">
      <article class="card">
        <div class="card-heading"><h2>هشدارها و فرصت‌های قابل بررسی</h2><small>پیشنهاد، نه اجرای خودکار</small></div>
        <div class="signals" id="signals"><div class="empty">هنوز هشداری برای نمایش دریافت نشده است.</div></div>
      </article>
      <article class="card">
        <div class="card-heading"><h2>ریتم بودجهٔ کمپین‌ها</h2><small id="pacing-meta">انتخاب بازه برای بررسی</small></div>
        <div class="signals" id="pacing"><div class="empty">گزارش ریتم بودجه پس از دریافت داده نمایش داده می‌شود.</div></div>
      </article>
    </section>
    <section class="card" style="margin-top:14px">
      <div class="card-heading"><h2>دسترسی سریع به میزکارهای موجود</h2><small>بر اساس کد فعلی مخزن</small></div>
      <div class="link-row">
        <a class="module-link" href="/workspace/crm-catalog">کاتالوگ محصول و خدمت</a>
        <a class="module-link" href="/workspace/crm-offers">پیشنهادهای فروش</a>
        <a class="module-link" href="/workspace/crm-offer-plans">طرح پیشنهادهای بازاریابی</a>
        <a class="module-link" href="/workspace/budget-scenario-comparison">مقایسهٔ سناریوهای بودجه</a>
        <a class="module-link" href="/workspace/crm-activity-capture">ثبت فعالیت میدانی</a>
        <a class="module-link" href="/workspace/crm-commissions">کمیسیون فروش</a>
      </div>
      <p class="footnote">شاخص‌ها فقط بر اساس دادهٔ موجود نمایش داده می‌شوند. دادهٔ ناقص یا قدیمی به‌عنوان نتیجهٔ قطعی تفسیر نمی‌شود. محصولات اجرایی فانل مستقل و انتخابی هستند.</p>
    </section>
  </main>
</div>
</body>
</html>"""

_SCRIPT = r"""(() => {
  const $ = (id) => document.getElementById(id);
  const workspace = $("workspace-id");
  const status = $("status");
  const warn = $("data-warning");
  const params = new URLSearchParams(window.location.search);
  const faNumber = new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 1 });
  const money = new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 0 });
  const dateValue = (date) => date.toISOString().slice(0, 10);
  function setStatus(message, error = false) { status.textContent = message; status.classList.toggle("error", error); }
  function append(parent, tag, text, className = "") {
    const node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = text;
    parent.appendChild(node);
    return node;
  }
  function currencyText(values) {
    const entries = Object.entries(values || {});
    if (!entries.length) return "داده‌ای ثبت نشده";
    return entries.map(([currency, value]) => money.format(Number(value || 0)) + " " + currency).join(" · ");
  }
  async function api(path, needsWorkspace = true) {
    const headers = { Accept: "application/json" };
    if (needsWorkspace) headers["X-Workspace-ID"] = workspace.value;
    const response = await fetch(path, { credentials: "same-origin", headers });
    let data = {};
    try { data = await response.json(); } catch (_) {}
    if (!response.ok) throw new Error(data.detail || "دریافت داده ناموفق بود (" + response.status + ").");
    return data;
  }
  function isoToday() { return dateValue(new Date()); }
  function setDefaultDates() {
    const end = new Date();
    const start = new Date(end);
    start.setDate(start.getDate() - 29);
    $("period-start").value = dateValue(start);
    $("period-end").value = dateValue(end);
  }
  function renderChannels(items) {
    const host = $("channel-chart");
    host.replaceChildren();
    const rows = (items || []).slice(0, 8);
    if (!rows.length) { append(host, "div", "برای این بازه دادهٔ کانالی ثبت نشده است.", "empty"); return; }
    const max = Math.max(1, ...rows.map((row) => Object.values(row.actual_spend_by_currency || {}).reduce((a, b) => a + Number(b || 0), 0)));
    rows.forEach((row) => {
      const line = document.createElement("div"); line.className = "chart-row";
      append(line, "span", row.channel || "بدون نام کانال");
      const track = document.createElement("div"); track.className = "bar-track";
      const bar = document.createElement("div"); bar.className = "bar";
      const amount = Object.values(row.actual_spend_by_currency || {}).reduce((a, b) => a + Number(b || 0), 0);
      bar.style.width = Math.max(2, Math.round(amount / max * 100)) + "%"; track.appendChild(bar); line.appendChild(track);
      append(line, "span", currencyText(row.actual_spend_by_currency), "bar-value");
      host.appendChild(line);
    });
  }
  function renderFunnel(totals) {
    const host = $("funnel"); host.replaceChildren();
    const steps = [
      ["پاسخ‌ها", totals.responses],
      ["سرنخ‌ها", totals.leads],
      ["تبدیل‌ها", totals.conversions]
    ].filter((step) => step[1] !== null && step[1] !== undefined);
    if (!steps.length) { append(host, "div", "برای این بازه دادهٔ مراحل مشتری ثبت نشده است؛ صفر فرض نشده.", "empty"); return; }
    const max = Math.max(1, ...steps.map((step) => Number(step[1])));
    steps.forEach(([name, value]) => {
      const line = document.createElement("div"); line.className = "funnel-row";
      append(line, "span", name);
      const track = document.createElement("div"); track.className = "funnel-track";
      const fill = document.createElement("div"); fill.className = "funnel-fill";
      fill.style.width = Math.max(2, Math.round(Number(value) / max * 100)) + "%"; track.appendChild(fill); line.appendChild(track);
      append(line, "strong", faNumber.format(Number(value)));
      host.appendChild(line);
    });
  }
  function renderSignals(signals) {
    const host = $("signals"); host.replaceChildren();
    const rows = (signals || []).slice(0, 5);
    if (!rows.length) { append(host, "div", "هشدار تأییدشده‌ای برای این بازه دریافت نشد.", "empty"); return; }
    rows.forEach((signal) => {
      const card = document.createElement("article"); card.className = "signal";
      append(card, "strong", (signal.priority === "high" ? "اولویت بالا · " : "") + (signal.metric_key || "نیازمند بررسی"));
      append(card, "p", signal.recommended_action || "جزئیات اقدام برای این مورد ثبت نشده است.");
      host.appendChild(card);
    });
  }
  function renderPacing(report) {
    const host = $("pacing"); host.replaceChildren();
    $("pacing-meta").textContent = report.items.length + " کمپین · " + report.as_of;
    const rows = report.items.filter((item) => item.pacing_status === "ahead_of_pace" || item.pacing_status === "behind_pace").slice(0, 4);
    if (!rows.length) { append(host, "div", "برای این دوره موردی با ریتم قابل‌محاسبه دریافت نشد.", "empty"); return; }
    rows.forEach((item) => {
      const card = document.createElement("article"); card.className = "signal";
      const label = item.pacing_status === "behind_pace" ? "عقب‌تر از ریتم" : "جلوتر از ریتم";
      append(card, "strong", (item.campaign_name || "کمپین") + " · " + label);
      append(card, "p", "هزینهٔ ثبت‌شده: " + (item.actual_spend_in_budget_currency || "نامشخص") + " " + (item.budget_currency || "") + "؛ اختلاف با برنامه: " + (item.variance_percent === null ? "نامشخص" : faNumber.format(item.variance_percent) + "٪"));
      host.appendChild(card);
    });
  }
  async function loadDashboard() {
    if (!workspace.value) return;
    const start = $("period-start").value;
    const end = $("period-end").value;
    if (!start || !end || start > end) { setStatus("بازهٔ زمانی را بررسی کنید.", true); return; }
    setStatus("در حال دریافت گزارش و شواهد…");
    warn.hidden = true;
    const query = "?period_start=" + encodeURIComponent(start) + "&period_end=" + encodeURIComponent(end);
    try {
      const report = await api("/api/v1/crm/analytics/marketing-manager/campaigns" + query);
      const p = report.performance || {};
      const quality = report.data_quality || {};
      $("revenue-value").textContent = currencyText(p.attributed_revenue_by_currency);
      $("revenue-meta").textContent = "در بازهٔ انتخابی · گزارش نسخهٔ " + (report.report_definition_version || "—");
      $("spend-value").textContent = currencyText(p.actual_spend_by_currency);
      $("spend-meta").textContent = "هزینهٔ مشاهده‌شده؛ بدون تبدیل میان ارزها";
      $("campaign-count").textContent = faNumber.format(p.campaign_count || 0);
      $("measured-count").textContent = faNumber.format(p.measured_campaign_count || 0) + " کمپین دارای سنجش";
      const rate = quality.expected_campaign_days ? Math.round(quality.covered_campaign_days / quality.expected_campaign_days * 100) : null;
      $("coverage-value").textContent = rate === null ? "نامعلوم" : faNumber.format(rate) + "٪";
      $("coverage-bar").style.width = (rate === null ? 0 : Math.min(100, Math.max(0, rate))) + "%";
      $("coverage-meta").textContent = quality.expected_campaign_days ? faNumber.format(quality.covered_campaign_days) + " از " + faNumber.format(quality.expected_campaign_days) + " روز کمپین پوشش داده شده" : "مبنای مقایسه در این بازه موجود نیست";
      renderChannels(report.channel_performance);
      renderFunnel(p.totals || {});
      renderSignals((report.target_attainment || {}).manager_signals || []);
      const pacing = await api("/api/v1/crm/analytics/marketing-manager/campaigns/budget-pacing?period_start=" + encodeURIComponent(start) + "&as_of=" + encodeURIComponent(end));
      renderPacing(pacing);
      const warnings = [];
      if (p.truncated) warnings.push("فهرست کمپین‌ها به سقف گزارش رسیده است.");
      if (quality.truncated) warnings.push("گزارش کیفیت داده محدود شده است.");
      if (report.target_attainment && report.target_attainment.manager_signals_truncated) warnings.push("فهرست هشدارها کامل نیست.");
      if (warnings.length) { warn.textContent = warnings.join(" "); warn.hidden = false; }
      setStatus("گزارش به‌روز شد · " + new Date(report.generated_at).toLocaleString("fa-IR"));
    } catch (error) { setStatus(error.message, true); }
  }
  async function init() {
    setDefaultDates();
    try {
      const spaces = await api("/api/v1/system/workspaces", false);
      workspace.replaceChildren();
      const first = document.createElement("option"); first.value = ""; first.textContent = "فضای کاری را انتخاب کنید"; workspace.appendChild(first);
      spaces.forEach((space) => {
        const option = document.createElement("option"); option.value = space.id; option.textContent = space.name; workspace.appendChild(option);
      });
      const requested = spaces.find((space) => space.id === params.get("workspace_id"));
      workspace.value = requested ? requested.id : (spaces.length === 1 ? spaces[0].id : "");
      if (workspace.value) await loadDashboard();
      else setStatus("فضای کاری را انتخاب کنید تا گزارش همان کسب‌وکار بارگذاری شود.");
    } catch (error) { setStatus(error.message, true); }
  }
  $("refresh").addEventListener("click", () => loadDashboard());
  workspace.addEventListener("change", () => loadDashboard());
  $("period-start").addEventListener("change", () => { if (workspace.value) loadDashboard(); });
  $("period-end").addEventListener("change", () => { if (workspace.value) loadDashboard(); });
  init();
})();"""

@router.get("/workspace/marketing-manager", response_class=HTMLResponse)
async def marketing_manager_workspace_page() -> HTMLResponse:
    return HTMLResponse(_PAGE, headers=_HEADERS)


@router.get("/assets/crm-manager-home.js")
async def marketing_manager_workspace_script() -> Response:
    return Response(
        _SCRIPT,
        media_type="application/javascript",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
