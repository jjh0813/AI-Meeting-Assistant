import json

import httpx

from app.core.config import settings


def transcribe(audio_bytes: bytes, filename: str = "audio") -> str:
    url = settings.clova_speech_invoke_url.rstrip("/") + "/recognizer/upload"
    headers = {"X-CLOVASPEECH-API-KEY": settings.clova_speech_secret}
    params = {"language": "ko-KR", "completion": "sync", "fullText": True}
    files = {
        "media": (filename, audio_bytes),
        "params": (None, json.dumps(params), "application/json"),
    }
    response = httpx.post(url, headers=headers, files=files, timeout=300)
    response.raise_for_status()
    data = response.json()
    return data.get("text", "")
