import re


_TOKEN_PATTERN = re.compile(r"[0-9A-Za-z가-힣]+")
_STOP_WORDS = {
    "그",
    "누구",
    "무엇",
    "뭐",
    "알려줘",
    "어떻게",
    "언제",
    "얼마",
    "회의",
    "회의록",
}
_STOP_PREFIXES = ("누구", "무엇", "어떻게", "언제", "알려")
_PARTICLE_SUFFIXES = (
    "으로",
    "에서",
    "까지",
    "부터",
    "에게",
    "한테",
    "처럼",
    "보다",
    "하고",
    "이며",
    "에는",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "에",
    "의",
    "와",
    "과",
    "도",
)
_ALIASES = {
    "erp": "시스템",
    "시스템": "시스템",
    "신규": "신규",
    "새로운": "신규",
    "새": "신규",
    "전환": "전환",
    "변경": "전환",
    "교체": "전환",
    "바꾸": "전환",
    "날짜": "일정",
    "일정": "일정",
    "기한": "일정",
    "마감": "일정",
    "받기": "회수",
    "회수": "회수",
    "담당자": "담당",
    "책임자": "담당",
    "킥오프": "착수",
    "착수": "착수",
}


def _strip_particle(token: str) -> str:
    for suffix in _PARTICLE_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 2:
            return token[: -len(suffix)]
    return token


def retrieval_terms(text: str) -> set[str]:
    terms: set[str] = set()
    for raw_token in _TOKEN_PATTERN.findall(text.lower()):
        token = _strip_particle(raw_token)
        if token in _STOP_WORDS or any(
            token.startswith(prefix) for prefix in _STOP_PREFIXES
        ):
            continue
        canonical = next(
            (replacement for phrase, replacement in _ALIASES.items() if phrase in token),
            token,
        )
        if len(canonical) >= 2 or canonical.isdigit():
            terms.add(canonical)
    return terms


def lexical_similarity(query: str, document: str) -> float:
    query_terms = retrieval_terms(query)
    document_terms = retrieval_terms(document)
    if not query_terms or not document_terms:
        return 0.0
    matched = sum(
        1
        for query_term in query_terms
        if any(
            query_term == document_term
            or (
                min(len(query_term), len(document_term)) >= 2
                and (
                    query_term in document_term
                    or document_term in query_term
                )
            )
            for document_term in document_terms
        )
    )
    return matched / len(query_terms)


def rerank_sources(query: str, sources: list[dict], limit: int) -> list[dict]:
    reranked = []
    for source in sources:
        lexical = lexical_similarity(query, source["content"])
        vector = float(source["similarity"])
        reranked.append(
            {
                **source,
                "lexical_similarity": round(lexical, 4),
                "retrieval_score": round((0.65 * vector) + (0.35 * lexical), 4),
            }
        )
    return sorted(
        reranked,
        key=lambda source: (
            source["retrieval_score"],
            source["similarity"],
        ),
        reverse=True,
    )[:limit]


def has_sufficient_evidence(source: dict) -> bool:
    return (
        source["similarity"] >= 0.60
        and (
            source["lexical_similarity"] >= 0.30
            or source["retrieval_score"] >= 0.78
        )
    )


def answer_indicates_missing_evidence(answer: str) -> bool:
    normalized = re.sub(r"\s+", "", answer)
    return any(
        phrase in normalized
        for phrase in (
            "확인할수없",
            "알수없",
            "근거가없",
            "정보가없",
            "찾을수없",
        )
    )
