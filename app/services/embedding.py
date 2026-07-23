import httpx

from app.core.config import settings
from app.services.errors import ExternalServiceError


def embed(text: str):
    url = settings.ollama_base_url + "/api/embeddings"
    body = {"model": settings.embed_model, "prompt": text}
    try:
        response = httpx.post(url, json=body, timeout=120)
        response.raise_for_status()
        embedding = response.json().get("embedding")
    except httpx.TimeoutException as exc:
        raise ExternalServiceError(
            "임베딩 모델 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.",
            status_code=504,
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise ExternalServiceError(
            "임베딩 생성에 실패했습니다. Ollama와 임베딩 모델 상태를 확인해 주세요.",
            status_code=502,
        ) from exc
    except (httpx.RequestError, ValueError) as exc:
        raise ExternalServiceError(
            "임베딩 모델에 연결할 수 없습니다. Ollama 실행 상태를 확인해 주세요."
        ) from exc
    if not isinstance(embedding, list) or not embedding:
        raise ExternalServiceError(
            "임베딩 모델이 유효한 벡터를 반환하지 않았습니다.",
            status_code=502,
        )
    return embedding
