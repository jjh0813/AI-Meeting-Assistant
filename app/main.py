from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import auth, transcripts, users
from app.core.config import settings

app = FastAPI(title="Noting")

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(transcripts.router)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/ui", StaticFiles(directory=STATIC_DIR, html=True), name="ui")


@app.get("/")
def root():
    return RedirectResponse(url="/ui/", status_code=302)


@app.get("/health")
def health_check():
    return {"status": "ok", "environment": settings.environment}
