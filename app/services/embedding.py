import httpx

from app.core.config import settings


def embed(text: str):
    url = settings.ollama_base_url + "/api/embeddings"
    body = {"model": settings.embed_model, "prompt": text}
    try:
        response = httpx.post(url, json=body, timeout=120)
        response.raise_for_status()
        return response.json().get("embedding")
    except Exception:
        return None
