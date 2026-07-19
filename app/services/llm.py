import httpx

from app.core.config import settings


def call_llm(prompt: str, json_mode: bool = False) -> str:
    url = settings.ollama_base_url + "/api/generate"
    body = {"model": settings.llm_model, "prompt": prompt, "stream": False}
    if json_mode:
        body["format"] = "json"
    response = httpx.post(url, json=body, timeout=120)
    response.raise_for_status()
    return response.json()["response"]
