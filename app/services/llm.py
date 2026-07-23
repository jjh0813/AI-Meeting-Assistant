import httpx

from app.core.config import settings
from app.services.errors import ExternalServiceError


def call_llm(prompt: str, json_mode: bool = False) -> str:
    url = settings.ollama_base_url + "/api/generate"
    body = {"model": settings.llm_model, "prompt": prompt, "stream": False}
    if json_mode:
        body["format"] = "json"
    try:
        response = httpx.post(url, json=body, timeout=120)
        response.raise_for_status()
        generated = response.json().get("response")
    except httpx.TimeoutException as exc:
        raise ExternalServiceError(
            "AI 모델 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.",
            status_code=504,
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise ExternalServiceError(
            "AI 모델 호출에 실패했습니다. Ollama와 모델 상태를 확인해 주세요.",
            status_code=502,
        ) from exc
    except (httpx.RequestError, ValueError) as exc:
        raise ExternalServiceError(
            "AI 모델에 연결할 수 없습니다. Ollama 실행 상태를 확인해 주세요."
        ) from exc
    if not isinstance(generated, str) or not generated.strip():
        raise ExternalServiceError(
            "AI 모델이 유효한 응답을 반환하지 않았습니다. 다시 시도해 주세요.",
            status_code=502,
        )
    return generated
