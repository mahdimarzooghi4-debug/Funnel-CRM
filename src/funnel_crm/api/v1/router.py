"""Composition root for versioned API modules."""

from fastapi import APIRouter

from funnel_crm.api.v1.system import router as system_router

router = APIRouter(prefix="/api/v1")
router.include_router(system_router)
