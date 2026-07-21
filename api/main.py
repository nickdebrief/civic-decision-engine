from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from api.platform_identity import PLATFORM_NAME, PLATFORM_VERSION_LABEL
from api.routes import records

from api.routes import health, civic, adaptation, timeline, pattern, admin_session, documents, associations, collections, archive, traceability

app = FastAPI(
    title=f"{PLATFORM_NAME} API",
    description="Structured API for civic case analysis, timeline detection, and pattern classification.",
    version=PLATFORM_VERSION_LABEL,
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
app.include_router(admin_session.router)
app.include_router(documents.router)
app.include_router(associations.router)
app.include_router(collections.router)
app.include_router(archive.router)
app.include_router(traceability.router)
app.include_router(records.router)
