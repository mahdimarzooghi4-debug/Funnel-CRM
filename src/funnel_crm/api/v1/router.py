"""Composition root for versioned API modules."""

from fastapi import APIRouter

from funnel_crm.api.v1.crm_segments import router as crm_segments_router
from funnel_crm.api.v1.crm_campaigns import router as crm_campaigns_router
from funnel_crm.api.v1.crm_campaign_measurements import router as crm_campaign_measurements_router
from funnel_crm.api.v1.crm_budget_scenarios import router as crm_budget_scenarios_router
from funnel_crm.api.v1.crm_customer_activity_analytics import router as crm_customer_activity_analytics_router
from funnel_crm.api.v1.crm_customer_activities import router as crm_customer_activities_router

from funnel_crm.api.v1.crm_contact_points import router as crm_contact_points_router
from funnel_crm.api.v1.crm_duplicates import router as crm_duplicates_router
from funnel_crm.api.v1.crm_custom_field_definitions import router as crm_custom_field_definitions_router
from funnel_crm.api.v1.crm_custom_field_values import router as crm_custom_field_values_router
from funnel_crm.api.v1.crm_profiles import router as crm_profiles_router
from funnel_crm.api.v1.crm_communication_consent import router as crm_communication_consent_router
from funnel_crm.api.v1.integrations import router as integrations_router
from funnel_crm.api.v1.product_connections import router as product_connections_router
from funnel_crm.api.v1.system import router as system_router

router = APIRouter(prefix="/api/v1")
router.include_router(system_router)
router.include_router(integrations_router)
router.include_router(product_connections_router)
router.include_router(crm_profiles_router)
router.include_router(crm_customer_activities_router)
router.include_router(crm_customer_activity_analytics_router)
router.include_router(crm_segments_router)
router.include_router(crm_campaigns_router)
router.include_router(crm_campaign_measurements_router)
router.include_router(crm_budget_scenarios_router)
router.include_router(crm_contact_points_router)
router.include_router(crm_duplicates_router)
router.include_router(crm_custom_field_definitions_router)
router.include_router(crm_custom_field_values_router)
router.include_router(crm_communication_consent_router)
