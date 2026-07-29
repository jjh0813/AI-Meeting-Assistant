from contextlib import asynccontextmanager
import hashlib
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import auth, calendar, transcripts, users
from app.core.config import settings
from app.mcp_server import mcp
from app.services.errors import ExternalServiceError

STATIC_DIR = Path(__file__).parent / "static"
STATIC_INDEX = STATIC_DIR / "index.html"
mcp_http_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(_):
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="Noting", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(transcripts.router)
app.include_router(calendar.router)


class CacheControlStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200 and path.endswith((".css", ".js")):
            query = scope.get("query_string", b"").decode("ascii", errors="ignore")
            if "v=" in query:
                response.headers["Cache-Control"] = (
                    "public, max-age=31536000, immutable"
                )
            else:
                response.headers["Cache-Control"] = (
                    "public, max-age=300, stale-while-revalidate=60"
                )
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response


def _asset_version() -> str:
    configured = settings.static_asset_version.strip()
    if configured:
        return configured
    digest = hashlib.sha256()
    for name in ("styles.css", "app.js"):
        digest.update((STATIC_DIR / name).read_bytes())
    return digest.hexdigest()[:12]


@app.get("/ui/", include_in_schema=False)
def ui_index():
    base_url = settings.static_asset_base_url.strip().rstrip("/") or "/ui"
    version = _asset_version()
    html = STATIC_INDEX.read_text(encoding="utf-8")
    html = html.replace(
        "/ui/styles.css",
        f"{base_url}/styles.css?v={version}",
    ).replace(
        "/ui/app.js",
        f"{base_url}/app.js?v={version}",
    )
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


app.mount(
    "/ui",
    CacheControlStaticFiles(directory=STATIC_DIR, html=True),
    name="ui",
)


@app.exception_handler(ExternalServiceError)
def external_service_error_handler(_, exc: ExternalServiceError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.get("/")
def root():
    return RedirectResponse(url="/ui/", status_code=302)


@app.get("/health")
def health_check():
    return {"status": "ok", "environment": settings.environment}


# The MCP app is mounted last at the origin root so OAuth discovery endpoints
# remain RFC 8414/RFC 9728 compliant while the protocol endpoint stays at /mcp.
app.mount("/", mcp_http_app, name="mcp")
