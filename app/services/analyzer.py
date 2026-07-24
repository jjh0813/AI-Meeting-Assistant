import json

from pydantic import BaseModel, ConfigDict, ValidationError

from app.core.prompts import ANALYSIS_PROMPT, SUMMARY_PROMPT
from app.services.errors import ExternalServiceError
from app.services.llm import call_llm


class AnalysisTask(BaseModel):
    model_config = ConfigDict(extra="ignore")

    task: str
    assignee: str
    due: str
    request: str


class AnalysisResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str
    summary: str
    tasks: list[AnalysisTask]


def summarize(masked_text: str) -> str:
    prompt = SUMMARY_PROMPT.format(content=masked_text)
    return call_llm(prompt)


def analyze(masked_text: str) -> dict:
    prompt = ANALYSIS_PROMPT.format(content=masked_text)
    raw = call_llm(prompt, json_mode=True)
    try:
        data = json.loads(raw)
        result = AnalysisResult.model_validate(data)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise ExternalServiceError(
            "AI 분석 결과 형식이 올바르지 않습니다. 기존 분석은 유지되며 다시 시도할 수 있습니다.",
            status_code=502,
        ) from exc
    return result.model_dump()
