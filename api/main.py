from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from api.public_origin import (
    inject_canonical_link,
    is_public_indexable_path,
    public_alias_redirect_location,
)
from api.platform_identity import PLATFORM_NAME, PLATFORM_VERSION_LABEL
from api.routes import records

from api.routes import health, civic, adaptation, timeline, pattern, admin_session, documents, associations, collections, archive, traceability, transmissions, governed_determination_publications

app = FastAPI(
    title=f"{PLATFORM_NAME} API",
    description="Structured API for civic case analysis, timeline detection, and pattern classification.",
    version=PLATFORM_VERSION_LABEL,
)

app.mount("/static", StaticFiles(directory="api/static"), name="static")

INDEXNOW_OWNERSHIP_KEY = "199f69ef74214688b3aff215441ae226"


@app.middleware("http")
async def canonical_public_origin_middleware(request, call_next):
    host = request.headers.get("host", "")
    location = public_alias_redirect_location(host, request.url.path, request.scope["query_string"])
    if location is not None:
        return Response(status_code=308, headers={"Location": location})
    response = await call_next(request)
    if (
        request.method != "GET"
        or not is_public_indexable_path(request.url.path)
        or response.status_code != 200
        or not response.headers.get("content-type", "").startswith("text/html")
    ):
        return response
    body = b"".join([chunk async for chunk in response.body_iterator])
    body = inject_canonical_link(body, request.url.path)
    headers = dict(response.headers)
    headers["content-length"] = str(len(body))
    return Response(content=body, status_code=response.status_code, headers=headers, media_type="text/html")


@app.get("/")
def root():
    return FileResponse("api/static/index.html")


@app.api_route(
    f"/{INDEXNOW_OWNERSHIP_KEY}.txt",
    methods=["GET", "HEAD"],
    include_in_schema=False,
)
def indexnow_ownership_key():
    return Response(content=INDEXNOW_OWNERSHIP_KEY, media_type="text/plain")


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
app.include_router(transmissions.router)
app.include_router(records.router)
app.include_router(governed_determination_publications.router)
