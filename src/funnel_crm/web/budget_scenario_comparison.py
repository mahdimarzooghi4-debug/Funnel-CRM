"""Persian, read-only browser workspace for budget-scenario evidence."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response

router = APIRouter(tags=["CRM budget scenario workspace"], include_in_schema=False)

_PAGE = """<!doctype html>
<html lang="fa" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>مقایسهٔ سناریوهای بودجه | Funnel CRM</title>
  <style>
    :root { color-scheme: light; font-family: Tahoma, Arial, sans-serif; background: #f4f7fb; color: #182638; }
    * { box-sizing: border-box; }
    body { margin: 0; }
    header { background: #12334a; color: #fff; padding: 22px max(20px, calc((100vw - 1240px) / 2)); }
    header strong { font-size: 14px; letter-spacing: .04em; }
    main { max-width: 1240px; margin: 28px auto; padding: 0 20px 56px; }
    h1 { margin: 0 0 8px; font-size: clamp(24px, 4vw, 34px); }
    h2 { margin: 0 0 16px; font-size: 19px; }
    p { line-height: 1.8; }
    .intro { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin-bottom: 22px; }
    .intro p { max-width: 760px; margin: 0; color: #526477; }
    .badge { white-space: nowrap; border-radius: 999px; padding: 8px 12px; background: #e5f4ec; color: #17613b; font-size: 13px; }
    .panel { background: #fff; border: 1px solid #e1e8ef; border-radius: 14px; padding: 22px; margin: 18px 0; box-shadow: 0 5px 20px #142d4210; }
    .grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }
    label { display: grid; gap: 7px; color: #405367; font-size: 13px; }
    input, select { width: 100%; min-height: 42px; border: 1px solid #cbd6e0; border-radius: 8px; padding: 9px 11px; color: #182638; background: #fff; font: inherit; }
    button { min-height: 42px; border: 0; border-radius: 8px; padding: 9px 16px; background: #1578a8; color: #fff; font: inherit; font-weight: 700; cursor: pointer; }
    button:hover { background: #0e648f; }
    button:disabled { opacity: .55; cursor: wait; }
    .actions { display: flex; align-items: center; gap: 14px; margin-top: 16px; }
    .hint, .muted { color: #687b8d; font-size: 13px; line-height: 1.8; }
    #status { min-height: 24px; margin: 12px 0 0; color: #8b3b22; }
    #scenario-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 10px; }
    .scenario-option { display: flex; align-items: flex-start; gap: 10px; border: 1px solid #dbe4ec; border-radius: 10px; padding: 12px; cursor: pointer; }
    .scenario-option input { width: 18px; min-height: 18px; margin: 2px 0 0; accent-color: #1578a8; }
    .scenario-option strong { display: block; color: #20364b; }
    .scenario-option small { display: block; color: #687b8d; margin-top: 4px; }
    #results[hidden], #scenario-panel[hidden] { display: none; }
    .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 14px; }
    .scenario-card { border: 1px solid #dce5ed; border-radius: 12px; padding: 16px; }
    .scenario-card h3 { margin: 0 0 10px; font-size: 17px; }
    .currency-card { border-top: 1px solid #edf1f5; padding-top: 10px; margin-top: 10px; }
    .currency-card strong { display: block; margin-bottom: 7px; color: #17658b; }
    .facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px 12px; margin: 0; }
    .facts dt { color: #687b8d; font-size: 12px; }
    .facts dd { margin: 3px 0 0; font-weight: 700; direction: ltr; text-align: right; }
    .table-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; min-width: 850px; }
    th, td { padding: 12px 10px; text-align: right; vertical-align: top; border-bottom: 1px solid #e9eef3; }
    th { color: #526477; background: #f8fafc; font-size: 13px; }
    td { line-height: 1.75; }
    .allocation { display: block; padding: 7px 0; border-bottom: 1px dashed #e0e7ed; }
    .allocation:last-child { border-bottom: 0; }
    .allocation strong { display: block; }
    .allocation small { color: #687b8d; }
    .notice { background: #f1f7fb; border-right: 3px solid #3594bd; padding: 12px 14px; color: #405367; border-radius: 6px; font-size: 13px; line-height: 1.8; }
    .empty { padding: 18px; border: 1px dashed #cbd6e0; border-radius: 10px; color: #687b8d; text-align: center; }
    @media (max-width: 800px) { .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .intro { display: block; } .badge { display: inline-block; margin-top: 12px; } }
    @media (max-width: 520px) { main { margin-top: 18px; padding-right: 12px; padding-left: 12px; } .panel { padding: 16px; } .grid { grid-template-columns: 1fr; } .actions { align-items: stretch; flex-direction: column; } }
  </style>
  <script src="/assets/budget-scenario-comparison.js" defer></script>
</head>
<body>
  <header><strong>FUNNEL CRM</strong></header>
  <main>
    <div class="intro">
      <div>
        <h1>مقایسهٔ سناریوهای بودجه</h1>
        <p>تخصیص‌های پیشنهادی را کنار هزینه و نتایج ثبت‌شدهٔ همان کمپین‌ها ببینید تا تصمیم را بر پایهٔ شواهد موجود بگیرید.</p>
      </div>
      <span class="badge">گزارش واقعی؛ بدون پیش‌بینی</span>
    </div>
    <section class="panel" aria-labelledby="scope-title">
      <h2 id="scope-title">فضای کاری و بازهٔ گزارش</h2>
      <div class="grid">
        <label for="workspace-id">فضای کاری
          <select id="workspace-id" name="workspace_id" required><option value="">در حال بارگذاری…</option></select>
        </label>
        <label for="organization-id">واحد سازمانی مجاز
          <select id="organization-id" name="organization_unit_id" required><option value="">ابتدا فضای کاری را انتخاب کنید</option></select>
        </label>
        <label for="period-start">از تاریخ
          <input id="period-start" type="date" required>
        </label>
        <label for="period-end">تا تاریخ
          <input id="period-end" type="date" required>
        </label>
      </div>
      <div class="actions">
        <button id="load-scenarios" type="button">بارگذاری سناریوها</button>
        <span class="hint">فهرست‌ها بر اساس عضویت فعال و مجوزهای مشاهدهٔ کمپین و سناریوی بودجهٔ حساب شما بارگذاری می‌شوند.</span>
      </div>
      <p id="status" role="status" aria-live="polite"></p>
    </section>
    <section class="panel" id="scenario-panel" hidden aria-labelledby="scenario-title">
      <h2 id="scenario-title">سناریوهای قابل مقایسه</h2>
      <p class="muted">بین ۲ تا ۵ سناریوی پیش‌نویس را انتخاب کنید. سناریوها باید برای مجموعهٔ یکسانی از کمپین‌ها تعریف شده باشند.</p>
      <div id="scenario-list"></div>
      <div class="actions">
        <button id="compare" type="button">نمایش مقایسه</button>
        <span id="selection-count" class="hint"></span>
      </div>
    </section>
    <section class="panel" id="results" hidden aria-labelledby="results-title">
      <h2 id="results-title">خلاصهٔ بودجه و شواهد واقعی</h2>
      <div class="actions"><button id="export-csv" type="button">دریافت فایل CSV</button><span class="hint">فایل شامل خلاصهٔ سناریوها و شواهد کمپین همین بازه است.</span></div>
      <p class="notice">نتایج ثبت‌شده برای کمپین‌های مشترک نمایش داده می‌شوند و به یک سناریوی بودجه نسبت داده نمی‌شوند. جمع واریانس فقط شامل هزینه‌های ثبت‌شده با ارز همسان است؛ ارزها تبدیل نمی‌شوند و نبود رکورد به معنی عملکرد صفر نیست.</p>
      <p class="muted">پیوند صفحه محدوده، بازه و سناریوهای انتخاب‌شده را نگه می‌دارد؛ با بازکردن دوباره، داده‌ها با مجوز فعلی از سامانه بازخوانی می‌شوند.</p>
      <h2>پوشش شواهد این گزارش</h2>
      <p class="muted">این شمارنده‌ها میزان ثبت داده را نشان می‌دهند، نه عملکرد بهتر یا بدتر را.</p>
      <div id="evidence-coverage" class="cards" aria-live="polite"></div>
      <h2 style="margin-top:24px">پوشش شواهد به تفکیک کانال</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th scope="col">کانال</th><th scope="col">کمپین</th><th scope="col">هزینهٔ ثبت‌شده / پوشش</th><th scope="col">دادهٔ سرنخ / پوشش</th><th scope="col">دادهٔ تبدیل / پوشش</th></tr></thead>
          <tbody id="channel-coverage"></tbody>
        </table>
      </div>
      <h2 style="margin-top:24px">فهرست کمپین‌های نیازمند تکمیل داده</h2>
      <p class="muted">این فهرست فقط مواردی را نشان می‌دهد که دادهٔ هزینه، سرنخ یا تبدیل در گزارش موجود نیست.</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th scope="col">کمپین</th><th scope="col">کانال</th><th scope="col">دادهٔ ثبت‌نشده</th></tr></thead>
          <tbody id="evidence-gaps"></tbody>
        </table>
      </div>
      <h2 style="margin-top:28px">مقایسه با بازهٔ قبلی هم‌طول</h2>
      <p id="period-comparison-period" class="muted"></p>
      <p class="muted">تغییرها توصیفی هستند و انتساب علّی به سناریوها انجام نمی‌شود. ارزها جداگانه مقایسه می‌شوند.</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th scope="col">شاخص</th><th scope="col">بازهٔ قبلی</th><th scope="col">بازهٔ جاری</th><th scope="col">تغییر</th><th scope="col">درصد تغییر</th></tr></thead>
          <tbody id="period-comparison"></tbody>
        </table>
      </div>
      <h3 style="margin-top:22px">مقایسهٔ تغییرها به تفکیک کانال</h3>
      <div class="table-wrap">
        <table>
          <thead><tr><th scope="col">کانال</th><th scope="col">شاخص</th><th scope="col">بازهٔ قبلی</th><th scope="col">بازهٔ جاری</th><th scope="col">تغییر</th><th scope="col">درصد تغییر</th></tr></thead>
          <tbody id="channel-period-comparison"></tbody>
        </table>
      </div>
      <h3 style="margin-top:22px">هزینهٔ ثبت‌شده به‌ازای سرنخ و تبدیل</h3>
      <p class="muted">این نسبت فقط از کمپین‌هایی محاسبه می‌شود که هزینه و شاخص مربوط را ثبت کرده‌اند و هزینه‌شان یک ارز واحد دارد. کمپین‌های چندارزی برای جلوگیری از نسبت‌دهی مبهم کنار گذاشته می‌شوند. این شاخص ROI نیست.</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th scope="col">کانال</th><th scope="col">شاخص</th><th scope="col">ارز</th><th scope="col">هزینهٔ واحد قبلی</th><th scope="col">هزینهٔ واحد جاری</th><th scope="col">درصد تغییر</th><th scope="col">مجموع شاخص جاری</th><th scope="col">کمپین‌های جاری</th></tr></thead>
          <tbody id="unit-cost-comparison"></tbody>
        </table>
      </div>
      <h3 style="margin-top:22px">مقایسهٔ عملکرد بر اساس هدف بازاریابی</h3>
      <p class="muted">جمع سرنخ و تبدیل ثبت‌شده برای هر هدف و کانال را در دو بازه ببینید. پوشش کنار هر مقدار تعداد کمپین‌های دارای مشاهده را از کل کمپین‌های همان گروه جدا می‌کند؛ این تغییرها توصیفی‌اند.</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th scope="col">هدف بازاریابی</th><th scope="col">کانال</th><th scope="col">شاخص</th><th scope="col">جمع بازهٔ قبلی</th><th scope="col">جمع بازهٔ جاری</th><th scope="col">تغییر</th><th scope="col">پوشش قبلی</th><th scope="col">پوشش جاری</th></tr></thead>
          <tbody id="objective-performance"></tbody>
        </table>
      </div>
      <h3 style="margin-top:22px">تطبیق بودجه به تفکیک هدف بازاریابی</h3>
      <p class="muted">بودجهٔ برنامه‌ریزی‌شده و هزینهٔ واقعی هم‌ارز را به تفکیک هدف، سناریو و ارز ببینید. سهم بودجه، ترکیب تخصیص همان سناریو را نشان می‌دهد؛ پوشش، تعداد تخصیص‌های قابل‌مقایسه را. ارزها تبدیل نمی‌شوند.</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th scope="col">هدف بازاریابی</th><th scope="col">سناریو</th><th scope="col">ارز</th><th scope="col">بودجهٔ برنامه‌ریزی‌شده</th><th scope="col">بودجهٔ تخصیص‌های قابل‌مقایسه</th><th scope="col">هزینهٔ واقعی هم‌ارز</th><th scope="col">واریانس</th><th scope="col">پوشش تخصیص</th><th scope="col">سهم از بودجهٔ سناریو</th></tr></thead>
          <tbody id="objective-budget-reconciliation"></tbody>
        </table>
      </div>
      <h3 style="margin-top:22px">بودجهٔ سناریو در کنار شواهد تاریخی هدف</h3>
      <p class="muted">برای هر هدف و ارز، بودجهٔ هر سناریو را کنار هزینهٔ واحد محاسبه‌شده از داده‌های ثبت‌شدهٔ همین بازه ببینید. این کنارهم‌گذاری نتیجهٔ آینده را پیش‌بینی نمی‌کند و هزینه را به سناریو نسبت نمی‌دهد.</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th scope="col">هدف بازاریابی</th><th scope="col">سناریو</th><th scope="col">ارز</th><th scope="col">بودجهٔ برنامه‌ریزی‌شده</th><th scope="col">سهم از بودجه</th><th scope="col">هزینهٔ هر سرنخ ثبت‌شده</th><th scope="col">پوشش سرنخ</th><th scope="col">هزینهٔ هر تبدیل ثبت‌شده</th><th scope="col">پوشش تبدیل</th></tr></thead>
          <tbody id="scenario-objective-evidence"></tbody>
        </table>
      </div>
      <h3 style="margin-top:22px">هزینهٔ واحد به تفکیک هدف بازاریابی</h3>
      <p class="muted">هزینهٔ تک‌ارزی کمپین‌های هر هدف بر مجموع سرنخ یا تبدیل ثبت‌شدهٔ همان کمپین‌ها تقسیم می‌شود. دادهٔ شاخص ثبت‌نشده در محاسبه وارد نمی‌شود و هزینه‌های چندارزی به ارز خاصی نسبت داده نمی‌شوند؛ این شاخص ROI یا انتساب علّی نیست.</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th scope="col">هدف بازاریابی</th><th scope="col">ارز</th><th scope="col">شاخص</th><th scope="col">هزینهٔ واردشده</th><th scope="col">مجموع نتیجهٔ ثبت‌شده</th><th scope="col">هزینهٔ واحد</th><th scope="col">پوشش کمپین</th></tr></thead>
          <tbody id="objective-unit-cost"></tbody>
        </table>
      </div>
      <h3 style="margin-top:22px">پراکندگی هزینهٔ واحد کمپین‌ها</h3>
      <p class="muted">میانه و دامنهٔ هزینهٔ هر کمپین تک‌ارزی را جداگانه نشان می‌دهد تا تفاوت کمپین‌ها پشت نسبت تجمیعی پنهان نماند. این آمار توصیفی است؛ تعداد نمونه را کنار آن ببینید.</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th scope="col">هدف بازاریابی</th><th scope="col">ارز</th><th scope="col">شاخص</th><th scope="col">تعداد کمپین</th><th scope="col">میانهٔ هزینه</th><th scope="col">کمترین هزینه</th><th scope="col">بیشترین هزینه</th></tr></thead>
          <tbody id="objective-unit-cost-distribution"></tbody>
        </table>
      </div>
      <h3 style="margin-top:22px">هزینهٔ واحد به تفکیک کمپین</h3>
      <p class="muted">برای هر کمپین، هزینهٔ ثبت‌شده بر سرنخ یا تبدیل ثبت‌شده محاسبه می‌شود. مقایسهٔ دو بازه فقط با دادهٔ کافی و ارز یکسان انجام می‌شود؛ این شاخص ROI نیست.</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th scope="col">کمپین</th><th scope="col">کانال</th><th scope="col">شاخص</th><th scope="col">ارز</th><th scope="col">هزینهٔ واحد قبلی</th><th scope="col">هزینهٔ واحد جاری</th><th scope="col">درصد تغییر</th></tr></thead>
          <tbody id="campaign-unit-cost"></tbody>
        </table>
      </div>
      <div id="scenario-results" class="cards"></div>
      <h2 style="margin-top:28px">عملکرد کمپین‌ها در همین بازه</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th scope="col">کمپین</th><th scope="col">هزینهٔ ثبت‌شده</th><th scope="col">سرنخ / تبدیل</th><th scope="col">تخصیص هر سناریو در برابر هزینهٔ واقعی</th></tr></thead>
          <tbody id="campaign-results"></tbody>
        </table>
      </div>
      <h2 style="margin-top:28px">وضعیت هدف‌های ثبت‌شدهٔ کمپین</h2>
      <p id="target-outcomes-note" class="muted">هدف‌ها فقط برای همین بازهٔ گزارش و کمپین‌های مشترک نمایش داده می‌شوند.</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th scope="col">کمپین</th><th scope="col">شاخص</th><th scope="col">هدف</th><th scope="col">عملکرد ثبت‌شده</th><th scope="col">وضعیت</th><th scope="col">پوشش روزهای ثبت‌شده</th></tr></thead>
          <tbody id="target-outcomes"></tbody>
        </table>
      </div>
      <h3 style="margin-top:22px">جمع‌بندی وضعیت هدف‌ها به تفکیک کانال</h3>
      <p id="channel-target-summary-note" class="muted">شمارش وضعیت‌ها از ارزیابی ثبت‌شدهٔ کمپین‌های همین گزارش به دست می‌آید.</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th scope="col">کانال</th><th scope="col">شاخص</th><th scope="col">کمپین دارای هدف</th><th scope="col">محقق‌شده</th><th scope="col">محقق‌نشده</th><th scope="col">دادهٔ ناکافی</th><th scope="col">وضعیت نامشخص</th></tr></thead>
          <tbody id="channel-target-summary"></tbody>
        </table>
      </div>
      <h3 style="margin-top:22px">فاصلهٔ کمی هدف تا عملکرد</h3>
      <p id="target-variance-summary-note" class="muted">برای شاخص‌های تعدادی، فقط دوره‌های دارای پوشش کامل با هدف مقایسه می‌شوند. اختلاف عددی علت را ثابت نمی‌کند.</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th scope="col">گروه</th><th scope="col">شاخص</th><th scope="col">تعداد هدف‌دار</th><th scope="col">دورهٔ کامل</th><th scope="col">جمع هدف</th><th scope="col">عملکرد کامل</th><th scope="col">فاصله</th><th scope="col">هدف دوره ناقص</th><th scope="col">عملکرد ناقص ثبت‌شده</th></tr></thead>
          <tbody id="target-variance-summary"></tbody>
        </table>
      </div>
      <h3 style="margin-top:22px">نسبت تبدیل ثبت‌شده به سرنخ</h3>
      <p class="muted">نسبت مجموع تبدیل‌های ثبت‌شده به سرنخ‌های ثبت‌شده است؛ فقط کمپین‌هایی با هر دو مقدار و سرنخ مثبت وارد می‌شوند. این شاخص، نرخ تبدیل یکتای افراد یا انتساب علّی را اثبات نمی‌کند.</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th scope="col">کانال</th><th scope="col">بازهٔ قبلی: تبدیل / سرنخ</th><th scope="col">بازهٔ جاری: تبدیل / سرنخ</th><th scope="col">تغییر (واحد درصد)</th></tr></thead>
          <tbody id="lead-conversion-ratio"></tbody>
        </table>
      </div>
      <h3 style="margin-top:22px">تغییر وضعیت هدف‌ها نسبت به بازهٔ قبلی</h3>
      <p id="target-period-comparison-note" class="muted">مقایسهٔ توصیفی وضعیت هدف‌ها برای کمپین‌های مشترک در دو بازهٔ هم‌طول است.</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th scope="col">کانال</th><th scope="col">شاخص</th><th scope="col">وضعیت بازهٔ قبلی</th><th scope="col">وضعیت بازهٔ جاری</th><th scope="col">تعداد کمپین</th></tr></thead>
          <tbody id="target-period-comparison"></tbody>
        </table>
      </div>
    </section>
  </main>
</body>
</html>
"""

_CLIENT_SCRIPT = r"""(() => {
  "use strict";
  const byId = (id) => document.getElementById(id);
  const workspaceInput = byId("workspace-id");
  const organizationInput = byId("organization-id");
  const statusNode = byId("status");
  const listNode = byId("scenario-list");
  const scenarioPanel = byId("scenario-panel");
  const resultsPanel = byId("results");
  const formatNumber = new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 2 });
  let latestComparison = null;
  let latestPreviousComparison = null;
  let latestTargetPortfolio = null;
  let latestPreviousTargetPortfolio = null;
  let latestFields = null;

  const params = new URLSearchParams(window.location.search);
  const requestedWorkspaceId = params.get("workspace_id") || "";
  const requestedOrganizationId = params.get("organization_unit_id") || "";
  const requestedScenarioIds = params.getAll("scenario_ids");
  byId("period-start").value = params.get("period_start") || "";
  byId("period-end").value = params.get("period_end") || "";

  function setStatus(message, isError) {
    statusNode.textContent = message || "";
    statusNode.style.color = isError ? "#8b3b22" : "#17613b";
  }
  function clearResults() {
    latestComparison = null;
    latestPreviousComparison = null;
    latestTargetPortfolio = null;
    latestPreviousTargetPortfolio = null;
    latestFields = null;
    byId("target-period-comparison-note").textContent = "";
    byId("target-period-comparison").replaceChildren();
    byId("lead-conversion-ratio").replaceChildren();
    byId("campaign-unit-cost").replaceChildren();
    byId("objective-unit-cost").replaceChildren();
    byId("objective-unit-cost-distribution").replaceChildren();
    byId("scenario-objective-evidence").replaceChildren();
    byId("objective-performance").replaceChildren();
    byId("objective-budget-reconciliation").replaceChildren();
    byId("target-outcomes-note").textContent = "";
    byId("target-outcomes").replaceChildren();
    byId("channel-target-summary-note").textContent = "";
    byId("channel-target-summary").replaceChildren();
    byId("period-comparison-period").textContent = "";
    byId("period-comparison").replaceChildren();
    byId("channel-period-comparison").replaceChildren();
    byId("unit-cost-comparison").replaceChildren();
    resultsPanel.hidden = true;
    byId("evidence-coverage").replaceChildren();
    byId("channel-coverage").replaceChildren();
    byId("evidence-gaps").replaceChildren();
    byId("scenario-results").replaceChildren();
    byId("campaign-results").replaceChildren();
  }
  function selectedIds() {
    return Array.from(listNode.querySelectorAll("input[type=checkbox]:checked")).map((node) => node.value);
  }
  function updateSelectionCount() {
    const count = selectedIds().length;
    byId("selection-count").textContent = count + " از ۵ سناریو انتخاب شده";
    byId("compare").disabled = count < 2 || count > 5;
  }
  function updateReportUrl(fields, ids) {
    const query = new URLSearchParams();
    query.set("workspace_id", workspaceInput.value.trim());
    query.set("organization_unit_id", organizationInput.value.trim());
    query.set("period_start", fields.start);
    query.set("period_end", fields.end);
    ids.forEach((id) => query.append("scenario_ids", id));
    if (window.history && typeof window.history.replaceState === "function") {
      window.history.replaceState(null, "", window.location.pathname + "?" + query.toString() + (window.location.hash || ""));
    }
  }
  function selectedRequestFields() {
    const workspace = workspaceInput.value.trim();
    const organization = organizationInput.value.trim();
    const start = byId("period-start").value;
    const end = byId("period-end").value;
    if (!workspace || !organization) throw new Error("شناسهٔ فضای کاری و واحد سازمانی را وارد کنید.");
    if (!start || !end) throw new Error("بازهٔ تاریخ را کامل کنید.");
    if (start > end) throw new Error("تاریخ شروع باید پیش از تاریخ پایان باشد.");
    return { workspace: workspace, organization: organization, start: start, end: end };
  }
  async function getJson(path, workspaceId) {
    const response = await fetch(path, {
      method: "GET",
      credentials: "same-origin",
      headers: workspaceId
        ? { "Accept": "application/json", "X-Workspace-ID": workspaceId }
        : { "Accept": "application/json" }
    });
    let payload = {};
    try { payload = await response.json(); } catch (_) {}
    if (!response.ok) {
      if (response.status === 401) throw new Error("برای دیدن این صفحه ابتدا وارد حساب کاربری شوید.");
      if (response.status === 403) throw new Error("عضویت فعال یا مجوز مشاهدهٔ این محدوده برای حساب شما ثبت نشده است.");
      throw new Error(payload.detail || "دریافت اطلاعات ناموفق بود. دوباره تلاش کنید.");
    }
    return payload;
  }
  function appendChoice(select, value, label) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    select.appendChild(option);
  }
  async function loadOrganizationChoices() {
    organizationInput.replaceChildren();
    appendChoice(organizationInput, "", "در حال بارگذاری…");
    const units = await getJson("/api/v1/system/organization-units", workspaceInput.value);
    organizationInput.replaceChildren();
    appendChoice(organizationInput, "", "واحد سازمانی را انتخاب کنید");
    units.forEach((unit) => appendChoice(organizationInput, unit.id, unit.name));
    const requested = units.find((unit) => unit.id === requestedOrganizationId);
    const root = units.find((unit) => unit.unit_type === "root");
    if (requested) organizationInput.value = requested.id;
    else if (root) organizationInput.value = root.id;
    if (!units.length) appendChoice(organizationInput, "", "واحد مجاز پیدا نشد");
  }
  async function loadContextChoices() {
    const workspaces = await getJson("/api/v1/system/workspaces");
    workspaceInput.replaceChildren();
    appendChoice(workspaceInput, "", "فضای کاری را انتخاب کنید");
    workspaces.forEach((workspace) => appendChoice(workspaceInput, workspace.id, workspace.name));
    const requested = workspaces.find((workspace) => workspace.id === requestedWorkspaceId);
    if (requested) workspaceInput.value = requested.id;
    else if (workspaces.length === 1) workspaceInput.value = workspaces[0].id;
    if (workspaceInput.value) {
      await loadOrganizationChoices();
      if (requestedScenarioIds.length >= 2 && requestedScenarioIds.length <= 5
          && byId("period-start").value && byId("period-end").value) {
        await loadScenarios();
      }
    } else organizationInput.replaceChildren();
  }
  async function loadAllScenarios(fields) {
    const result = [];
    let offset = 0;
    while (true) {
      const query = new URLSearchParams({
        organization_unit_id: fields.organization,
        status: "draft",
        limit: "100",
        offset: String(offset)
      });
      const page = await getJson("/api/v1/crm/budget-scenarios?" + query.toString(), fields.workspace);
      const items = Array.isArray(page) ? page : [];
      result.push.apply(result, items);
      if (items.length < 100) return result;
      offset += items.length;
    }
  }
  function renderScenarioOptions(items) {
    listNode.replaceChildren();
    if (!items.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "در این واحد سازمانی سناریوی پیش‌نویس پیدا نشد.";
      listNode.appendChild(empty);
      return;
    }
    items.forEach((scenario) => {
      const label = document.createElement("label");
      label.className = "scenario-option";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = scenario.id;
      checkbox.addEventListener("change", () => {
        if (selectedIds().length > 5) {
          checkbox.checked = false;
          setStatus("حداکثر ۵ سناریو را می‌توان هم‌زمان مقایسه کرد.", true);
        } else {
          setStatus("", false);
        }
        updateSelectionCount();
      });
      const copy = document.createElement("span");
      const name = document.createElement("strong");
      name.textContent = scenario.name;
      const details = document.createElement("small");
      details.textContent = (scenario.allocation_count || 0) + " تخصیص · " + scenario.id;
      copy.append(name, details);
      label.append(checkbox, copy);
      listNode.appendChild(label);
    });
    updateSelectionCount();
  }
  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }
  function displayAmount(value, currency) {
    if (value === null || value === undefined) return "—";
    const numeric = Number(value);
    return (Number.isFinite(numeric) ? formatNumber.format(numeric) : String(value)) + " " + currency;
  }
  function addFact(list, label, value) {
    list.append(element("dt", "", label), element("dd", "", value));
  }
  function coverageRate(count, denominator) {
    return denominator > 0 ? count * 100 / denominator : null;
  }
  function displayCoverageRate(count, denominator) {
    const rate = coverageRate(count, denominator);
    return rate === null ? "نامشخص" : formatNumber.format(rate) + "٪";
  }
  function renderEvidenceCoverage(result) {
    const campaigns = result.campaigns || [];
    const scenarios = result.scenarios || [];
    const hasSpend = (campaign) => Object.keys(campaign.recorded_spend_by_currency || {}).length > 0;
    const hasMetric = (campaign, key) => {
      const metric = (campaign.metrics || {})[key] || {};
      return metric.actual !== null && metric.actual !== undefined;
    };
    const values = [
      ["سناریوی مقایسه‌شده", scenarios.length, null],
      ["کمپین هم‌پوشان", campaigns.length, null],
      ["کمپین دارای هزینهٔ ثبت‌شده", campaigns.filter(hasSpend).length, campaigns.length],
      ["کمپین دارای دادهٔ سرنخ", campaigns.filter((campaign) => hasMetric(campaign, "leads")).length, campaigns.length],
      ["کمپین دارای دادهٔ تبدیل", campaigns.filter((campaign) => hasMetric(campaign, "conversions")).length, campaigns.length],
    ];
    const container = byId("evidence-coverage");
    container.replaceChildren();
    values.forEach(([label, count, denominator]) => {
      const card = element("article", "scenario-card");
      card.appendChild(element("strong", "", formatNumber.format(count)));
      const detail = denominator === null
        ? label
        : label + " · " + formatNumber.format(count) + " از " + formatNumber.format(denominator)
          + " کمپین · پوشش " + displayCoverageRate(count, denominator);
      card.appendChild(element("p", "muted", detail));
      container.appendChild(card);
    });
  }
  function campaignChannel(campaign) {
    const rawChannel = campaign.channel;
    return rawChannel === null || rawChannel === undefined || String(rawChannel).trim() === ""
      ? "بدون کانال ثبت‌شده"
      : String(rawChannel);
  }
  function channelCoverage(campaigns) {
    const groups = new Map();
    campaigns.forEach((campaign) => {
      const channel = campaignChannel(campaign);
      const group = groups.get(channel) || { channel, campaigns: 0, spend: 0, leads: 0, conversions: 0 };
      group.campaigns += 1;
      if (Object.keys(campaign.recorded_spend_by_currency || {}).length > 0) group.spend += 1;
      ["leads", "conversions"].forEach((key) => {
        const metric = (campaign.metrics || {})[key] || {};
        if (metric.actual !== null && metric.actual !== undefined) group[key] += 1;
      });
      groups.set(channel, group);
    });
    return Array.from(groups.values()).sort((a, b) => a.channel.localeCompare(b.channel, "fa"));
  }
  function renderChannelCoverage(campaigns) {
    const body = byId("channel-coverage");
    body.replaceChildren();
    channelCoverage(campaigns).forEach((group) => {
      const row = document.createElement("tr");
      row.append(
        element("td", "", group.channel),
        element("td", "", formatNumber.format(group.campaigns)),
        element("td", "", formatNumber.format(group.spend) + " / " + formatNumber.format(group.campaigns) + " · " + displayCoverageRate(group.spend, group.campaigns)),
        element("td", "", formatNumber.format(group.leads) + " / " + formatNumber.format(group.campaigns) + " · " + displayCoverageRate(group.leads, group.campaigns)),
        element("td", "", formatNumber.format(group.conversions) + " / " + formatNumber.format(group.campaigns) + " · " + displayCoverageRate(group.conversions, group.campaigns)),
      );
      body.appendChild(row);
    });
  }
  function missingEvidence(campaign) {
    const missing = [];
    if (!Object.keys(campaign.recorded_spend_by_currency || {}).length) missing.push("هزینهٔ ثبت‌شده");
    const metrics = campaign.metrics || {};
    if (metrics.leads?.actual === null || metrics.leads?.actual === undefined) missing.push("دادهٔ سرنخ");
    if (metrics.conversions?.actual === null || metrics.conversions?.actual === undefined) missing.push("دادهٔ تبدیل");
    return missing;
  }
  function renderEvidenceGaps(campaigns) {
    const body = byId("evidence-gaps");
    body.replaceChildren();
    const gaps = campaigns.filter((campaign) => missingEvidence(campaign).length > 0);
    if (!gaps.length) {
      const row = document.createElement("tr");
      const cell = element("td", "muted", "برای کمپین‌های این گزارش شکاف شواهدی پیدا نشد.");
      cell.colSpan = 3;
      row.appendChild(cell);
      body.appendChild(row);
      return;
    }
    gaps.forEach((campaign) => {
      const row = document.createElement("tr");
      row.append(
        element("td", "", campaign.campaign_name),
        element("td", "", campaignChannel(campaign)),
        element("td", "", missingEvidence(campaign).join("، ")),
      );
      body.appendChild(row);
    });
  }
  function precedingPeriod(fields) {
    const day = 24 * 60 * 60 * 1000;
    const start = new Date(fields.start + "T00:00:00Z");
    const end = new Date(fields.end + "T00:00:00Z");
    const periodDays = Math.round((end.getTime() - start.getTime()) / day) + 1;
    const previousEnd = new Date(start.getTime() - day);
    const previousStart = new Date(start.getTime() - periodDays * day);
    return { start: previousStart.toISOString().slice(0, 10), end: previousEnd.toISOString().slice(0, 10) };
  }
  function aggregateReportEvidence(report) {
    const campaigns = report.campaigns || [];
    const spend = {};
    const metricValues = { leads: [], conversions: [] };
    campaigns.forEach((campaign) => {
      Object.entries(campaign.recorded_spend_by_currency || {}).forEach(([currency, amount]) => {
        spend[currency] = (spend[currency] || 0) + Number(amount);
      });
      ["leads", "conversions"].forEach((key) => {
        const actual = (campaign.metrics || {})[key]?.actual;
        if (actual !== null && actual !== undefined) metricValues[key].push(Number(actual));
      });
    });
    return {
      spend,
      leads: metricValues.leads.length ? metricValues.leads.reduce((sum, value) => sum + value, 0) : null,
      conversions: metricValues.conversions.length ? metricValues.conversions.reduce((sum, value) => sum + value, 0) : null,
    };
  }
  function comparisonRows(currentReport, previousReport) {
    if (!previousReport) return [];
    const current = aggregateReportEvidence(currentReport);
    const previous = aggregateReportEvidence(previousReport);
    const rows = [];
    [["سرنخ", "leads"], ["تبدیل", "conversions"]].forEach(([label, key]) => {
      const before = previous[key];
      const now = current[key];
      rows.push({ label, currency: "", before, now, delta: before === null || now === null ? null : now - before,
        percent: before === null || now === null || before === 0 ? null : ((now - before) / Math.abs(before)) * 100 });
    });
    Array.from(new Set([...Object.keys(previous.spend), ...Object.keys(current.spend)])).sort().forEach((currency) => {
      const before = Object.hasOwn(previous.spend, currency) ? previous.spend[currency] : null;
      const now = Object.hasOwn(current.spend, currency) ? current.spend[currency] : null;
      rows.push({ label: "هزینهٔ ثبت‌شده", currency, before, now, delta: before === null || now === null ? null : now - before,
        percent: before === null || now === null || before === 0 ? null : ((now - before) / Math.abs(before)) * 100 });
    });
    return rows;
  }
  function comparisonValue(value, currency) {
    if (value === null || value === undefined) return "ثبت نشده";
    return currency ? displayAmount(value, currency) : formatNumber.format(value);
  }
  function aggregateReportEvidenceByChannel(report) {
    const groups = new Map();
    (report.campaigns || []).forEach((campaign) => {
      const channel = campaignChannel(campaign);
      const group = groups.get(channel) || { channel, spend: {}, leads: [], conversions: [] };
      Object.entries(campaign.recorded_spend_by_currency || {}).forEach(([currency, amount]) => {
        group.spend[currency] = (group.spend[currency] || 0) + Number(amount);
      });
      ["leads", "conversions"].forEach((key) => {
        const actual = (campaign.metrics || {})[key]?.actual;
        if (actual !== null && actual !== undefined) group[key].push(Number(actual));
      });
      groups.set(channel, group);
    });
    groups.forEach((group) => {
      ["leads", "conversions"].forEach((key) => {
        group[key] = group[key].length ? group[key].reduce((sum, value) => sum + value, 0) : null;
      });
    });
    return groups;
  }
  function channelComparisonRows(currentReport, previousReport) {
    if (!previousReport) return [];
    const current = aggregateReportEvidenceByChannel(currentReport);
    const previous = aggregateReportEvidenceByChannel(previousReport);
    const rows = [];
    Array.from(new Set([...previous.keys(), ...current.keys()])).sort((a, b) => a.localeCompare(b, "fa")).forEach((channel) => {
      const beforeGroup = previous.get(channel);
      const currentGroup = current.get(channel);
      [["سرنخ", "leads"], ["تبدیل", "conversions"]].forEach(([label, key]) => {
        const before = beforeGroup?.[key] ?? null;
        const now = currentGroup?.[key] ?? null;
        rows.push({ channel, label, currency: "", before, now,
          delta: before === null || now === null ? null : now - before,
          percent: before === null || now === null || before === 0 ? null : ((now - before) / Math.abs(before)) * 100 });
      });
      const currencies = new Set([...Object.keys(beforeGroup?.spend || {}), ...Object.keys(currentGroup?.spend || {})]);
      Array.from(currencies).sort().forEach((currency) => {
        const before = beforeGroup && Object.hasOwn(beforeGroup.spend, currency) ? beforeGroup.spend[currency] : null;
        const now = currentGroup && Object.hasOwn(currentGroup.spend, currency) ? currentGroup.spend[currency] : null;
        rows.push({ channel, label: "هزینهٔ ثبت‌شده", currency, before, now,
          delta: before === null || now === null ? null : now - before,
          percent: before === null || now === null || before === 0 ? null : ((now - before) / Math.abs(before)) * 100 });
      });
    });
    return rows;
  }
  function renderChannelPeriodComparison(currentReport, previousReport) {
    const body = byId("channel-period-comparison");
    body.replaceChildren();
    const rows = channelComparisonRows(currentReport, previousReport);
    if (!rows.length) {
      const row = document.createElement("tr");
      const cell = element("td", "muted", "دادهٔ مقایسه‌ای کانال‌ها در دسترس نیست.");
      cell.colSpan = 6;
      row.appendChild(cell);
      body.appendChild(row);
      return;
    }
    rows.forEach((item) => {
      const row = document.createElement("tr");
      row.append(element("td", "", item.channel),
        element("td", "", item.label + (item.currency ? " · " + item.currency : "")),
        element("td", "", comparisonValue(item.before, item.currency)),
        element("td", "", comparisonValue(item.now, item.currency)),
        element("td", "", item.delta === null ? "نامشخص" : comparisonValue(item.delta, item.currency)),
        element("td", "", item.percent === null ? "نامشخص" : formatNumber.format(item.percent) + "٪"));
      body.appendChild(row);
    });
  }
  function leadConversionRows(report) {
    const groups = new Map();
    (report?.campaigns || []).forEach((campaign) => {
      const metrics = campaign.metrics || {};
      const leads = metrics.leads?.actual;
      const conversions = metrics.conversions?.actual;
      if (leads === null || leads === undefined || conversions === null || conversions === undefined) return;
      const leadCount = Number(leads);
      const conversionCount = Number(conversions);
      if (!Number.isFinite(leadCount) || !Number.isFinite(conversionCount) || leadCount <= 0 || conversionCount < 0) return;
      const channel = campaign.channel || "نامشخص";
      const group = groups.get(channel) || { channel, leads: 0, conversions: 0, campaigns: 0 };
      group.leads += leadCount;
      group.conversions += conversionCount;
      group.campaigns += 1;
      groups.set(channel, group);
    });
    return new Map(Array.from(groups, ([channel, group]) => [
      channel, { ...group, rate: (group.conversions / group.leads) * 100 },
    ]));
  }
  function compareLeadConversionRates(currentReport, previousReport) {
    const current = leadConversionRows(currentReport);
    const previous = leadConversionRows(previousReport);
    return Array.from(new Set([...current.keys(), ...previous.keys()])).sort((a, b) => a.localeCompare(b, "fa"))
      .map((channel) => ({
        channel, current: current.get(channel) || null, previous: previous.get(channel) || null,
        delta: current.has(channel) && previous.has(channel)
          ? current.get(channel).rate - previous.get(channel).rate : null,
      }));
  }
  function renderLeadConversionRatio(currentReport, previousReport) {
    const body = byId("lead-conversion-ratio");
    body.replaceChildren();
    const rows = compareLeadConversionRates(currentReport, previousReport);
    if (!rows.length) {
      const row = document.createElement("tr");
      const cell = element("td", "muted", "برای این گزارش دادهٔ هم‌زمان سرنخ و تبدیل با سرنخ مثبت پیدا نشد.");
      cell.colSpan = 4;
      row.appendChild(cell);
      body.appendChild(row);
      return;
    }
    const describe = (group) => group
      ? formatNumber.format(group.rate) + "٪ · " + formatNumber.format(group.campaigns)
        + " کمپین · " + formatNumber.format(group.conversions) + " / " + formatNumber.format(group.leads)
      : "دادهٔ کافی نیست";
    rows.forEach((item) => {
      const row = document.createElement("tr");
      row.append(element("td", "", item.channel),
        element("td", "", describe(item.previous)),
        element("td", "", describe(item.current)),
        element("td", "", item.delta === null ? "نامشخص" : formatNumber.format(item.delta) + " واحد درصد"));
      body.appendChild(row);
    });
  }
  function objectiveMetricGroups(report) {
    const groups = new Map();
    (report?.campaigns || []).forEach((campaign) => {
      const objective = campaign.objective_key || "بدون هدف ثبت‌شده";
      const channel = campaign.channel || "نامشخص";
      const id = JSON.stringify([objective, channel]);
      const group = groups.get(id) || {
        objective, channel, campaigns: 0,
        metrics: { leads: { total: 0, observed: 0 }, conversions: { total: 0, observed: 0 } },
      };
      group.campaigns += 1;
      ["leads", "conversions"].forEach((key) => {
        const actual = campaign.metrics?.[key]?.actual;
        if (actual === null || actual === undefined || !Number.isFinite(Number(actual))) return;
        group.metrics[key].total += Number(actual);
        group.metrics[key].observed += 1;
      });
      groups.set(id, group);
    });
    return groups;
  }
  function compareObjectivePerformance(currentReport, previousReport) {
    const current = objectiveMetricGroups(currentReport);
    const previous = objectiveMetricGroups(previousReport);
    const groups = new Map();
    Array.from(new Set([...current.keys(), ...previous.keys()])).forEach((id) => {
      const now = current.get(id) || null;
      const before = previous.get(id) || null;
      const group = now || before;
      ["leads", "conversions"].forEach((key) => {
        const currentMetric = now?.metrics[key] || null;
        const previousMetric = before?.metrics[key] || null;
        const currentObserved = currentMetric?.observed || 0;
        const previousObserved = previousMetric?.observed || 0;
        groups.set(JSON.stringify([id, key]), {
          objective: group.objective, channel: group.channel, key,
          previous: previousObserved ? previousMetric.total : null,
          current: currentObserved ? currentMetric.total : null,
          delta: previousObserved && currentObserved ? currentMetric.total - previousMetric.total : null,
          previousCoverage: { observed: previousObserved, campaigns: before?.campaigns || 0 },
          currentCoverage: { observed: currentObserved, campaigns: now?.campaigns || 0 },
        });
      });
    });
    return Array.from(groups.values()).sort((a, b) =>
      a.objective.localeCompare(b.objective, "fa") || a.channel.localeCompare(b.channel, "fa")
        || ["leads", "conversions"].indexOf(a.key) - ["leads", "conversions"].indexOf(b.key));
  }
  function renderObjectivePerformance(currentReport, previousReport) {
    const body = byId("objective-performance");
    body.replaceChildren();
    const rows = compareObjectivePerformance(currentReport, previousReport);
    if (!rows.length) {
      const row = document.createElement("tr");
      const cell = element("td", "muted", "برای این گزارش دادهٔ کمپینی وجود ندارد.");
      cell.colSpan = 9;
      row.appendChild(cell);
      body.appendChild(row);
      return;
    }
    const coverage = (item) => formatNumber.format(item.observed) + " / " + formatNumber.format(item.campaigns);
    rows.forEach((item) => {
      const row = document.createElement("tr");
      row.append(element("td", "", item.objective),
        element("td", "", item.channel),
        element("td", "", item.key === "leads" ? "سرنخ ثبت‌شده" : "تبدیل ثبت‌شده"),
        element("td", "", item.previous === null ? "ثبت نشده" : formatNumber.format(item.previous)),
        element("td", "", item.current === null ? "ثبت نشده" : formatNumber.format(item.current)),
        element("td", "", item.delta === null ? "نامشخص" : formatNumber.format(item.delta)),
        element("td", "", coverage(item.previousCoverage)),
        element("td", "", coverage(item.currentCoverage)));
      body.appendChild(row);
    });
  }
  function objectiveBudgetRows(report) {
    const groups = new Map();
    (report?.campaigns || []).forEach((campaign) => {
      const objective = campaign.objective_key || "بدون هدف ثبت‌شده";
      (campaign.scenario_allocations || []).forEach((allocation) => {
        const scenario = allocation.scenario_name || "سناریوی نامشخص";
        const currency = allocation.planned_budget_currency || "ارز نامشخص";
        const id = JSON.stringify([objective, scenario, currency]);
        const group = groups.get(id) || {
          objective, scenario, currency, planned: 0, comparablePlanned: 0,
          observedSpend: 0, variance: 0, allocations: 0, comparableAllocations: 0,
        };
        const planned = Number(allocation.planned_budget_amount);
        group.allocations += 1;
        if (Number.isFinite(planned)) group.planned += planned;
        const actual = allocation.actual_spend_in_allocation_currency;
        const variance = allocation.variance_amount;
        if (actual !== null && actual !== undefined && Number.isFinite(Number(actual))
          && variance !== null && variance !== undefined && Number.isFinite(Number(variance))
          && Number.isFinite(planned)) {
          group.comparableAllocations += 1;
          group.comparablePlanned += planned;
          group.observedSpend += Number(actual);
          group.variance += Number(variance);
        }
        groups.set(id, group);
      });
    });
    const rows = Array.from(groups.values());
    const totals = new Map();
    rows.forEach((item) => {
      const key = JSON.stringify([item.scenario, item.currency]);
      totals.set(key, (totals.get(key) || 0) + item.planned);
    });
    rows.forEach((item) => {
      const total = totals.get(JSON.stringify([item.scenario, item.currency])) || 0;
      item.mixSharePercent = total > 0 ? item.planned * 100 / total : null;
    });
    return rows.sort((a, b) =>
      a.objective.localeCompare(b.objective, "fa") || a.scenario.localeCompare(b.scenario, "fa")
        || a.currency.localeCompare(b.currency));
  }
  function renderObjectiveBudgetReconciliation(report) {
    const body = byId("objective-budget-reconciliation");
    body.replaceChildren();
    const rows = objectiveBudgetRows(report);
    if (!rows.length) {
      const row = document.createElement("tr");
      const cell = element("td", "muted", "برای تخصیص‌های این گزارش داده‌ای وجود ندارد.");
      cell.colSpan = 8;
      row.appendChild(cell);
      body.appendChild(row);
      return;
    }
    rows.forEach((item) => {
      const row = document.createElement("tr");
      row.append(element("td", "", item.objective), element("td", "", item.scenario),
        element("td", "", item.currency),
        element("td", "", displayAmount(item.planned, item.currency)),
        element("td", "", displayAmount(item.comparablePlanned, item.currency)),
        element("td", "", item.comparableAllocations ? displayAmount(item.observedSpend, item.currency) : "نامشخص"),
        element("td", "", item.comparableAllocations ? displayAmount(item.variance, item.currency) : "نامشخص"),
        element("td", "", formatNumber.format(item.comparableAllocations) + " / " + formatNumber.format(item.allocations)),
        element("td", "", item.mixSharePercent === null ? "نامشخص" : formatNumber.format(item.mixSharePercent) + "٪"));
      body.appendChild(row);
    });
  }
  function campaignUnitCostValue(campaign, key) {
    if (!campaign) return { value: null, currency: null, reason: "campaign_missing" };
    const spend = Object.entries(campaign.recorded_spend_by_currency || {});
    if (!spend.length) return { value: null, currency: null, reason: "spend_missing" };
    if (spend.length !== 1) return { value: null, currency: null, reason: "multi_currency" };
    const [currency, amount] = spend[0];
    const actual = (campaign.metrics || {})[key]?.actual;
    if (actual === null || actual === undefined) return { value: null, currency, reason: "metric_missing" };
    const denominator = Number(actual);
    const numerator = Number(amount);
    if (!Number.isFinite(denominator) || denominator <= 0) return { value: null, currency, reason: "invalid_denominator" };
    if (!Number.isFinite(numerator) || numerator < 0) return { value: null, currency, reason: "invalid_spend" };
    return { value: numerator / denominator, currency, reason: null };
  }
  function unitCostReason(reason) {
    return ({
      campaign_missing: "کمپین در بازهٔ قبلی موجود نیست",
      spend_missing: "هزینه ثبت نشده",
      multi_currency: "هزینه چندارزی است",
      metric_missing: "شاخص ثبت نشده",
      invalid_denominator: "مخرج صفر یا نامعتبر است",
      invalid_spend: "هزینه نامعتبر است",
      currency_mismatch: "ارز دو بازه یکسان نیست",
    })[reason] || "نامشخص";
  }
  function objectiveUnitCostRows(report) {
    const groups = new Map();
    (report?.campaigns || []).forEach((campaign) => {
      const spend = Object.entries(campaign.recorded_spend_by_currency || {});
      if (spend.length !== 1) return;
      const objective = campaign.objective_key || "بدون هدف ثبت‌شده";
      const [currency, amountValue] = spend[0];
      const amount = Number(amountValue);
      if (!Number.isFinite(amount) || amount < 0) return;
      const id = JSON.stringify([objective, currency]);
      const group = groups.get(id) || {
        objective, currency, campaigns: 0,
        metrics: {
          leads: { spend: 0, outcomes: 0, observed: 0 },
          conversions: { spend: 0, outcomes: 0, observed: 0 },
        },
      };
      group.campaigns += 1;
      ["leads", "conversions"].forEach((key) => {
        const value = campaign.metrics?.[key]?.actual;
        if (value === null || value === undefined || !Number.isFinite(Number(value)) || Number(value) < 0) return;
        group.metrics[key].spend += amount;
        group.metrics[key].outcomes += Number(value);
        group.metrics[key].observed += 1;
      });
      groups.set(id, group);
    });
    const rows = [];
    groups.forEach((group) => ["leads", "conversions"].forEach((key) => {
      const metric = group.metrics[key];
      rows.push({
        objective: group.objective, currency: group.currency, key,
        spend: metric.observed ? metric.spend : null,
        outcomes: metric.observed ? metric.outcomes : null,
        unitCost: metric.observed && metric.outcomes > 0 ? metric.spend / metric.outcomes : null,
        observed: metric.observed, campaigns: group.campaigns,
      });
    }));
    return rows.sort((a, b) =>
      a.objective.localeCompare(b.objective, "fa") || a.currency.localeCompare(b.currency)
        || ["leads", "conversions"].indexOf(a.key) - ["leads", "conversions"].indexOf(b.key));
  }
  function scenarioObjectiveEvidenceRows(report) {
    const costs = new Map(objectiveUnitCostRows(report).map((item) =>
      [JSON.stringify([item.objective, item.currency, item.key]), item]));
    return objectiveBudgetRows(report).map((budget) => {
      const leads = costs.get(JSON.stringify([budget.objective, budget.currency, "leads"])) || null;
      const conversions = costs.get(JSON.stringify([budget.objective, budget.currency, "conversions"])) || null;
      return { ...budget, leads, conversions };
    });
  }
  function renderScenarioObjectiveEvidence(report) {
    const body = byId("scenario-objective-evidence");
    body.replaceChildren();
    const rows = scenarioObjectiveEvidenceRows(report);
    if (!rows.length) {
      const row = document.createElement("tr");
      const cell = element("td", "muted", "برای این سناریو تخصیص بودجه‌ای ثبت نشده است.");
      cell.colSpan = 9;
      row.appendChild(cell);
      body.appendChild(row);
      return;
    }
    const costText = (item) => !item || item.unitCost === null
      ? "نامشخص" : displayAmount(item.unitCost, item.currency);
    const coverage = (item) => item
      ? formatNumber.format(item.observed) + " / " + formatNumber.format(item.campaigns)
      : "بدون سابقهٔ قابل‌مقایسه";
    rows.forEach((item) => {
      const row = document.createElement("tr");
      row.append(element("td", "", item.objective), element("td", "", item.scenario),
        element("td", "", item.currency), element("td", "", displayAmount(item.planned, item.currency)),
        element("td", "", item.mixSharePercent === null ? "نامشخص" : formatNumber.format(item.mixSharePercent) + "٪"),
        element("td", "", costText(item.leads)), element("td", "", coverage(item.leads)),
        element("td", "", costText(item.conversions)), element("td", "", coverage(item.conversions)));
      body.appendChild(row);
    });
  }
  function objectiveUnitCostDistributionRows(report) {
    const groups = new Map();
    (report?.campaigns || []).forEach((campaign) => {
      const objective = campaign.objective_key || "بدون هدف ثبت‌شده";
      ["leads", "conversions"].forEach((key) => {
        const result = campaignUnitCostValue(campaign, key);
        if (result.value === null || result.currency === null) return;
        const id = JSON.stringify([objective, result.currency, key]);
        const group = groups.get(id) || { objective, currency: result.currency, key, values: [] };
        group.values.push(result.value);
        groups.set(id, group);
      });
    });
    const median = (values) => {
      const sorted = [...values].sort((a, b) => a - b);
      const middle = Math.floor(sorted.length / 2);
      return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
    };
    return Array.from(groups.values()).map((item) => ({
      objective: item.objective, currency: item.currency, key: item.key,
      count: item.values.length, median: median(item.values),
      minimum: Math.min(...item.values), maximum: Math.max(...item.values),
    })).sort((a, b) =>
      a.objective.localeCompare(b.objective, "fa") || a.currency.localeCompare(b.currency)
        || ["leads", "conversions"].indexOf(a.key) - ["leads", "conversions"].indexOf(b.key));
  }
  function renderObjectiveUnitCostDistribution(report) {
    const body = byId("objective-unit-cost-distribution");
    body.replaceChildren();
    const rows = objectiveUnitCostDistributionRows(report);
    if (!rows.length) {
      const row = document.createElement("tr");
      const cell = element("td", "muted", "برای محاسبهٔ دامنه، دادهٔ هزینه و شاخص کافی موجود نیست.");
      cell.colSpan = 7;
      row.appendChild(cell);
      body.appendChild(row);
      return;
    }
    rows.forEach((item) => {
      const row = document.createElement("tr");
      row.append(element("td", "", item.objective), element("td", "", item.currency),
        element("td", "", item.key === "leads" ? "هزینه به‌ازای سرنخ" : "هزینه به‌ازای تبدیل"),
        element("td", "", formatNumber.format(item.count)),
        element("td", "", displayAmount(item.median, item.currency)),
        element("td", "", displayAmount(item.minimum, item.currency)),
        element("td", "", displayAmount(item.maximum, item.currency)));
      body.appendChild(row);
    });
  }
  function renderObjectiveUnitCosts(report) {
    const body = byId("objective-unit-cost");
    body.replaceChildren();
    const rows = objectiveUnitCostRows(report);
    if (!rows.length) {
      const row = document.createElement("tr");
      const cell = element("td", "muted", "کمپین تک‌ارزی دارای هزینه در این گزارش ثبت نشده است.");
      cell.colSpan = 7;
      row.appendChild(cell);
      body.appendChild(row);
      return;
    }
    rows.forEach((item) => {
      const row = document.createElement("tr");
      row.append(element("td", "", item.objective),
        element("td", "", item.currency),
        element("td", "", item.key === "leads" ? "سرنخ ثبت‌شده" : "تبدیل ثبت‌شده"),
        element("td", "", item.spend === null ? "ثبت نشده" : displayAmount(item.spend, item.currency)),
        element("td", "", item.outcomes === null ? "ثبت نشده" : formatNumber.format(item.outcomes)),
        element("td", "", item.unitCost === null ? "نامشخص" : displayAmount(item.unitCost, item.currency)),
        element("td", "", formatNumber.format(item.observed) + " / " + formatNumber.format(item.campaigns)));
      body.appendChild(row);
    });
  }
  function campaignUnitCostRows(currentReport, previousReport) {
    const previousById = new Map((previousReport?.campaigns || [])
      .filter((campaign) => campaign.campaign_id !== null && campaign.campaign_id !== undefined)
      .map((campaign) => [String(campaign.campaign_id), campaign]));
    const rows = [];
    (currentReport.campaigns || []).forEach((campaign) => {
      const id = campaign.campaign_id === null || campaign.campaign_id === undefined
        ? null : String(campaign.campaign_id);
      const previousCampaign = id === null ? null : previousById.get(id) || null;
      ["leads", "conversions"].forEach((key) => {
        const current = campaignUnitCostValue(campaign, key);
        const previous = campaignUnitCostValue(previousCampaign, key);
        const currencyMismatch = current.value !== null && previous.value !== null
          && current.currency !== previous.currency;
        const percent = current.value === null || previous.value === null || currencyMismatch || previous.value === 0
          ? null : ((current.value - previous.value) / Math.abs(previous.value)) * 100;
        rows.push({
          campaign: campaign.campaign_name || campaign.name || id || "نامشخص",
          channel: campaign.channel || "نامشخص",
          key, current, previous, percent,
          currency: current.currency || previous.currency || "",
          previousReason: previous.reason || (currencyMismatch ? "currency_mismatch" : null),
        });
      });
    });
    return rows;
  }
  function campaignUnitCostText(value, reason, currency) {
    if (value !== null && value !== undefined) return displayAmount(value, currency);
    return unitCostReason(reason);
  }
  function renderCampaignUnitCosts(currentReport, previousReport) {
    const body = byId("campaign-unit-cost");
    body.replaceChildren();
    const rows = campaignUnitCostRows(currentReport, previousReport);
    if (!rows.length) {
      const row = document.createElement("tr");
      const cell = element("td", "muted", "برای این گزارش کمپینی وجود ندارد.");
      cell.colSpan = 7;
      row.appendChild(cell);
      body.appendChild(row);
      return;
    }
    rows.forEach((item) => {
      const row = document.createElement("tr");
      row.append(element("td", "", item.campaign),
        element("td", "", item.channel),
        element("td", "", item.key === "leads" ? "هزینه به‌ازای سرنخ" : "هزینه به‌ازای تبدیل"),
        element("td", "", item.currency || "—"),
        element("td", "", campaignUnitCostText(item.previous.value, item.previousReason || item.previous.reason, item.previous.currency)),
        element("td", "", campaignUnitCostText(item.current.value, item.current.reason, item.current.currency)),
        element("td", "", item.percent === null ? "نامشخص" : formatNumber.format(item.percent) + "٪"));
      body.appendChild(row);
    });
  }
  function unitCostRows(report) {
    const groups = new Map();
    (report.campaigns || []).forEach((campaign) => {
      const currencies = Object.entries(campaign.recorded_spend_by_currency || {});
      if (currencies.length !== 1) return;
      const [currency, amount] = currencies[0];
      ["leads", "conversions"].forEach((key) => {
        const actual = (campaign.metrics || {})[key]?.actual;
        if (actual === null || actual === undefined) return;
        const channel = campaignChannel(campaign);
        const id = JSON.stringify([channel, currency, key]);
        const group = groups.get(id) || { channel, currency, key, spend: 0, metricTotal: 0, campaignCount: 0 };
        group.spend += Number(amount);
        group.metricTotal += Number(actual);
        group.campaignCount += 1;
        groups.set(id, group);
      });
    });
    groups.forEach((group) => {
      group.unitCost = group.metricTotal > 0 && group.spend >= 0 ? group.spend / group.metricTotal : null;
    });
    return groups;
  }
  function compareUnitCosts(currentReport, previousReport) {
    if (!previousReport) return [];
    const current = unitCostRows(currentReport);
    const previous = unitCostRows(previousReport);
    return Array.from(new Set([...previous.keys(), ...current.keys()])).map((id) => {
      const before = previous.get(id) || null;
      const now = current.get(id) || null;
      const item = now || before;
      const beforeCost = before?.unitCost ?? null;
      const nowCost = now?.unitCost ?? null;
      return {
        channel: item.channel, currency: item.currency, key: item.key,
        before, now, beforeCost, nowCost,
        percent: beforeCost === null || nowCost === null || beforeCost === 0
          ? null : ((nowCost - beforeCost) / Math.abs(beforeCost)) * 100,
      };
    }).sort((a, b) => a.channel.localeCompare(b.channel, "fa")
      || a.currency.localeCompare(b.currency)
      || ["leads", "conversions"].indexOf(a.key) - ["leads", "conversions"].indexOf(b.key));
  }
  function unitCostText(group) {
    if (!group) return "ثبت نشده";
    if (group.unitCost === null) return "نامشخص";
    return displayAmount(group.unitCost, group.currency);
  }
  function renderUnitCostComparison(currentReport, previousReport) {
    const body = byId("unit-cost-comparison");
    body.replaceChildren();
    const rows = compareUnitCosts(currentReport, previousReport);
    if (!rows.length) {
      const row = document.createElement("tr");
      const cell = element("td", "muted", "برای کمپین‌های این گزارش دادهٔ کافی و هم‌ارز پیدا نشد.");
      cell.colSpan = 8;
      row.appendChild(cell);
      body.appendChild(row);
      return;
    }
    rows.forEach((item) => {
      const row = document.createElement("tr");
      const metric = item.key === "leads" ? "هزینه به‌ازای هر سرنخ" : "هزینه به‌ازای هر تبدیل";
      row.append(element("td", "", item.channel),
        element("td", "", metric),
        element("td", "", item.currency),
        element("td", "", unitCostText(item.before)),
        element("td", "", unitCostText(item.now)),
        element("td", "", item.percent === null ? "نامشخص" : formatNumber.format(item.percent) + "٪"),
        element("td", "", item.now ? formatNumber.format(item.now.metricTotal) : "—"),
        element("td", "", item.now ? formatNumber.format(item.now.campaignCount) : "۰"));
      body.appendChild(row);
    });
  }
  function campaignTargetRows(report, portfolio) {
    if (!portfolio) return [];
    const includedIds = new Set((report.campaigns || []).map((campaign) => String(campaign.campaign_id)));
    const rows = [];
    (portfolio.campaigns || []).filter((item) => includedIds.has(String(item.campaign_id))).forEach((item) => {
      Object.entries(item.metrics || {}).sort(([a], [b]) => a.localeCompare(b)).forEach(([key, metric]) => {
        rows.push({ campaign: item.name, channel: item.group_key, key, ...metric });
      });
    });
    return rows;
  }
  function channelTargetSummaryRows(portfolio, includedCampaignIds) {
    if (!portfolio || portfolio.campaign_list_truncated) return [];
    const groups = new Map();
    (portfolio.campaigns || []).filter((campaign) =>
      includedCampaignIds.has(String(campaign.campaign_id))).forEach((campaign) => {
      Object.entries(campaign.metrics || {}).forEach(([key, metric]) => {
        const channel = campaign.group_key || "نامشخص";
        const groupKey = JSON.stringify([channel, key]);
        const group = groups.get(groupKey) || {
          channel, key, campaigns: 0, met: 0, notMet: 0, noData: 0, unknown: 0,
        };
        group.campaigns += 1;
        if (metric.status === "met") group.met += 1;
        else if (metric.status === "not_met") group.notMet += 1;
        else if (metric.status === "no_data") group.noData += 1;
        else group.unknown += 1;
        groups.set(groupKey, group);
      });
    });
    return Array.from(groups.values()).sort((a, b) =>
      a.channel.localeCompare(b.channel, "fa") || a.key.localeCompare(b.key));
  }
  function renderChannelTargetSummary(report, portfolio) {
    const body = byId("channel-target-summary");
    const note = byId("channel-target-summary-note");
    body.replaceChildren();
    if (!portfolio) {
      note.textContent = "جمع‌بندی هدف‌های کانال در دسترس نیست.";
      return;
    }
    if (portfolio.campaign_list_truncated) {
      note.textContent = "به‌دلیل محدود بودن فهرست کمپین‌های ارزیابی‌شده، جمع‌بندی کانال نمایش داده نمی‌شود.";
      return;
    }
    note.textContent = "شمارش‌ها از وضعیت ارزیابی‌شدهٔ هر شاخص در کمپین‌های مشترک گزارش است؛ وضعیت‌های نامشخص جدا نگه داشته شده‌اند.";
    const includedIds = new Set((report.campaigns || []).map((campaign) => String(campaign.campaign_id)));
    const rows = channelTargetSummaryRows(portfolio, includedIds);
    if (!rows.length) {
      const row = document.createElement("tr");
      const cell = element("td", "muted", "برای کمپین‌های مشترک هدفی برای جمع‌بندی ثبت نشده است.");
      cell.colSpan = 7;
      row.appendChild(cell);
      body.appendChild(row);
      return;
    }
    rows.forEach((item) => {
      const row = document.createElement("tr");
      row.append(element("td", "", item.channel),
        element("td", "", targetMetricLabel(item.key)),
        element("td", "", formatNumber.format(item.campaigns)),
        element("td", "", formatNumber.format(item.met)),
        element("td", "", formatNumber.format(item.notMet)),
        element("td", "", formatNumber.format(item.noData)),
        element("td", "", formatNumber.format(item.unknown)));
      body.appendChild(row);
    });
  }
  function targetStatusByCampaign(portfolio, includedIds) {
    const statuses = new Map();
    (portfolio.campaigns || []).filter((campaign) =>
      includedIds.has(String(campaign.campaign_id))).forEach((campaign) => {
      Object.entries(campaign.metrics || {}).forEach(([key, metric]) => {
        const status = ["met", "not_met", "no_data"].includes(metric.status) ? metric.status : "unknown";
        statuses.set(JSON.stringify([String(campaign.campaign_id), key]), {
          campaignId: String(campaign.campaign_id),
          channel: campaign.group_key || "نامشخص",
          key,
          status,
        });
      });
    });
    return statuses;
  }
  function targetPeriodTransitionRows(current, previous, includedIds) {
    if (!current || !previous || current.campaign_list_truncated || previous.campaign_list_truncated) return null;
    const now = targetStatusByCampaign(current, includedIds);
    const before = targetStatusByCampaign(previous, includedIds);
    const grouped = new Map();
    Array.from(new Set([...now.keys(), ...before.keys()])).forEach((id) => {
      const oldItem = before.get(id);
      const newItem = now.get(id);
      const item = newItem || oldItem;
      const from = oldItem ? oldItem.status : "no_plan";
      const to = newItem ? newItem.status : "no_plan";
      const groupId = JSON.stringify([item.channel, item.key, from, to]);
      const group = grouped.get(groupId) || { channel: item.channel, key: item.key, from, to, campaigns: 0 };
      group.campaigns += 1;
      grouped.set(groupId, group);
    });
    return Array.from(grouped.values()).sort((a, b) =>
      a.channel.localeCompare(b.channel, "fa") || a.key.localeCompare(b.key)
        || a.from.localeCompare(b.from) || a.to.localeCompare(b.to));
  }
  function targetTransitionLabel(status) {
    return ({ met: "هدف محقق‌شده", not_met: "هدف محقق‌نشده",
      no_data: "دادهٔ کافی ثبت نشده", unknown: "نامشخص", no_plan: "هدف ثبت نشده" })[status] || "نامشخص";
  }
  function targetVarianceRows(portfolio) {
    if (!portfolio || portfolio.campaign_list_truncated) return [];
    const rows = [];
    (portfolio?.groups || []).forEach((group) => {
      Object.entries(group.metric_variances || {}).forEach(([key, values]) => {
        rows.push({ group: group.key, key, ...values });
      });
    });
    return rows.sort((a, b) => a.group.localeCompare(b.group, "fa") || a.key.localeCompare(b.key));
  }
  function renderTargetVarianceSummary(portfolio) {
    const body = byId("target-variance-summary");
    const note = byId("target-variance-summary-note");
    body.replaceChildren();
    if (!portfolio) {
      note.textContent = "تحلیل فاصلهٔ هدف و عملکرد در دسترس نیست.";
      return;
    }
    if (portfolio.campaign_list_truncated) {
      note.textContent = "به‌دلیل محدودیت تعداد کمپین‌ها، جمع‌بندی کامل نیست و نمایش داده نمی‌شود.";
      return;
    }
    note.textContent = "جمع‌بندی همهٔ کمپین‌های هدف‌دار در دامنهٔ انتخاب‌شده است. فاصله فقط برای پوشش کامل دوره محاسبه شده؛ هدف‌ها و عملکرد دوره‌های ناقص جدا هستند. اختلاف عددی علت را ثابت نمی‌کند.";
    const rows = targetVarianceRows(portfolio);
    if (!rows.length) {
      const row = document.createElement("tr");
      const cell = element("td", "muted", "هدف تعدادی برای جمع‌بندی ثبت نشده است.");
      cell.colSpan = 9;
      row.appendChild(cell);
      body.appendChild(row);
      return;
    }
    rows.forEach((item) => {
      const complete = item.complete_campaign_count > 0;
      const row = document.createElement("tr");
      row.append(
        element("td", "", item.group),
        element("td", "", targetMetricLabel(item.key)),
        element("td", "", formatNumber.format(item.targeted_campaign_count)),
        element("td", "", formatNumber.format(item.complete_campaign_count) + " / " + formatNumber.format(item.incomplete_campaign_count)),
        element("td", "", formatNumber.format(item.target_total)),
        element("td", "", complete ? formatNumber.format(item.complete_actual_total) : "نامشخص"),
        element("td", "", complete ? formatNumber.format(item.complete_variance) : "نامشخص"),
        element("td", "", formatNumber.format(item.incomplete_target_total)),
        element("td", "", formatNumber.format(item.partial_actual_total)),
      );
      body.appendChild(row);
    });
  }
  function renderTargetPeriodComparison(report, current, previous) {
    const body = byId("target-period-comparison");
    const note = byId("target-period-comparison-note");
    body.replaceChildren();
    const includedIds = new Set((report.campaigns || []).map((campaign) => String(campaign.campaign_id)));
    const rows = targetPeriodTransitionRows(current, previous, includedIds);
    if (rows === null) {
      note.textContent = "مقایسهٔ وضعیت هدف‌ها در دسترس نیست یا فهرست ارزیابی یکی از بازه‌ها ناقص است.";
      return;
    }
    note.textContent = "تغییرها توصیفی‌اند؛ فقط کمپین‌های مشترک گزارش شمرده می‌شوند و تغییر هدف یا نبود هدف به‌عنوان وضعیت جدا دیده می‌شود.";
    if (!rows.length) {
      const row = document.createElement("tr");
      const cell = element("td", "muted", "برای کمپین‌های مشترک در دو بازه هدفی برای مقایسه پیدا نشد.");
      cell.colSpan = 5;
      row.appendChild(cell);
      body.appendChild(row);
      return;
    }
    rows.forEach((item) => {
      const row = document.createElement("tr");
      row.append(element("td", "", item.channel),
        element("td", "", targetMetricLabel(item.key)),
        element("td", "", targetTransitionLabel(item.from)),
        element("td", "", targetTransitionLabel(item.to)),
        element("td", "", formatNumber.format(item.campaigns)));
      body.appendChild(row);
    });
  }
  function targetMetricLabel(key) {
    return ({ impressions: "نمایش", clicks: "کلیک", leads: "سرنخ", conversions: "تبدیل",
      spend: "هزینه", cost_per_lead: "هزینه به‌ازای سرنخ",
      cost_per_conversion: "هزینه به‌ازای تبدیل", roas: "بازده هزینهٔ تبلیغ" })[key] || key;
  }
  function targetValue(value, currency) {
    if (value === null || value === undefined) return "ثبت نشده";
    return currency ? displayAmount(value, currency) : formatNumber.format(Number(value));
  }
  function targetStatusLabel(status) {
    return ({ met: "هدف محقق‌شده", not_met: "هدف محقق‌نشده", no_data: "دادهٔ کافی ثبت نشده" })[status] || "نامشخص";
  }
  function renderCampaignTargetOutcomes(report, portfolio) {
    const body = byId("target-outcomes");
    const note = byId("target-outcomes-note");
    body.replaceChildren();
    if (!portfolio) {
      note.textContent = "دریافت ارزیابی هدف‌ها ممکن نشد؛ سایر بخش‌های گزارش در دسترس هستند.";
      const row = document.createElement("tr");
      const cell = element("td", "muted", "ارزیابی هدف‌ها در این گزارش در دسترس نیست.");
      cell.colSpan = 6;
      row.appendChild(cell);
      body.appendChild(row);
      return;
    }
    note.textContent = portfolio.campaign_list_truncated
      ? "فقط هدف‌های منطبق با بازه و کمپین‌های مشترک نمایش داده می‌شوند؛ فهرست هدف‌ها در API محدود شده است."
      : "هدف‌ها فقط برای همین بازهٔ گزارش و کمپین‌های مشترک نمایش داده می‌شوند.";
    const rows = campaignTargetRows(report, portfolio);
    if (!rows.length) {
      const row = document.createElement("tr");
      const cell = element("td", "muted", "برای کمپین‌های مشترک، هدفی با همین بازهٔ زمانی ثبت نشده است.");
      cell.colSpan = 6;
      row.appendChild(cell);
      body.appendChild(row);
      return;
    }
    rows.forEach((item) => {
      const row = document.createElement("tr");
      row.append(element("td", "", item.campaign),
        element("td", "", targetMetricLabel(item.key)),
        element("td", "", targetValue(item.target, item.currency)),
        element("td", "", targetValue(item.actual, item.currency)),
        element("td", "", targetStatusLabel(item.status)),
        element("td", "", formatNumber.format(Number(item.recorded_day_coverage_percent)) + "٪"));
      body.appendChild(row);
    });
  }
  function renderPeriodComparison(currentReport, previousReport, fields) {
    const body = byId("period-comparison");
    body.replaceChildren();
    const prior = precedingPeriod(fields);
    byId("period-comparison-period").textContent =
      "بازهٔ قبلی: " + prior.start + " تا " + prior.end + " · بازهٔ گزارش: " + fields.start + " تا " + fields.end;
    if (!previousReport) {
      const row = document.createElement("tr");
      const cell = element("td", "muted", "دادهٔ بازهٔ قبلی در دسترس نیست.");
      cell.colSpan = 5;
      row.appendChild(cell);
      body.appendChild(row);
      return;
    }
    comparisonRows(currentReport, previousReport).forEach((item) => {
      const row = document.createElement("tr");
      const change = item.delta === null ? "نامشخص" : comparisonValue(item.delta, item.currency);
      const percent = item.percent === null ? "نامشخص" : formatNumber.format(item.percent) + "٪";
      row.append(element("td", "", item.label + (item.currency ? " · " + item.currency : "")),
        element("td", "", comparisonValue(item.before, item.currency)),
        element("td", "", comparisonValue(item.now, item.currency)),
        element("td", "", change), element("td", "", percent));
      body.appendChild(row);
    });
  }
  function renderScenarioSummaries(scenarios) {
    const container = byId("scenario-results");
    container.replaceChildren();
    scenarios.forEach((scenario) => {
      const card = element("article", "scenario-card");
      card.appendChild(element("h3", "", scenario.name));
      const currencies = Object.keys(scenario.reconciliation_by_currency || {}).sort();
      if (!currencies.length) card.appendChild(element("p", "muted", "این سناریو تخصیصی برای مقایسه ندارد."));
      currencies.forEach((currency) => {
        const reconciliation = scenario.reconciliation_by_currency[currency];
        const block = element("div", "currency-card");
        block.appendChild(element("strong", "", "ارز " + currency));
        const facts = element("dl", "facts");
        addFact(facts, "بودجهٔ برنامه‌ریزی‌شده", displayAmount(reconciliation.planned_amount, currency));
        addFact(facts, "بودجه با هزینهٔ هم‌ارز", displayAmount(reconciliation.comparable_planned_amount, currency));
        addFact(facts, "هزینهٔ ثبت‌شده", displayAmount(reconciliation.observed_spend_amount, currency));
        addFact(facts, "فاصلهٔ بودجه و هزینه", displayAmount(reconciliation.variance_amount, currency));
        addFact(facts, "پوشش تخصیص‌های دارای هزینه", formatNumber.format(Number(reconciliation.allocation_coverage_percent)) + "٪");
        addFact(facts, "تخصیص با ارز متفاوت", formatNumber.format(Number(reconciliation.currency_mismatch_allocation_count)));
        block.appendChild(facts);
        card.appendChild(block);
      });
      container.appendChild(card);
    });
  }
  function metricText(metrics, key, title) {
    const metric = metrics[key] || {};
    const actual = metric.actual === null || metric.actual === undefined ? "ثبت نشده" : formatNumber.format(Number(metric.actual));
    return title + ": " + actual + " · پوشش " + formatNumber.format(Number(metric.recorded_day_coverage_percent || 0)) + "٪";
  }
  function renderCampaignRows(campaigns) {
    const body = byId("campaign-results");
    body.replaceChildren();
    campaigns.forEach((campaign) => {
      const row = document.createElement("tr");
      const title = element("td", "", campaign.campaign_name + " · " + campaign.channel);
      const spendCell = document.createElement("td");
      const currencies = Object.keys(campaign.recorded_spend_by_currency || {}).sort();
      spendCell.textContent = currencies.length
        ? currencies.map((currency) => displayAmount(campaign.recorded_spend_by_currency[currency], currency)).join(" · ")
        : "هزینه ثبت نشده";
      const metricCell = element("td", "", metricText(campaign.metrics, "leads", "سرنخ") + " | " + metricText(campaign.metrics, "conversions", "تبدیل"));
      const allocationsCell = document.createElement("td");
      campaign.scenario_allocations.forEach((allocation) => {
        const item = element("span", "allocation");
        item.appendChild(element("strong", "", allocation.scenario_name));
        item.appendChild(element("span", "", "بودجه: " + displayAmount(allocation.planned_budget_amount, allocation.planned_budget_currency)));
        const actual = allocation.actual_spend_in_allocation_currency;
        let actualDescription = displayAmount(actual, allocation.planned_budget_currency);
        if (actual === null || actual === undefined) {
          actualDescription = currencies.length ? "هزینه با ارز همسان ثبت نشده" : "هزینهٔ دوره ثبت نشده";
        }
        item.appendChild(element("small", "", "هزینهٔ هم‌ارز: " + actualDescription + " · واریانس: " + displayAmount(allocation.variance_amount, allocation.planned_budget_currency)));
        allocationsCell.appendChild(item);
      });
      row.append(title, spendCell, metricCell, allocationsCell);
      body.appendChild(row);
    });
  }
  function csvCell(value) {
    let text = value === null || value === undefined ? "" : String(value);
    if (typeof value === "string" && /^[\t\r\n ]*[=+@-]/.test(text)) text = "'" + text;
    return '"' + text.replace(/"/g, '""') + '"';
  }
  function exportComparisonCsv(result, fields) {
    const campaigns = result.campaigns || [];
    const scenarios = result.scenarios || [];
    const hasSpend = (campaign) => Object.keys(campaign.recorded_spend_by_currency || {}).length > 0;
    const hasMetric = (campaign, key) => {
      const metric = (campaign.metrics || {})[key] || {};
      return metric.actual !== null && metric.actual !== undefined;
    };
    const rows = [
      ["نوع رکورد", "از تاریخ", "تا تاریخ", "سناریو", "کمپین", "کانال", "ارز", "شاخص", "مقدار", "یادداشت"],
      ["بازه گزارش", fields.start, fields.end, "", "", "", "", "روز تقویمی", result.period_calendar_days, ""],
      ["پوشش شواهد", fields.start, fields.end, "", "", "", "", "سناریوی مقایسه‌شده", scenarios.length, ""],
      ["پوشش شواهد", fields.start, fields.end, "", "", "", "", "کمپین هم‌پوشان", campaigns.length, ""],
      ["پوشش شواهد", fields.start, fields.end, "", "", "", "", "کمپین دارای هزینهٔ ثبت‌شده", campaigns.filter(hasSpend).length, "از " + campaigns.length + " کمپین"],
      ["پوشش شواهد", fields.start, fields.end, "", "", "", "", "کمپین دارای دادهٔ سرنخ", campaigns.filter((campaign) => hasMetric(campaign, "leads")).length, "از " + campaigns.length + " کمپین"],
      ["پوشش شواهد", fields.start, fields.end, "", "", "", "", "کمپین دارای دادهٔ تبدیل", campaigns.filter((campaign) => hasMetric(campaign, "conversions")).length, "از " + campaigns.length + " کمپین"],
      ["پوشش شواهد", fields.start, fields.end, "", "", "", "", "نرخ پوشش هزینهٔ ثبت‌شده (درصد)", coverageRate(campaigns.filter(hasSpend).length, campaigns.length), campaigns.length ? "درصد از کمپین‌های هم‌پوشان" : "مخرج صفر؛ نامشخص"],
      ["پوشش شواهد", fields.start, fields.end, "", "", "", "", "نرخ پوشش دادهٔ سرنخ (درصد)", coverageRate(campaigns.filter((campaign) => hasMetric(campaign, "leads")).length, campaigns.length), campaigns.length ? "درصد از کمپین‌های هم‌پوشان" : "مخرج صفر؛ نامشخص"],
      ["پوشش شواهد", fields.start, fields.end, "", "", "", "", "نرخ پوشش دادهٔ تبدیل (درصد)", coverageRate(campaigns.filter((campaign) => hasMetric(campaign, "conversions")).length, campaigns.length), campaigns.length ? "درصد از کمپین‌های هم‌پوشان" : "مخرج صفر؛ نامشخص"],
    ];
    campaigns.forEach((campaign) => {
      missingEvidence(campaign).forEach((missing) => rows.push([
        "شکاف شواهد", fields.start, fields.end, "", campaign.campaign_name,
        campaignChannel(campaign), "", missing, "", "",
      ]));
    });
    channelCoverage(campaigns).forEach((group) => {
      [
        ["کمپین", group.campaigns],
        ["کمپین دارای هزینهٔ ثبت‌شده", group.spend],
        ["کمپین دارای دادهٔ سرنخ", group.leads],
        ["کمپین دارای دادهٔ تبدیل", group.conversions],
      ].forEach(([metric, count]) => rows.push([
        "پوشش کانال", fields.start, fields.end, "", "", group.channel, "", metric, count, "",
      ]));
      [
        ["نرخ پوشش هزینهٔ ثبت‌شده (درصد)", coverageRate(group.spend, group.campaigns)],
        ["نرخ پوشش دادهٔ سرنخ (درصد)", coverageRate(group.leads, group.campaigns)],
        ["نرخ پوشش دادهٔ تبدیل (درصد)", coverageRate(group.conversions, group.campaigns)],
      ].forEach(([metric, rate]) => rows.push([
        "پوشش کانال", fields.start, fields.end, "", "", group.channel, "", metric, rate,
        "درصد از " + group.campaigns + " کمپین کانال",
      ]));
    });
    if (latestPreviousComparison) {
      comparisonRows(result, latestPreviousComparison).forEach((item) => rows.push([
        "مقایسه با بازه قبلی", fields.start, fields.end, "", "", "", item.currency,
        item.label + " · تغییر", item.delta,
        "بازه قبلی " + precedingPeriod(fields).start + " تا " + precedingPeriod(fields).end
          + "؛ مقدار قبلی: " + (item.before ?? "ثبت نشده") + "؛ مقدار جاری: " + (item.now ?? "ثبت نشده")
          + "؛ درصد تغییر: " + (item.percent === null ? "نامشخص" : item.percent + "٪"),
      ]));
      channelComparisonRows(result, latestPreviousComparison).forEach((item) => rows.push([
        "مقایسه کانال", fields.start, fields.end, "", "", item.channel, item.currency,
        item.label + " · تغییر", item.delta,
        "بازه قبلی " + precedingPeriod(fields).start + " تا " + precedingPeriod(fields).end
          + "؛ مقدار قبلی: " + (item.before ?? "ثبت نشده") + "؛ مقدار جاری: " + (item.now ?? "ثبت نشده")
          + "؛ درصد تغییر: " + (item.percent === null ? "نامشخص" : item.percent + "٪"),
      ]));
      compareUnitCosts(result, latestPreviousComparison).forEach((item) => rows.push([
        "هزینهٔ واحد ثبت‌شده", fields.start, fields.end, "", "", item.channel, item.currency,
        item.key === "leads" ? "هزینه به‌ازای هر سرنخ" : "هزینه به‌ازای هر تبدیل",
        item.nowCost,
        "بازه قبلی " + precedingPeriod(fields).start + " تا " + precedingPeriod(fields).end
          + "؛ هزینه واحد قبلی: " + (item.beforeCost ?? "نامشخص")
          + "؛ مجموع شاخص جاری: " + (item.now?.metricTotal ?? "ثبت نشده")
          + "؛ درصد تغییر: " + (item.percent === null ? "نامشخص" : item.percent + "٪")
          + "؛ کمپین‌های چندارزی از محاسبه حذف شده‌اند",
      ]));
      campaignTargetRows(result, latestTargetPortfolio).forEach((item) => rows.push([
        "وضعیت هدف کمپین", fields.start, fields.end, "", item.campaign, item.channel, item.currency || "",
        targetMetricLabel(item.key) + " · هدف", item.actual,
        "هدف: " + item.target + "؛ وضعیت: " + targetStatusLabel(item.status)
          + "؛ پوشش روزهای ثبت‌شده: " + item.recorded_day_coverage_percent + "٪",
      ]));
      channelTargetSummaryRows(latestTargetPortfolio,
        new Set(campaigns.map((campaign) => String(campaign.campaign_id)))).forEach((item) => rows.push([
        "خلاصه هدف کانال", fields.start, fields.end, "", "", item.channel, "",
        targetMetricLabel(item.key), item.campaigns,
        "محقق‌شده: " + item.met + "؛ محقق‌نشده: " + item.notMet
          + "؛ داده ناکافی: " + item.noData + "؛ نامشخص: " + item.unknown,
      ]));
      targetVarianceRows(latestTargetPortfolio).forEach((item) => rows.push([
        "فاصله هدف و عملکرد", fields.start, fields.end, "", "", item.group, "",
        targetMetricLabel(item.key) + " · فاصلهٔ دورهٔ کامل",
        item.complete_campaign_count > 0 ? item.complete_variance : "",
        "تعداد هدف‌دار: " + item.targeted_campaign_count
          + "؛ دورهٔ کامل: " + item.complete_campaign_count
          + "؛ عملکرد کامل: " + (item.complete_campaign_count > 0 ? item.complete_actual_total : "نامشخص")
          + "؛ جمع هدف: " + item.target_total
          + "؛ هدف دوره ناقص: " + item.incomplete_target_total
          + "؛ عملکرد ناقص ثبت‌شده: " + item.partial_actual_total
          + "؛ اختلاف عددی است و علت را ثابت نمی‌کند",
      ]));
      compareLeadConversionRates(result, latestPreviousComparison).forEach((item) => rows.push([
        "نسبت تبدیل به سرنخ", fields.start, fields.end, "", "", item.channel, "",
        "تبدیل ثبت‌شده به سرنخ ثبت‌شده (درصد)", item.current?.rate ?? "",
        "بازه قبلی " + precedingPeriod(fields).start + " تا " + precedingPeriod(fields).end
          + "؛ نرخ قبلی: " + (item.previous?.rate ?? "نامشخص")
          + "؛ تغییر واحد درصد: " + (item.delta === null ? "نامشخص" : item.delta)
          + "؛ کمپین‌های قبلی: " + (item.previous?.campaigns ?? 0)
          + "؛ کمپین‌های جاری: " + (item.current?.campaigns ?? 0)
          + "؛ فقط داده‌های هم‌زمان و سرنخ مثبت",
      ]));
      const targetTransitions = targetPeriodTransitionRows(latestTargetPortfolio, latestPreviousTargetPortfolio,
        new Set(campaigns.map((campaign) => String(campaign.campaign_id))));
      (targetTransitions || []).forEach((item) => rows.push([
        "تغییر وضعیت هدف", fields.start, fields.end, "", "", item.channel, "",
        targetMetricLabel(item.key) + " · " + targetTransitionLabel(item.from) + " ← " + targetTransitionLabel(item.to),
        item.campaigns, "ارزیابی وضعیت هدف در بازه‌های هم‌طول",
      ]));
    }
    (result.scenarios || []).forEach((scenario) => {
      Object.keys(scenario.reconciliation_by_currency || {}).sort().forEach((currency) => {
        const values = scenario.reconciliation_by_currency[currency];
        [
          ["بودجه برنامه‌ریزی‌شده", values.planned_amount],
          ["بودجه دارای هزینه هم‌ارز", values.comparable_planned_amount],
          ["هزینه ثبت‌شده", values.observed_spend_amount],
          ["فاصله بودجه و هزینه", values.variance_amount],
          ["پوشش تخصیص‌های دارای هزینه (درصد)", values.allocation_coverage_percent],
          ["تخصیص با ارز متفاوت (تعداد)", values.currency_mismatch_allocation_count],
        ].forEach(([metric, value]) => rows.push([
          "سناریو", fields.start, fields.end, scenario.name, "", "", currency, metric, value, "",
        ]));
      });
    });
    (result.campaigns || []).forEach((campaign) => {
      Object.keys(campaign.recorded_spend_by_currency || {}).sort().forEach((currency) => {
        rows.push(["کمپین", fields.start, fields.end, "", campaign.campaign_name, campaign.channel,
          currency, "هزینه ثبت‌شده", campaign.recorded_spend_by_currency[currency], ""]);
      });
      ["leads", "conversions"].forEach((key) => {
        const metric = (campaign.metrics || {})[key] || {};
        rows.push(["کمپین", fields.start, fields.end, "", campaign.campaign_name, campaign.channel,
          "", key === "leads" ? "سرنخ" : "تبدیل", metric.actual,
          (metric.actual === null || metric.actual === undefined ? "مقدار ثبت نشده؛ " : "") + "پوشش روزهای ثبت‌شده: " + (metric.recorded_day_coverage_percent ?? "نامشخص") + "٪"]);
      });
      (campaign.scenario_allocations || []).forEach((allocation) => {
        const currency = allocation.planned_budget_currency || "";
        rows.push(["تخصیص", fields.start, fields.end, allocation.scenario_name, campaign.campaign_name,
          campaign.channel, currency, "بودجه برنامه‌ریزی‌شده", allocation.planned_budget_amount, ""]);
        rows.push(["تخصیص", fields.start, fields.end, allocation.scenario_name, campaign.campaign_name,
          campaign.channel, currency, "هزینه هم‌ارز", allocation.actual_spend_in_allocation_currency,
          allocation.actual_spend_in_allocation_currency === null ? "هزینه هم‌ارز ثبت نشده" : ""]);
        rows.push(["تخصیص", fields.start, fields.end, allocation.scenario_name, campaign.campaign_name,
          campaign.channel, currency, "واریانس", allocation.variance_amount, ""]);
      });
    });
    objectiveBudgetRows(result).forEach((item) => rows.push([
      "تطبیق بودجه بر اساس هدف", fields.start, fields.end, item.scenario, "", "",
      item.currency, item.objective, item.comparableAllocations ? item.observedSpend : "",
      "بودجه برنامه‌ریزی‌شده: " + item.planned + "؛ سهم از بودجه سناریو: " + (item.mixSharePercent === null ? "نامشخص" : item.mixSharePercent)
        + "٪؛ بودجه تخصیص‌های قابل‌مقایسه: " + item.comparablePlanned
        + "؛ واریانس: " + (item.comparableAllocations ? item.variance : "نامشخص")
        + "؛ پوشش تخصیص: " + item.comparableAllocations + " از " + item.allocations,
    ]));
    compareObjectivePerformance(result, latestPreviousComparison).forEach((item) => rows.push([
      "عملکرد هدف بازاریابی", fields.start, fields.end, "", "", item.channel, "",
      item.objective + " · " + (item.key === "leads" ? "سرنخ ثبت‌شده" : "تبدیل ثبت‌شده"),
      item.current ?? "",
      "جمع بازهٔ قبلی: " + (item.previous ?? "ثبت نشده")
        + "؛ تغییر: " + (item.delta === null ? "نامشخص" : item.delta)
        + "؛ پوشش قبلی: " + item.previousCoverage.observed + " از " + item.previousCoverage.campaigns
        + "؛ پوشش جاری: " + item.currentCoverage.observed + " از " + item.currentCoverage.campaigns,
    ]));
    scenarioObjectiveEvidenceRows(result).forEach((item) => rows.push([
      "سناریو و شواهد هدف", fields.start, fields.end, item.scenario, "",
      item.objective, item.currency, "بودجهٔ برنامه‌ریزی‌شده", item.planned,
      "سهم از بودجه: " + (item.mixSharePercent === null ? "نامشخص" : item.mixSharePercent + "٪")
        + "؛ هزینهٔ هر سرنخ: " + (item.leads ? item.leads.unitCost ?? "نامشخص" : "بدون سابقه")
        + "؛ پوشش سرنخ: " + (item.leads ? item.leads.observed + " از " + item.leads.campaigns : "بدون سابقه")
        + "؛ هزینهٔ هر تبدیل: " + (item.conversions ? item.conversions.unitCost ?? "نامشخص" : "بدون سابقه")
        + "؛ پوشش تبدیل: " + (item.conversions ? item.conversions.observed + " از " + item.conversions.campaigns : "بدون سابقه"),
    ]));
    objectiveUnitCostRows(result).forEach((item) => rows.push([
      "هزینهٔ واحد هدف بازاریابی", fields.start, fields.end, "", "",
      item.objective + " · " + (item.key === "leads" ? "سرنخ ثبت‌شده" : "تبدیل ثبت‌شده"),
      item.currency, "هزینهٔ واحد هدف", item.unitCost ?? "",
      "هزینهٔ واردشده: " + (item.spend === null ? "ثبت نشده" : item.spend)
        + "؛ مجموع شاخص: " + (item.outcomes === null ? "ثبت نشده" : item.outcomes)
        + "؛ پوشش: " + item.observed + " از " + item.campaigns
        + "؛ کمپین چندارزی به ارز خاصی نسبت داده نمی‌شود",
    ]));
    objectiveUnitCostDistributionRows(result).forEach((item) => rows.push([
      "پراکندگی هزینهٔ واحد هدف", fields.start, fields.end, "", "",
      item.objective + " · " + (item.key === "leads" ? "هزینه به‌ازای سرنخ" : "هزینه به‌ازای تبدیل"),
      item.currency, "میانه و دامنهٔ کمپین", item.median,
      "تعداد کمپین: " + item.count + "؛ کمترین: " + item.minimum + "؛ بیشترین: " + item.maximum,
    ]));
    campaignUnitCostRows(result, latestPreviousComparison).forEach((item) => rows.push([
      "هزینهٔ واحد کمپین", fields.start, fields.end, "", item.campaign, item.channel, item.currency,
      item.key === "leads" ? "هزینه به‌ازای سرنخ" : "هزینه به‌ازای تبدیل",
      item.current.value ?? "",
      "هزینهٔ واحد قبلی: " + (item.previous.value === null ? unitCostReason(item.previousReason || item.previous.reason) : item.previous.value)
        + "؛ هزینهٔ واحد جاری: " + (item.current.value === null ? unitCostReason(item.current.reason) : item.current.value)
        + "؛ درصد تغییر: " + (item.percent === null ? "نامشخص" : item.percent + "٪")
        + "؛ نسبت فقط با ارز همسان مقایسه می‌شود",
    ]));
    const csv = "\uFEFF" + rows.map((row) => row.map(csvCell).join(",")).join("\r\n") + "\r\n";
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "budget-comparison-" + fields.start + "-" + fields.end + ".csv";
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
  byId("export-csv").addEventListener("click", () => {
    if (!latestComparison || !latestFields) return;
    try {
      exportComparisonCsv(latestComparison, latestFields);
      setStatus("فایل CSV گزارش آماده شد.", false);
    } catch (_) {
      setStatus("ساخت فایل CSV ناموفق بود؛ دوباره تلاش کنید.", true);
    }
  });
  async function loadScenarios() {
    clearResults();
    scenarioPanel.hidden = true;
    try {
      const fields = selectedRequestFields();
      setStatus("در حال دریافت سناریوهای مجاز…", false);
      byId("load-scenarios").disabled = true;
      const scenarios = await loadAllScenarios(fields);
      renderScenarioOptions(scenarios);
      scenarioPanel.hidden = false;
      setStatus(scenarios.length + " سناریو بارگذاری شد.", false);
      const requestedIds = Array.from(new Set(requestedScenarioIds.filter(Boolean)));
      if (requestedIds.length >= 2 && requestedIds.length <= 5
          && requestedIds.length === requestedScenarioIds.length) {
        const checkboxes = Array.from(listNode.querySelectorAll('input[type="checkbox"]'));
        const availableIds = new Set(checkboxes.map((checkbox) => checkbox.value));
        if (requestedIds.every((id) => availableIds.has(id))) {
          checkboxes.forEach((checkbox) => { checkbox.checked = requestedIds.includes(checkbox.value); });
          updateSelectionCount();
          await compareScenarios();
        }
      }
    } catch (error) {
      setStatus(error.message || "دریافت سناریوها ناموفق بود.", true);
    } finally {
      byId("load-scenarios").disabled = false;
    }
  }
  async function compareScenarios() {
    clearResults();
    try {
      const fields = selectedRequestFields();
      const ids = selectedIds();
      if (ids.length < 2 || ids.length > 5) throw new Error("برای مقایسه ۲ تا ۵ سناریو را انتخاب کنید.");
      const query = new URLSearchParams({ period_start: fields.start, period_end: fields.end });
      ids.forEach((id) => query.append("scenario_ids", id));
      setStatus("در حال محاسبهٔ مقایسه…", false);
      byId("compare").disabled = true;
      const result = await getJson("/api/v1/crm/budget-scenarios/compare/performance-context?" + query.toString(), fields.workspace);
      const prior = precedingPeriod(fields);
      const priorQuery = new URLSearchParams({ period_start: prior.start, period_end: prior.end });
      ids.forEach((id) => priorQuery.append("scenario_ids", id));
      let previousResult = null;
      try {
        previousResult = await getJson("/api/v1/crm/budget-scenarios/compare/performance-context?" + priorQuery.toString(), fields.workspace);
      } catch (_) {}
      renderEvidenceCoverage(result);
      renderChannelCoverage(result.campaigns || []);
      renderEvidenceGaps(result.campaigns || []);
      renderScenarioSummaries(result.scenarios || []);
      renderCampaignRows(result.campaigns || []);
      renderPeriodComparison(result, previousResult, fields);
      renderChannelPeriodComparison(result, previousResult);
      renderUnitCostComparison(result, previousResult);
      renderLeadConversionRatio(result, previousResult);
      renderCampaignUnitCosts(result, previousResult);
      renderObjectiveUnitCosts(result);
      renderObjectiveUnitCostDistribution(result);
      renderScenarioObjectiveEvidence(result);
      renderObjectivePerformance(result, previousResult);
      renderObjectiveBudgetReconciliation(result);
      const targetQuery = new URLSearchParams({
        period_start: fields.start,
        period_end: fields.end,
        organization_unit_id: fields.organization,
        grouped_by: "channel",
      });
      let targetPortfolio = null;
      try {
        targetPortfolio = await getJson("/api/v1/crm/analytics/campaign-target-performance/portfolio?" + targetQuery.toString(), fields.workspace);
      } catch (_) {}
      const previousTargetQuery = new URLSearchParams({
        period_start: prior.start,
        period_end: prior.end,
        organization_unit_id: fields.organization,
        grouped_by: "channel",
      });
      let previousTargetPortfolio = null;
      try {
        previousTargetPortfolio = await getJson("/api/v1/crm/analytics/campaign-target-performance/portfolio?" + previousTargetQuery.toString(), fields.workspace);
      } catch (_) {}
      renderCampaignTargetOutcomes(result, targetPortfolio);
      renderChannelTargetSummary(result, targetPortfolio);
      renderTargetVarianceSummary(targetPortfolio);
      renderTargetPeriodComparison(result, targetPortfolio, previousTargetPortfolio);
      updateReportUrl(fields, ids);
      latestComparison = result;
      latestPreviousComparison = previousResult;
      latestTargetPortfolio = targetPortfolio;
      latestPreviousTargetPortfolio = previousTargetPortfolio;
      latestFields = fields;
      resultsPanel.hidden = false;
      setStatus("گزارش برای " + result.period_calendar_days + " روز تقویمی آماده شد.", false);
    } catch (error) {
      setStatus(error.message || "ساخت گزارش ناموفق بود.", true);
    } finally {
      updateSelectionCount();
    }
  }
  byId("load-scenarios").addEventListener("click", loadScenarios);
  byId("compare").addEventListener("click", compareScenarios);
  workspaceInput.addEventListener("change", async () => {
    scenarioPanel.hidden = true;
    clearResults();
    setStatus("", false);
    if (!workspaceInput.value) {
      organizationInput.replaceChildren();
      return;
    }
    try { await loadOrganizationChoices(); }
    catch (error) { setStatus(error.message || "دریافت واحدهای مجاز ناموفق بود.", true); }
  });
  [organizationInput, byId("period-start"), byId("period-end")].forEach((input) => {
    input.addEventListener("change", () => {
      scenarioPanel.hidden = true;
      clearResults();
      setStatus("", false);
    });
  });
  loadContextChoices().catch((error) => {
    setStatus(error.message || "دریافت فضاهای کاری ناموفق بود.", true);
  });
  updateSelectionCount();
})();"""

_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; "
        "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


@router.get("/workspace/budget-scenario-comparison", response_class=HTMLResponse)
async def budget_scenario_comparison_page() -> HTMLResponse:
    """Serve a data-free shell; protected API calls still enforce user permissions."""
    return HTMLResponse(_PAGE, headers=_SECURITY_HEADERS)


@router.get("/assets/budget-scenario-comparison.js")
async def budget_scenario_comparison_script() -> Response:
    """Serve the same-origin client with a restrictive script policy."""
    return Response(
        _CLIENT_SCRIPT,
        media_type="application/javascript",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
