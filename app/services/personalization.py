import re

from app.services.masking import mask_text


INDEXED_PII_PATTERN = re.compile(r"\[(이름|전화번호)#\d+\]")
NAME_TITLE_PATTERN = re.compile(
    r"(님|씨|군|양|과장|대리|부장|차장|사원|팀장|이사|대표|사장|교수|주임|연구원)$"
)


def normalize_person_name(value: str | None) -> str:
    normalized = re.sub(r"\s+", "", value or "")
    return NAME_TITLE_PATTERN.sub("", normalized)


def own_name_tokens(pii_entries, display_name: str | None) -> set[str]:
    target = normalize_person_name(display_name)
    if not target:
        return set()
    return {
        entry.placeholder_token
        for entry in pii_entries
        if entry.pii_type == "name"
        and entry.placeholder_token
        and normalize_person_name(entry.original_value) == target
    }


def personalize_masked_text(
    value: str | None, pii_entries, display_name: str | None
) -> str | None:
    if value is None:
        return None
    own_tokens = own_name_tokens(pii_entries, display_name)

    def replace(match: re.Match) -> str:
        token = match.group(0)
        if token in own_tokens:
            return display_name or "[이름]"
        return "[전화번호]" if token.startswith("[전화번호#") else "[이름]"

    return INDEXED_PII_PATTERN.sub(replace, value)


def is_assigned_to_user(
    assignee: str | None, pii_entries, display_name: str | None
) -> bool:
    if not assignee or not display_name:
        return False
    if any(token in assignee for token in own_name_tokens(pii_entries, display_name)):
        return True
    return normalize_person_name(assignee) == normalize_person_name(display_name)


def remask_personalized_text(
    value: str, pii_entries, display_name: str | None
) -> tuple[str, list[dict]]:
    """Preserve hidden PII tokens when a personalized transcript is edited."""
    prepared = value
    own_tokens = own_name_tokens(pii_entries, display_name)
    retained = []
    counters = {"name": 0, "phone": 0}
    for entry in pii_entries:
        token = entry.placeholder_token
        if not token:
            continue
        token_match = re.fullmatch(r"\[(이름|전화번호)#(\d+)\]", token)
        if not token_match:
            continue
        kind = "name" if token_match.group(1) == "이름" else "phone"
        counters[kind] = max(counters[kind], int(token_match.group(2)))
        if token in own_tokens:
            continue
        generic = "[이름]" if kind == "name" else "[전화번호]"
        if generic in prepared:
            prepared = prepared.replace(generic, token, 1)
            retained.append(
                {
                    "pii_type": entry.pii_type,
                    "original_value": entry.original_value,
                    "placeholder_token": token,
                }
            )

    masked, newly_found = mask_text(prepared, initial_counts=counters)
    return masked, retained + newly_found
