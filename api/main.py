from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from api.routes import records

from api.routes import health, civic, adaptation, timeline, pattern

app = FastAPI(
    title="Civic Decision Engine API",
    description="Structured API for civic case analysis, timeline detection, and pattern classification.",
    version="v11",
)

app.mount("/static", StaticFiles(directory="api/static"), name="static")


@app.get("/")
def root():
    return FileResponse("api/static/index.html")


@app.get("/robots.txt")
def robots():
    return FileResponse("robots.txt")


@app.get("/sitemap.xml")
def sitemap():
    return FileResponse("sitemap.xml")


app.include_router(health.router)
app.include_router(civic.router)
app.include_router(adaptation.router)
app.include_router(timeline.router)
app.include_router(pattern.router)
app.include_router(records.router)
