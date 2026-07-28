from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import auth, calendar, transcripts, users
from app.core.config import settings
from app.mcp_server import mcp
from app.services.errors import ExternalServiceError


@asynccontextmanager
async def lifespan(_):
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="Noting", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(transcripts.router)
app.include_router(calendar.router)
app.mount("/mcp", mcp.streamable_http_app(), name="mcp")

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/ui", StaticFiles(directory=STATIC_DIR, html=True), name="ui")


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
