from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

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

app.mount("/static", StaticFiles(directory="api/static"), name="static")


@app.get("/")
def root():
    return FileResponse("api/static/index.html")


app.include_router(health.router)
app.include_router(civic.router)
app.include_router(adaptation.router)
app.include_router(timeline.router)
app.include_router(pattern.router)
