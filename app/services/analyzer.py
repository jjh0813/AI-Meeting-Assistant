import json

from app.core.prompts import ANALYSIS_PROMPT, SUMMARY_PROMPT
from app.services.llm import call_llm


def summarize(masked_text: str) -> str:
    prompt = SUMMARY_PROMPT.format(content=masked_text)
    return call_llm(prompt)


def analyze(masked_text: str) -> dict:
    prompt = ANALYSIS_PROMPT.format(content=masked_text)
    raw = call_llm(prompt, json_mode=True)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {}
    return {"summary": data.get("summary", ""), "tasks": data.get("tasks", [])}
