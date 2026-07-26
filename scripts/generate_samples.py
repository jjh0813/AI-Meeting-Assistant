import json
import random
from pathlib import Path

SURNAME_GIVEN = [
    "김철수", "이영희", "박민준", "최지우", "정하윤", "강도현", "조서연", "윤예준",
    "장시우", "임하은", "한지호", "오유진", "서준영", "신아름", "권태양", "송민서",
    "안지훈", "전다은", "홍석진", "고나연", "문서진", "양준혁", "손예린", "배성우",
]
DEPTS = ["회계", "경영", "영업"]
TOPICS = [
    "3분기 예산 검토", "신규 거래처 계약", "마케팅 캠페인", "분기 실적 보고",
    "인사 평가", "제품 출시 일정", "비용 정산", "고객 클레임 대응",
]
TASKS = [
    "예산안 작성", "계약서 검토", "보고서 정리", "견적서 발송",
    "일정 조율", "자료 취합", "품의서 제출", "회의록 배포",
]
DUES = ["다음 주 금요일", "이번 달 말", "내일 오전", "3일 이내", "다음 주 월요일", "월말까지"]
TITLES = ["과장", "대리", "부장", "팀장", "사원", "차장"]


def _phone():
    return f"010-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}"


def make_sample(i):
    names = random.sample(SURNAME_GIVEN, 3)
    phones = [_phone()]
    dept = random.choice(DEPTS)
    topic = random.choice(TOPICS)
    t1, t2 = random.sample(TASKS, 2)
    d1, d2 = random.sample(DUES, 2)
    text = (
        f"{dept}팀 {topic} 회의입니다. "
        f"{names[0]} {random.choice(TITLES)}이 {topic} 현황을 보고했습니다. "
        f"{names[1]}에게 {phones[0]}로 연락해 {t1}을 요청하기로 했고, "
        f"{names[2]} {random.choice(TITLES)}는 {d1}까지 {t2}을 완료하기로 했습니다. "
        f"세부 사항은 {d2}에 다시 논의합니다."
    )
    return {
        "id": i,
        "department": dept,
        "text": text,
        "expected_names": names,
        "expected_phones": phones,
    }


def main():
    random.seed(42)
    samples = [make_sample(i) for i in range(1, 101)]
    out = Path(__file__).resolve().parents[1] / "data" / "samples" / "meeting_samples.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"generated {len(samples)} samples -> {out}")


if __name__ == "__main__":
    main()
