from dataclasses import dataclass

from app.services.personalization import is_assigned_to_user, normalize_person_name
from app.services.retrieval import lexical_similarity

MIN_SCHEDULE_VECTOR_SIMILARITY = 0.82
MIN_SCHEDULE_LEXICAL_SIMILARITY = 0.20
STRONG_SCHEDULE_VECTOR_SIMILARITY = 0.93

_MISSING_DUE_VALUES = {
    "",
    "-",
    "없음",
    "미정",
    "언급없음",
    "언급되지않음",
    "기한미정",
    "날짜미정",
    "추후",
    "추후결정",
}


@dataclass(frozen=True)
class ScheduleMatchScore:
    accepted: bool
    vector_similarity: float
    lexical_similarity: float
    combined_score: float


def has_meaningful_due(value: str | None) -> bool:
    normalized = "".join((value or "").lower().split()).strip(".,:;")
    return normalized not in _MISSING_DUE_VALUES


def assignees_match(
    current_assignee: str | None,
    current_pii,
    previous_assignee: str | None,
    previous_pii,
    display_name: str | None,
) -> bool:
    current_normalized = _resolved_assignee(current_assignee, current_pii)
    previous_normalized = _resolved_assignee(previous_assignee, previous_pii)
    if current_normalized and current_normalized == previous_normalized:
        return True
    return is_assigned_to_user(
        current_assignee,
        current_pii,
        display_name,
    ) and is_assigned_to_user(
        previous_assignee,
        previous_pii,
        display_name,
    )


def _resolved_assignee(assignee: str | None, pii_entries) -> str:
    raw_value = assignee or ""
    for entry in pii_entries:
        token = getattr(entry, "placeholder_token", None)
        if (
            getattr(entry, "pii_type", None) == "name"
            and token
            and token in raw_value
        ):
            return normalize_person_name(
                getattr(entry, "original_value", "")
            )
    if "[이름" in raw_value:
        return ""
    return normalize_person_name(raw_value)


def schedule_match_score(
    current_task: str | None,
    current_request: str | None,
    previous_task: str | None,
    previous_request: str | None,
    vector_similarity: float,
) -> ScheduleMatchScore:
    current_text = " ".join(
        value.strip() for value in (current_task or "", current_request or "") if value.strip()
    )
    previous_text = " ".join(
        value.strip()
        for value in (previous_task or "", previous_request or "")
        if value.strip()
    )
    lexical = max(
        lexical_similarity(current_text, previous_text),
        lexical_similarity(previous_text, current_text),
    )
    accepted = (
        vector_similarity >= MIN_SCHEDULE_VECTOR_SIMILARITY
        and lexical >= MIN_SCHEDULE_LEXICAL_SIMILARITY
    ) or vector_similarity >= STRONG_SCHEDULE_VECTOR_SIMILARITY
    combined = (0.75 * vector_similarity) + (0.25 * lexical)
    return ScheduleMatchScore(
        accepted=accepted,
        vector_similarity=vector_similarity,
        lexical_similarity=lexical,
        combined_score=combined,
    )
