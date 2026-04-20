from __future__ import annotations

from fastapi import FastAPI
from api.routes import health, civic, adaptation, timeline, pattern

app = FastAPI(
    title="Civic Decision Engine API",
    description=(
        "Structured API for civic case analysis, "
        "timeline detection, and pattern classification. "
        "Input → Structured processing → Classified output."
    ),
    version="v10",
)

app.include_router(health.router, prefix="/system")
app.include_router(civic.router, prefix="/civic")
app.include_router(adaptation.router, prefix="/analysis")
app.include_router(timeline.router, prefix="/analysis")
app.include_router(pattern.router, prefix="/analysis")
