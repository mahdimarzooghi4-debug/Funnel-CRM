"""Versioned glossary of marketing metrics exposed by CRM analytics."""

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import has_crm_permission
from funnel_crm.platform.models import AuditEvent
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/crm/analytics/metrics", tags=["CRM marketing metric catalog"])

CATALOG_VERSION = "1.0"
COMMERCE_PERMISSION = "crm.commerce_event:view"


class MetricDefinition(BaseModel):
    key: str
    name: str
    category: Literal["campaign_activity", "funnel_rates", "marketing_cost", "commerce", "data_quality"]
    description: str
    formula: str
    source: str
    aggregation: str
    dimensions: list[str]
    unit: str
    currency_behavior: str
    missing_data_behavior: str
    limitations: str
    endpoint: str
    required_permissions: list[str]


class MetricCatalog(BaseModel):
    catalog_version: str
    organization_unit_id: UUID
    generated_at: datetime
    metrics: list[MetricDefinition]


_METRICS = [
    MetricDefinition(
        key=key, name=name, category="campaign_activity",
        description=f"مقدار ثبت‌شدهٔ {name} برای کمپین در بازهٔ گزارش.",
        formula=f"جمع مقادیر روزانهٔ غیرتهیِ {key}",
        source="CRMMarketingCampaignMeasurement",
        aggregation="جمع روزانه در سطح کمپین؛ در گزارش‌های سبد، جمع کمپین‌های مجاز.",
        dimensions=["campaign", "channel", "objective", "date"],
        unit="count", currency_behavior="بدون ارز",
        missing_data_behavior="روز بدون مقدار حذف می‌شود؛ به‌عنوان صفر تفسیر نمی‌شود.",
        limitations="کیفیت و کامل‌بودن گزارش‌دهی کانال را تضمین نمی‌کند.",
        endpoint="/api/v1/crm/analytics/campaign-performance",
        required_permissions=["crm.campaign:view"],
    )
    for key, name in [
        ("impressions", "نمایش"),
        ("reach", "دسترسی"),
        ("clicks", "کلیک"),
        ("responses", "پاسخ"),
        ("leads", "سرنخ"),
        ("conversions", "تبدیل"),
        ("return_count", "تعداد مرجوعی گزارش‌شده"),
    ]
]
_METRICS.extend([
    MetricDefinition(
        key="click_through_rate", name="نرخ کلیک به نمایش", category="funnel_rates",
        description="سهم کلیک از نمایش در روزهایی که هر دو مقدار ثبت شده‌اند.",
        formula="100 × جمع کلیک روزهای جفت‌شده ÷ جمع نمایش همان روزها",
        source="CRMMarketingCampaignMeasurement: clicks, impressions",
        aggregation="نسبت مجموع صورت و مخرجِ روزهای دارای هر دو مقدار؛ میانگین نرخ روزانه نیست.",
        dimensions=["campaign", "channel", "objective", "date range"],
        unit="percent", currency_behavior="بدون ارز",
        missing_data_behavior="روز فاقد کلیک یا نمایش از هر دو مجموع کنار گذاشته می‌شود؛ مخرج صفر، مقدار ندارد.",
        limitations="وابسته به تعریف و گزارش‌دهی پلتفرم برای نمایش و کلیک است.",
        endpoint="/api/v1/crm/analytics/campaign-performance",
        required_permissions=["crm.campaign:view"],
    ),
    MetricDefinition(
        key="lead_rate_per_click", name="نرخ سرنخ به کلیک", category="funnel_rates",
        description="سهم سرنخ از کلیک، فقط در روزهای دارای هر دو داده.",
        formula="100 × جمع سرنخ روزهای جفت‌شده ÷ جمع کلیک همان روزها",
        source="CRMMarketingCampaignMeasurement: leads, clicks",
        aggregation="نسبت مجموع مقادیر روزهای جفت‌شده؛ میانگین نرخ روزانه نیست.",
        dimensions=["campaign", "channel", "objective", "date range"],
        unit="percent", currency_behavior="بدون ارز",
        missing_data_behavior="روزهای فاقد یکی از دو مقدار کنار گذاشته می‌شوند؛ مخرج صفر، مقدار ندارد.",
        limitations="ارتباط زمانی گزارش‌شده را نشان می‌دهد و انتساب علّی نیست.",
        endpoint="/api/v1/crm/analytics/campaign-performance",
        required_permissions=["crm.campaign:view"],
    ),
    MetricDefinition(
        key="conversion_rate_per_click", name="نرخ تبدیل به کلیک", category="funnel_rates",
        description="سهم تبدیل از کلیک، فقط در روزهای دارای هر دو داده.",
        formula="100 × جمع تبدیل روزهای جفت‌شده ÷ جمع کلیک همان روزها",
        source="CRMMarketingCampaignMeasurement: conversions, clicks",
        aggregation="نسبت مجموع مقادیر روزهای جفت‌شده؛ میانگین نرخ روزانه نیست.",
        dimensions=["campaign", "channel", "objective", "date range"],
        unit="percent", currency_behavior="بدون ارز",
        missing_data_behavior="روزهای فاقد یکی از دو مقدار کنار گذاشته می‌شوند؛ مخرج صفر، مقدار ندارد.",
        limitations="تعریف تبدیل میان کانال‌ها ممکن است متفاوت باشد؛ انتساب علّی نیست.",
        endpoint="/api/v1/crm/analytics/campaign-performance",
        required_permissions=["crm.campaign:view"],
    ),
    MetricDefinition(
        key="actual_spend", name="هزینهٔ ثبت‌شده", category="marketing_cost",
        description="هزینهٔ واقعی واردشده برای کمپین؛ هر ارز جداگانه گزارش می‌شود.",
        formula="جمع actual_spend_amount برای هر actual_spend_currency",
        source="CRMMarketingCampaignMeasurement: actual_spend_amount, actual_spend_currency",
        aggregation="جمع مقادیر غیرتهی به تفکیک کمپین و ارز.",
        dimensions=["campaign", "channel", "objective", "currency", "date range"],
        unit="money", currency_behavior="هر ارز جدا؛ تبدیل ارز انجام نمی‌شود.",
        missing_data_behavior="ردیف فاقد مبلغ هزینه وارد جمع نمی‌شود.",
        limitations="هزینهٔ ثبت‌شده است و الزاماً صورت‌حساب نهایی یا کل هزینهٔ کانال نیست.",
        endpoint="/api/v1/crm/analytics/campaign-performance",
        required_permissions=["crm.campaign:view"],
    ),
    MetricDefinition(
        key="cost_per_lead", name="هزینه به‌ازای سرنخ", category="marketing_cost",
        description="هزینهٔ ثبت‌شده تقسیم بر سرنخ‌های ثبت‌شده در روزهای مشترک.",
        formula="جمع هزینه ÷ جمع سرنخ، فقط برای روزهای دارای هر دو داده و ارز همسان",
        source="CRMMarketingCampaignMeasurement: actual spend, leads",
        aggregation="نسبت مجموع‌های جفت‌شده به تفکیک ارز؛ نه میانگین روزانه.",
        dimensions=["campaign", "currency", "date range"],
        unit="money per lead", currency_behavior="محاسبهٔ جدا برای هر ارز؛ تبدیل ارز ندارد.",
        missing_data_behavior="بدون روز جفت‌شده یا با مجموع سرنخ صفر، مقدار ندارد.",
        limitations="به ثبت کامل و سازگار هزینه و سرنخ وابسته است.",
        endpoint="/api/v1/crm/analytics/campaign-performance",
        required_permissions=["crm.campaign:view"],
    ),
    MetricDefinition(
        key="cost_per_conversion", name="هزینه به‌ازای تبدیل", category="marketing_cost",
        description="هزینهٔ ثبت‌شده تقسیم بر تبدیل‌های ثبت‌شده در روزهای مشترک.",
        formula="جمع هزینه ÷ جمع تبدیل، فقط برای روزهای دارای هر دو داده و ارز همسان",
        source="CRMMarketingCampaignMeasurement: actual spend, conversions",
        aggregation="نسبت مجموع‌های جفت‌شده به تفکیک ارز؛ نه میانگین روزانه.",
        dimensions=["campaign", "currency", "date range"],
        unit="money per conversion", currency_behavior="محاسبهٔ جدا برای هر ارز؛ تبدیل ارز ندارد.",
        missing_data_behavior="بدون روز جفت‌شده یا با مجموع تبدیل صفر، مقدار ندارد.",
        limitations="به تعریف تبدیل و ثبت کامل داده‌ها وابسته است.",
        endpoint="/api/v1/crm/analytics/campaign-performance",
        required_permissions=["crm.campaign:view"],
    ),
    MetricDefinition(
        key="reported_attributed_revenue", name="درآمد انتساب‌یافتهٔ گزارش‌شده", category="marketing_cost",
        description="مبلغ درآمدی که در اندازه‌گیری روزانه به کمپین نسبت داده و ثبت شده است.",
        formula="جمع attributed_revenue_amount به تفکیک ارز",
        source="CRMMarketingCampaignMeasurement: attributed_revenue_amount, attributed_revenue_currency",
        aggregation="جمع روزانه و گروه‌بندی بر اساس ارز.",
        dimensions=["campaign", "currency", "date range"],
        unit="money", currency_behavior="هر ارز جدا؛ تبدیل ارز انجام نمی‌شود.",
        missing_data_behavior="ردیف فاقد مبلغ درآمد کنار گذاشته می‌شود.",
        limitations="ورودی گزارش‌شده است؛ این کاتالوگ آن را از رویداد سفارش یا انتساب علّی تأیید نمی‌کند.",
        endpoint="/api/v1/crm/analytics/campaign-performance",
        required_permissions=["crm.campaign:view"],
    ),
    MetricDefinition(
        key="reported_roas", name="ROAS گزارش‌شده", category="marketing_cost",
        description="درآمد انتساب‌یافتهٔ گزارش‌شده نسبت به هزینهٔ کمپین.",
        formula="جمع درآمد و هزینهٔ روزهای جفت‌شده با ارز برابر؛ درآمد ÷ هزینه",
        source="CRMMarketingCampaignMeasurement: attributed_revenue_amount, attributed_revenue_currency, actual_spend_amount, actual_spend_currency",
        aggregation="نسبت مجموع‌های روزهای دارای هر دو مبلغ و ارز یکسان.",
        dimensions=["campaign", "currency", "date range"],
        unit="multiple", currency_behavior="فقط ارزهای یکسان با هم تقسیم می‌شوند؛ تبدیل ارز ندارد.",
        missing_data_behavior="بدون روز جفت‌شده یا با هزینهٔ صفر، مقدار ندارد.",
        limitations="با paid_to_spend مبتنی بر رویدادهای تجارت فرق دارد؛ انتساب علّی یا درآمد حسابداری نیست.",
        endpoint="/api/v1/crm/analytics/campaign-performance",
        required_permissions=["crm.campaign:view"],
    ),
    MetricDefinition(
        key="paid_amount", name="مبلغ پرداخت ثبت‌شده", category="commerce",
        description="جمع رویدادهای پرداختی که صریحاً به شناسهٔ کمپین متصل شده‌اند.",
        formula="جمع amount رویدادهای paid متصل به کمپین، به تفکیک ارز",
        source="CRMProductCommerceEvent با event_kind=paid و campaign_id مشخص",
        aggregation="جمع رویدادهای بازه؛ ارزها جدا هستند.",
        dimensions=["campaign", "currency", "date range", "source product"],
        unit="money", currency_behavior="هر ارز جدا؛ تبدیل ارز انجام نمی‌شود.",
        missing_data_behavior="فقط رویدادهای ثبت‌شده با پیوند صریح کمپین شمرده می‌شوند.",
        limitations="پیوند صریح به کمپین اثبات اثرگذاری یا انتساب علّی نیست.",
        endpoint="/api/v1/crm/analytics/campaign-commerce-efficiency",
        required_permissions=["crm.campaign:view", COMMERCE_PERMISSION],
    ),
    MetricDefinition(
        key="paid_order_count", name="تعداد سفارش‌های پرداخت‌شده", category="commerce",
        description="تعداد سفارش‌های متمایز دارای رویداد پرداخت که صریحاً به کمپین متصل شده‌اند.",
        formula="تعداد یکتای (محصول مبدأ، مرجع سفارش) برای رویدادهای paid متصل به کمپین",
        source="CRMProductCommerceEvent با event_kind=paid و campaign_id مشخص",
        aggregation="هر سفارش برای هر محصول مبدأ یک‌بار شمرده می‌شود.",
        dimensions=["campaign", "date range", "source product"],
        unit="count", currency_behavior="بدون ارز",
        missing_data_behavior="فقط سفارش‌های دارای رویداد پرداخت ثبت‌شده شمرده می‌شوند.",
        limitations="تکرار رویدادهای پرداخت همان سفارش حذف می‌شود؛ اتصال کمپین اثبات اثر علّی نیست.",
        endpoint="/api/v1/crm/campaign-experiments/{experiment_id}/readout",
        required_permissions=["crm.campaign:view", COMMERCE_PERMISSION],
    ),
    MetricDefinition(
        key="average_paid_order_value", name="میانگین ارزش سفارش پرداخت‌شده", category="commerce",
        description="میانگین مبلغ پرداختی سفارش‌های یکتای ثبت‌شده برای کمپین، به تفکیک ارز.",
        formula="مجموع رویدادهای paid هر سفارش ÷ تعداد سفارش‌های یکتای دارای رویداد paid",
        source="CRMProductCommerceEvent با event_kind=paid و campaign_id مشخص",
        aggregation="پرداخت‌های جزئی هر سفارش ابتدا جمع و سپس هر سفارش یک‌بار در میانگین لحاظ می‌شود.",
        dimensions=["campaign", "currency", "date range", "source product"],
        unit="money per order", currency_behavior="هر ارز جدا؛ تبدیل ارز انجام نمی‌شود.",
        missing_data_behavior="بدون سفارش paid با رویداد ثبت‌شده در ارز انتخاب‌شده، مقدار ناموجود است.",
        limitations="میانگین شامل رویدادهای پرداخت ثبت‌شده در بازه است؛ اتصالی صریح به کمپین اثبات اثر علّی نیست.",
        endpoint="/api/v1/crm/campaign-experiments/{experiment_id}/readout",
        required_permissions=["crm.campaign:view", COMMERCE_PERMISSION],
    ),
    MetricDefinition(
        key="average_refund_per_order", name="میانگین بازپرداخت هر سفارش", category="commerce",
        description="میانگین مجموع رویدادهای بازپرداخت برای هر سفارش یکتا، به تفکیک ارز.",
        formula="جمع رویدادهای refunded هر سفارش ÷ تعداد سفارش‌های یکتای دارای بازپرداخت",
        source="CRMProductCommerceEvent با event_kind=refunded و campaign_id مشخص",
        aggregation="بازپرداخت‌های جزئی هر سفارش ابتدا جمع و سپس هر سفارش یک‌بار در میانگین لحاظ می‌شود.",
        dimensions=["campaign", "currency", "date range", "source product"],
        unit="money per order", currency_behavior="هر ارز جدا؛ تبدیل ارز انجام نمی‌شود.",
        missing_data_behavior="بدون سفارش دارای بازپرداخت ثبت‌شده در ارز انتخاب‌شده، مقدار ناموجود است.",
        limitations="فقط رویدادهای بازپرداخت ثبت‌شده در بازه محاسبه می‌شوند؛ سنجه توصیفی است.",
        endpoint="/api/v1/crm/campaign-experiments/{experiment_id}/readout",
        required_permissions=["crm.campaign:view", COMMERCE_PERMISSION],
    ),
    MetricDefinition(
        key="refund_to_paid_amount_percent", name="نسبت بازپرداخت به مبلغ پرداخت سفارش", category="commerce",
        description="درصد مبلغ بازپرداخت ثبت‌شده نسبت به مبلغ پرداخت سفارش‌هایی که هر دو رویداد را دارند.",
        formula="جمع بازپرداخت‌های سفارش‌های دارای پرداخت ÷ جمع پرداخت همان سفارش‌ها × ۱۰۰",
        source="CRMProductCommerceEvent با رویدادهای paid و refunded و اتصال صریح کمپین",
        aggregation="پرداخت و بازپرداخت برای هر (محصول مبدأ، مرجع سفارش) جداگانه جمع می‌شوند؛ فقط سفارش‌های مشترک لحاظ می‌شوند.",
        dimensions=["campaign", "currency", "date range", "source product"],
        unit="percent", currency_behavior="هر ارز جدا؛ تبدیل ارز انجام نمی‌شود.",
        missing_data_behavior="بدون سفارش دارای هر دو رویداد یا با مبلغ پرداخت صفر، مقدار ناموجود است.",
        limitations="فقط رویدادهای ثبت‌شده در بازه را می‌سنجد؛ نسبت توصیفی است و میزان نهایی زیان یا اثر علّی نیست.",
        endpoint="/api/v1/crm/campaign-experiments/{experiment_id}/readout",
        required_permissions=["crm.campaign:view", COMMERCE_PERMISSION],
    ),
    MetricDefinition(
        key="refund_amount", name="مبلغ بازپرداخت ثبت‌شده", category="commerce",
        description="جمع رویدادهای بازپرداخت متصل به کمپین؛ جدا از مبلغ پرداخت نمایش داده می‌شود.",
        formula="جمع amount رویدادهای refunded متصل به کمپین، به تفکیک ارز",
        source="CRMProductCommerceEvent با event_kind=refunded و campaign_id مشخص",
        aggregation="جمع رویدادهای بازه؛ ارزها جدا هستند.",
        dimensions=["campaign", "currency", "date range", "source product"],
        unit="money", currency_behavior="هر ارز جدا؛ تبدیل ارز انجام نمی‌شود.",
        missing_data_behavior="فقط رویدادهای بازپرداخت ثبت‌شده با پیوند صریح کمپین شمرده می‌شوند.",
        limitations="در معیارهای مبلغ پرداخت این کاتالوگ به‌طور خودکار کسر نمی‌شود.",
        endpoint="/api/v1/crm/analytics/campaign-commerce-efficiency",
        required_permissions=["crm.campaign:view", COMMERCE_PERMISSION],
    ),
    MetricDefinition(
        key="refunded_order_count", name="تعداد سفارش‌های بازپرداخت‌شده", category="commerce",
        description="تعداد سفارش‌های متمایز دارای رویداد بازپرداخت که صریحاً به کمپین متصل شده‌اند.",
        formula="تعداد یکتای (محصول مبدأ، مرجع سفارش) برای رویدادهای refunded متصل به کمپین",
        source="CRMProductCommerceEvent با event_kind=refunded و campaign_id مشخص",
        aggregation="هر سفارش برای هر محصول مبدأ یک‌بار شمرده می‌شود، حتی با چند بازپرداخت جزئی.",
        dimensions=["campaign", "date range", "source product"],
        unit="count", currency_behavior="بدون ارز",
        missing_data_behavior="فقط سفارش‌های دارای رویداد بازپرداخت ثبت‌شده شمرده می‌شوند.",
        limitations="مرجع سفارش در محصول مبدأ معنا دارد؛ اتصال صریح کمپین اثبات اثر علّی نیست.",
        endpoint="/api/v1/crm/campaign-experiments/{experiment_id}/readout",
        required_permissions=["crm.campaign:view", COMMERCE_PERMISSION],
    ),
    MetricDefinition(
        key="refunded_order_rate_percent", name="نرخ سفارش‌های بازپرداخت‌شده", category="commerce",
        description="درصد سفارش‌های پرداخت‌شدهٔ متصل به کمپین که در همان بازه رویداد بازپرداخت دارند.",
        formula="تعداد یکتای سفارش‌های دارای رویداد paid و refunded تقسیم بر تعداد یکتای سفارش‌های paid × ۱۰۰",
        source="CRMProductCommerceEvent با اتصال صریح کمپین و event_kind برابر paid یا refunded",
        aggregation="سفارش‌ها با کلید (محصول مبدأ، مرجع سفارش) یکتا می‌شوند.",
        dimensions=["campaign", "date range", "source product"],
        unit="percent", currency_behavior="بدون ارز",
        missing_data_behavior="بدون سفارش paid مقدار ناموجود است؛ نبود رویداد refund به‌تنهایی اثبات نبود بازپرداخت نیست.",
        limitations="فقط بازپرداخت‌های ثبت‌شده در همان بازه لحاظ می‌شوند؛ سنجه توصیفی است و نسبت علّی را نشان نمی‌دهد.",
        endpoint="/api/v1/crm/campaign-experiments/{experiment_id}/readout",
        required_permissions=["crm.campaign:view", COMMERCE_PERMISSION],
    ),
    MetricDefinition(
        key="paid_to_spend", name="نسبت پرداخت ثبت‌شده به هزینه", category="commerce",
        description="نسبت پرداخت‌های ثبت‌شدهٔ متصل به کمپین به هزینهٔ ثبت‌شده.",
        formula="جمع مبلغ paid متصل به کمپین ÷ جمع هزینهٔ مثبت ثبت‌شده، در ارز یکسان",
        source="CRMProductCommerceEvent و CRMMarketingCampaignMeasurement",
        aggregation="نسبت مجموع‌های دوره؛ پرداخت و هزینه باید ارز یکسان داشته باشند.",
        dimensions=["campaign", "currency", "date range"],
        unit="multiple", currency_behavior="فقط ارزهای یکسان؛ تبدیل ارز انجام نمی‌شود.",
        missing_data_behavior="بدون پرداخت متصل یا هزینهٔ مثبت در همان ارز، مقدار ندارد.",
        limitations="بازپرداخت جدا می‌ماند؛ این نسبت بازده علّی تبلیغ یا ROAS انتساب‌یافته نیست.",
        endpoint="/api/v1/crm/campaigns/{campaign_id}/decision-workspace/{target_id}",
        required_permissions=["crm.campaign:view", COMMERCE_PERMISSION],
    ),
    MetricDefinition(
        key="recorded_day_coverage", name="پوشش روزهای دارای داده", category="data_quality",
        description="تعداد روزهای بازه که برای یک شاخص مقدار ثبت‌شده دارد.",
        formula="روزهای دارای مقدار غیرتهی برای همان شاخص ÷ روزهای تقویمی بازه × 100",
        source="CRMMarketingCampaignMeasurement و روزهای دورهٔ گزارش",
        aggregation="برای هر شاخص جداگانه محاسبه می‌شود؛ در فضای تصمیم کمپین در برابر روزهای تقویمی طرح.",
        dimensions=["campaign", "metric", "date range"],
        unit="percent", currency_behavior="بدون ارز",
        missing_data_behavior="روز بدون مقدار، بدون داده است و صفر عملکرد فرض نمی‌شود.",
        limitations="وجود داده را نشان می‌دهد، نه کامل‌بودن گزارش‌دهی کانال یا صحت داده.",
        endpoint="/api/v1/crm/campaigns/{campaign_id}/decision-workspace/{target_id}",
        required_permissions=["crm.campaign:view"],
    ),
])


def get_metric_definition(key: str) -> MetricDefinition | None:
    """Return the canonical definition for a workspace or target evaluation KPI."""
    aliases = {"spend": "actual_spend", "roas": "reported_roas"}
    canonical_key = aliases.get(key, key)
    return next((metric for metric in _METRICS if metric.key == canonical_key), None)


def _visible_metrics(
    definitions: list[MetricDefinition],
    *,
    has_commerce_permission: bool,
    category: str | None,
    search: str | None,
) -> list[MetricDefinition]:
    selected = [
        metric for metric in definitions
        if (has_commerce_permission or COMMERCE_PERMISSION not in metric.required_permissions)
        and (category is None or metric.category == category)
    ]
    needle = (search or "").strip().casefold()
    if needle:
        selected = [
            metric for metric in selected
            if needle in " ".join([
                metric.key, metric.name, metric.description, metric.formula,
                metric.source, metric.limitations,
            ]).casefold()
        ]
    return selected


@router.get("", response_model=MetricCatalog, operation_id="listCRMMetrics")
async def list_crm_metrics(
    organization_unit_id: UUID,
    category: Literal["campaign_activity", "funnel_rates", "marketing_cost", "commerce", "data_quality"] | None = None,
    search: str | None = Query(default=None, min_length=1, max_length=100),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> MetricCatalog:
    if not await has_crm_permission(
        context,
        permission_key="crm.campaign:view",
        organization_unit_id=organization_unit_id,
    ):
        raise HTTPException(status_code=403, detail="Marketing metric catalog is not authorized")
    can_view_commerce = await has_crm_permission(
        context,
        permission_key=COMMERCE_PERMISSION,
        organization_unit_id=organization_unit_id,
    )
    metrics = _visible_metrics(
        _METRICS,
        has_commerce_permission=can_view_commerce,
        category=category,
        search=search,
    )
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_marketing.metric_catalog_viewed",
        target_type="crm_metric_catalog",
        target_key=str(organization_unit_id),
        organization_unit_id=organization_unit_id,
        before_state=None,
        after_state={
            "catalog_version": CATALOG_VERSION,
            "category": category,
            "search_used": bool(search),
            "visible_metric_count": len(metrics),
        },
        correlation_id=None,
    ))
    await context.session.flush()
    return MetricCatalog(
        catalog_version=CATALOG_VERSION,
        organization_unit_id=organization_unit_id,
        generated_at=datetime.now(timezone.utc),
        metrics=metrics,
    )
