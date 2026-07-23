import json

import httpx

from app.core.config import settings
from app.services.errors import ExternalServiceError


def transcribe(audio_bytes: bytes, filename: str = "audio") -> str:
    if not settings.clova_speech_invoke_url or not settings.clova_speech_secret:
        raise ExternalServiceError(
            "CLOVA Speech 설정이 없습니다. 서버 환경변수를 확인해 주세요."
        )
    url = settings.clova_speech_invoke_url.rstrip("/") + "/recognizer/upload"
    headers = {"X-CLOVASPEECH-API-KEY": settings.clova_speech_secret}
    params = {"language": "ko-KR", "completion": "sync", "fullText": True}
    files = {
        "media": (filename, audio_bytes),
        "params": (None, json.dumps(params), "application/json"),
    }
    try:
        response = httpx.post(url, headers=headers, files=files, timeout=300)
        response.raise_for_status()
        text = response.json().get("text")
    except httpx.TimeoutException as exc:
        raise ExternalServiceError(
            "음성 변환 시간이 초과되었습니다. 더 짧은 파일로 다시 시도해 주세요.",
            status_code=504,
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise ExternalServiceError(
            "음성 변환 요청에 실패했습니다. CLOVA Speech 설정과 파일 형식을 확인해 주세요.",
            status_code=502,
        ) from exc
    except (httpx.RequestError, ValueError) as exc:
        raise ExternalServiceError(
            "CLOVA Speech에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요."
        ) from exc
    if not isinstance(text, str) or not text.strip():
        raise ExternalServiceError(
            "음성에서 인식된 텍스트가 없습니다. 음질과 파일 내용을 확인해 주세요.",
            status_code=422,
        )
    return text
