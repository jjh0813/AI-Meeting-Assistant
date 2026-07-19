from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import auth, transcripts, users
from app.core.config import settings

app = FastAPI(title="회의록 AI")

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(transcripts.router)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/ui", StaticFiles(directory=STATIC_DIR, html=True), name="ui")


@app.get("/")
def root():
    return {"message": "회의록 AI 서버가 실행 중입니다."}


@app.get("/health")
def health_check():
    return {"status": "ok", "environment": settings.environment}