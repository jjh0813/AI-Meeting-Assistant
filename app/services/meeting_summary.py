import re


EMPTY_VALUE = "언급 없음"
SUMMARY_LABELS = (
    "주제",
    "일시",
    "참석자",
    "회의 목적",
    "핵심 논의",
    "결정 사항",
    "미결 사항",
)
_LABEL_PATTERN = re.compile(
    r"^(주제|일시|참석자|회의\s*목적|핵심\s*논의|결정\s*사항|미결\s*사항)\s*:\s*(.*)$"
)
_LIST_FIELDS = {
    "핵심 논의": "key_points",
    "결정 사항": "decisions",
    "미결 사항": "unresolved_items",
}
_SCALAR_FIELDS = {
    "주제": "topic",
    "일시": "meeting_datetime",
    "참석자": "participants",
    "회의 목적": "purpose",
}


def _clean_label(label: str) -> str:
    return re.sub(r"\s+", " ", label.strip())


def _clean_item(text: str) -> str:
    return re.sub(r"^[\s\-*•·]+", "", text.strip()).strip()


def parse_structured_summary(summary: str, title: str = "") -> dict:
    result = {
        "topic": title.strip() or "회의 내용",
        "meeting_datetime": EMPTY_VALUE,
        "participants": EMPTY_VALUE,
        "purpose": EMPTY_VALUE,
        "key_points": [],
        "decisions": [],
        "unresolved_items": [],
    }
    text = (summary or "").strip()
    if not text:
        result["key_points"] = [EMPTY_VALUE]
        result["decisions"] = [EMPTY_VALUE]
        result["unresolved_items"] = [EMPTY_VALUE]
        return result

    recognized = False
    current_list_field = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _LABEL_PATTERN.match(line)
        if match:
            recognized = True
            label = _clean_label(match.group(1))
            value = _clean_item(match.group(2))
            if label in _SCALAR_FIELDS:
                current_list_field = None
                if value:
                    result[_SCALAR_FIELDS[label]] = value
            else:
                current_list_field = _LIST_FIELDS[label]
                if value:
                    result[current_list_field].append(value)
            continue
        if current_list_field:
            item = _clean_item(line)
            if item:
                result[current_list_field].append(item)

    if not recognized:
        result["key_points"] = [
            line.strip()
            for line in re.split(r"(?<=[.!?])\s+|\n+", text)
            if line.strip()
        ] or [text]

    for field in ("key_points", "decisions", "unresolved_items"):
        if not result[field]:
            result[field] = [EMPTY_VALUE]
    return result


def format_structured_summary(title: str, summary: str) -> str:
    parsed = parse_structured_summary(summary, title)
    parsed["topic"] = title.strip() or parsed["topic"]
    lines = [
        f"주제: {parsed['topic']}",
        f"일시: {parsed['meeting_datetime']}",
        f"참석자: {parsed['participants']}",
        f"회의 목적: {parsed['purpose']}",
        "핵심 논의:",
        *[f"- {item}" for item in parsed["key_points"]],
        "결정 사항:",
        *[f"- {item}" for item in parsed["decisions"]],
        "미결 사항:",
        *[f"- {item}" for item in parsed["unresolved_items"]],
    ]
    return "\n".join(lines)
