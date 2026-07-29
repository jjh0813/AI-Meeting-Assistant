import json

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.prompts import ANALYSIS_PROMPT, SUMMARY_PROMPT
from app.services.errors import ExternalServiceError
from app.services.llm import call_llm
from app.services.meeting_summary import format_structured_summary


class AnalysisTask(BaseModel):
    model_config = ConfigDict(extra="ignore")

    task: str
    assignee: str = ""
    due: str = ""
    request: str = ""

    @field_validator("task", "assignee", "due", "request", mode="before")
    @classmethod
    def normalize_nullable_text(cls, value):
        return "" if value is None else value


class StructuredAnalysisSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    topic: str = ""
    meeting_datetime: str = "언급 없음"
    participants: str = "언급 없음"
    purpose: str = "언급 없음"
    key_points: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    unresolved_items: list[str] = Field(default_factory=list)

    @field_validator(
        "topic",
        "meeting_datetime",
        "participants",
        "purpose",
        mode="before",
    )
    @classmethod
    def normalize_scalar(cls, value):
        if isinstance(value, list):
            return ", ".join(str(item) for item in value if item)
        return "언급 없음" if value is None else value

    @field_validator(
        "key_points",
        "decisions",
        "unresolved_items",
        mode="before",
    )
    @classmethod
    def normalize_list(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return value


class AnalysisResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str
    summary: StructuredAnalysisSummary
    tasks: list[AnalysisTask]


def summarize(masked_text: str) -> str:
    prompt = SUMMARY_PROMPT.format(content=masked_text)
    raw_summary = call_llm(prompt)
    return format_structured_summary("", raw_summary)


def _summary_object_from_text(title: str, summary: str) -> dict:
    from app.services.meeting_summary import parse_structured_summary

    parsed = parse_structured_summary(summary, title)
    return {
        "topic": parsed["topic"],
        "meeting_datetime": parsed["meeting_datetime"],
        "participants": parsed["participants"],
        "purpose": parsed["purpose"],
        "key_points": parsed["key_points"],
        "decisions": parsed["decisions"],
        "unresolved_items": parsed["unresolved_items"],
    }


def _summary_text(title: str, summary: StructuredAnalysisSummary) -> str:
    values = summary.model_dump()
    raw = "\n".join(
        [
            f"주제: {values['topic'] or title}",
            f"일시: {values['meeting_datetime'] or '언급 없음'}",
            f"참석자: {values['participants'] or '언급 없음'}",
            f"회의 목적: {values['purpose'] or '언급 없음'}",
            "핵심 논의:",
            *[f"- {item}" for item in values["key_points"]],
            "결정 사항:",
            *[f"- {item}" for item in values["decisions"]],
            "미결 사항:",
            *[f"- {item}" for item in values["unresolved_items"]],
        ]
    )
    return format_structured_summary(title, raw)


def analyze(masked_text: str) -> dict:
    prompt = ANALYSIS_PROMPT.format(content=masked_text)
    raw = call_llm(
        prompt,
        json_mode=True,
        json_schema=AnalysisResult.model_json_schema(),
    )
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and isinstance(data.get("summary"), str):
            data["summary"] = _summary_object_from_text(
                str(data.get("title") or ""),
                data["summary"],
            )
        result = AnalysisResult.model_validate(data)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise ExternalServiceError(
            "AI 분석 결과 형식이 올바르지 않습니다. 기존 분석은 유지되며 다시 시도할 수 있습니다.",
            status_code=502,
        ) from exc
    normalized = result.model_dump()
    normalized["summary"] = _summary_text(result.title, result.summary)
    return normalized
