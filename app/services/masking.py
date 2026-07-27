import re

PHONE_PATTERN = re.compile(r"01[016-9][-.\s]?\d{3,4}[-.\s]?\d{4}")

SURNAMES = "김이박최정강조윤장임한오서신권황안송전홍유고문양손배백허남심노하곽성차주우구민류나진지엄채원천방공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국"
NAME_CANDIDATE = re.compile(rf"(?<![가-힣])([{SURNAMES}][가-힣]{{1,2}})")

TITLES = ("님", "씨", "군", "양", "과장", "대리", "부장", "차장", "사원", "팀장", "이사", "대표", "사장", "선생", "교수", "주임", "연구원")
JOSA = ("이", "가", "은", "는", "을", "를", "에게", "한테", "께", "와", "과", "랑")
STOPWORDS = {
    "이번", "이것", "이제", "이거", "이때", "이후", "이전", "정리", "정도", "조금",
    "오늘", "최근", "최고", "최대", "최소", "문제", "방법", "방향", "전체", "전달",
    "한번", "강조", "조사", "신청", "신규", "임시", "임원", "서로", "구성", "구축",
    "장소", "주소", "성명", "성함", "안건", "방안", "조치", "문의", "정보", "최종",
    "서류", "기한", "이름", "유의", "노트", "상기", "하기", "참석", "결정", "요청",
    "연락", "연락처", "연구", "연결", "연간", "조정", "조건", "조율", "유효", "유지",
    "정산", "진행", "진척", "성과", "성공", "성장", "방문", "방식", "방침", "배송",
    "결과", "고객", "확정", "차질", "차이", "정책", "박스", "허가", "심사",
    "변경", "공유",
}
NAME_THRESHOLD = 0.7
NAME_WORD = rf"[{SURNAMES}][가-힣]{{1,2}}"
NAME_LIST_PATTERN = re.compile(
    rf"(?<![가-힣])({NAME_WORD}(?:\s*(?:,|、|·|및|그리고)\s*{NAME_WORD})+)"
)
PERSON_CONTEXT_PATTERN = re.compile(
    r"참석|참여|함께|동석|모인|모여|사람|인원|인물|구성원|멤버|"
    r"담당자|발표자|보고자|진행자|사회자|세\s*명|두\s*명|네\s*명|"
    r"다섯\s*명|여섯\s*명|일곱\s*명|여덟\s*명|아홉\s*명|\d+\s*명|"
    r"세\s*분|두\s*분|네\s*분|\d+\s*분"
)


def _speaker_label(preceding: str, following: str) -> bool:
    line_prefix = preceding.rsplit("\n", 1)[-1]
    return not line_prefix.strip() and following.lstrip().startswith(":")


def _name_score(candidate: str, preceding: str, following: str) -> float:
    score = 0.35
    score += 0.15 if len(candidate) == 3 else 0.05
    head = following
    if head.startswith(TITLES):
        score += 0.5
    elif head.lstrip().startswith(TITLES):
        score += 0.45
    elif head.startswith(JOSA):
        score += 0.25
    if _speaker_label(preceding, following):
        score += 0.5
    return score


def _contextual_list_names(text: str) -> set[str]:
    contextual_names: set[str] = set()
    for list_match in NAME_LIST_PATTERN.finditer(text):
        start, end = list_match.span(1)
        surrounding = text[max(0, start - 50):min(len(text), end + 50)]
        names = [match.group(1) for match in NAME_CANDIDATE.finditer(list_match.group(1))]
        corroborated = False
        for name in names:
            for occurrence in re.finditer(re.escape(name), text):
                if start <= occurrence.start() < end:
                    continue
                preceding = text[max(0, occurrence.start() - 20):occurrence.start()]
                following = text[occurrence.end():occurrence.end() + 10]
                if _name_score(name, preceding, following) >= NAME_THRESHOLD:
                    corroborated = True
                    break
            if corroborated:
                break
        if PERSON_CONTEXT_PATTERN.search(surrounding) or corroborated:
            contextual_names.update(name for name in names if name not in STOPWORDS)
    return contextual_names


def mask_text(text: str, initial_counts: dict[str, int] | None = None):
    found = []
    counters = {
        "phone": int((initial_counts or {}).get("phone", 0)),
        "name": int((initial_counts or {}).get("name", 0)),
    }

    def _mask_phone(match):
        counters["phone"] += 1
        token = f"[전화번호#{counters['phone']}]"
        found.append(
            {
                "pii_type": "phone",
                "original_value": match.group(),
                "placeholder_token": token,
            }
        )
        return token

    masked = PHONE_PATTERN.sub(_mask_phone, text)
    contextual_list_names = _contextual_list_names(masked)

    def _mask_name(match):
        candidate = match.group(1)
        if candidate in STOPWORDS:
            return candidate
        preceding = match.string[max(0, match.start() - 4):match.start()]
        following = match.string[match.end():match.end() + 6]
        if (
            candidate in contextual_list_names
            or _name_score(candidate, preceding, following) >= NAME_THRESHOLD
        ):
            counters["name"] += 1
            token = f"[이름#{counters['name']}]"
            found.append(
                {
                    "pii_type": "name",
                    "original_value": candidate,
                    "placeholder_token": token,
                }
            )
            return token
        return candidate

    masked = NAME_CANDIDATE.sub(_mask_name, masked)
    return masked, found
