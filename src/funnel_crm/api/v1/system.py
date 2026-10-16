"""System endpoints for the versioned public API."""

from fastapi import APIRouter

router = APIRouter(prefix="/system", tags=["system"])


@router.get("", operation_id="getSystemInfo", summary="Get API service information")
async def get_system_info() -> dict[str, str]:
    """Return non-sensitive service metadata for API discovery."""
    return {"service": "funnel-crm", "api_version": "v1"}
