from __future__ import annotations

from fastapi import APIRouter
from api.models import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["System"])
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        engine="Civic Decision Engine",
        version="v10",
        modes=["civic", "adaptation", "timeline", "pattern"],
    )
