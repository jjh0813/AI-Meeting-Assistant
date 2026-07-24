import re


MEETING_ONLY_MESSAGE = (
    "Noting은 내 회의록과 업무 관련 질문만 답할 수 있습니다. "
    "회의 주제, 업무, 일정 또는 담당자를 포함해 질문해 주세요."
)
AMBIGUOUS_QUESTION_MESSAGE = (
    "어떤 회의나 업무를 뜻하는지 확인하기 어렵습니다. "
    "예: ‘모바일 반응형 문제는 이후 어떻게 됐어?’처럼 주제를 함께 입력해 주세요."
)

MEETING_CONTEXT_TERMS = (
    "회의",
    "회의록",
    "업무",
    "일정",
    "기한",
    "마감",
    "담당",
    "할 일",
    "요청",
    "결정",
    "논의",
    "안건",
    "프로젝트",
    "스프린트",
    "배포",
    "진행",
    "진척",
    "작업",
    "이슈",
    "문제",
    "보고",
    "고객",
    "매출",
    "예산",
    "계약",
    "로그인",
    "토큰",
    "업로드",
    "대시보드",
    "모바일",
    "반응형",
)

EXPLICIT_MEETING_TERMS = (
    "회의",
    "회의록",
    "논의",
    "안건",
    "업무",
    "담당",
    "결정",
    "하기로",
)

AMBIGUOUS_PATTERNS = (
    re.compile(r"^(추가로|그거|그건|그 후|이후에?)?\s*(어떻게|어찌)\s*(됐|됬|되었|돼|됨)\s*어?\??$"),
    re.compile(r"^(그래서|또|추가로|그다음은|그 후는)\??$"),
    re.compile(r"^(진행\s*상황|결과)은?\??$"),
)

OUT_OF_SCOPE_PATTERNS = (
    re.compile(
        r"(python|파이썬|javascript|자바스크립트|java|자바|c\+\+|코드|프로그램)"
        r".{0,30}(짜\s*줘|작성해\s*줘|만들어\s*줘|구현해\s*줘|"
        r"코딩해\s*줘|디버깅해\s*줘|알고리즘.{0,10}풀어\s*줘)",
        re.IGNORECASE,
    ),
    re.compile(r"(오늘|내일|이번\s*주)?\s*(날씨|기온|미세먼지|강수량|일기예보)"),
    re.compile(r"(번역|레시피|요리법|운세|로또|주가|환율|뉴스|농담).{0,15}(해줘|알려줘|추천|뭐야|어때)"),
)


def guard_meeting_question(question: str) -> tuple[str, str] | None:
    """Return a user message and reason when a question should stop before RAG."""
    normalized = " ".join(question.lower().split())

    has_topic = any(term.lower() in normalized for term in MEETING_CONTEXT_TERMS)
    has_explicit_meeting_context = any(
        term.lower() in normalized for term in EXPLICIT_MEETING_TERMS
    )
    if not has_topic and any(
        pattern.search(normalized) for pattern in AMBIGUOUS_PATTERNS
    ):
        return AMBIGUOUS_QUESTION_MESSAGE, "ambiguous_question"

    # A question explicitly framed around a meeting is allowed even when it
    # mentions code, weather, or another topic discussed in that meeting.
    if has_explicit_meeting_context:
        return None

    if any(pattern.search(normalized) for pattern in OUT_OF_SCOPE_PATTERNS):
        return MEETING_ONLY_MESSAGE, "out_of_scope"

    return None
