"""Composition root for versioned API modules."""

from fastapi import APIRouter

from funnel_crm.api.v1.crm_contact_points import router as crm_contact_points_router
from funnel_crm.api.v1.crm_duplicates import router as crm_duplicates_router
from funnel_crm.api.v1.crm_profiles import router as crm_profiles_router
from funnel_crm.api.v1.crm_communication_consent import router as crm_communication_consent_router
from funnel_crm.api.v1.integrations import router as integrations_router
from funnel_crm.api.v1.system import router as system_router

router = APIRouter(prefix="/api/v1")
router.include_router(system_router)
router.include_router(integrations_router)
router.include_router(crm_profiles_router)
router.include_router(crm_contact_points_router)
router.include_router(crm_duplicates_router)
router.include_router(crm_communication_consent_router)
