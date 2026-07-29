import unittest
from datetime import datetime, timezone

from app.services.report import build_pdf_report, build_text_report


SAMPLE_ANALYSIS = {
    "id": 12,
    "title": "서비스 배포 점검",
    "summary": (
        "주제: 서비스 배포 점검\n"
        "일시: 2026년 7월 29일 오전 10시\n"
        "참석자: 김철수, [이름#2]\n"
        "회의 목적: 배포 전 위험 요소를 확인합니다.\n"
        "핵심 논의:\n"
        "- API 응답 시간을 점검했습니다.\n"
        "- 장애 대응 절차를 검토했습니다.\n"
        "결정 사항:\n"
        "- 오후 3시에 배포합니다.\n"
        "미결 사항:\n"
        "- 모니터링 담당자를 확정해야 합니다."
    ),
    "department": "개발",
    "created_at": datetime(2026, 7, 29, 1, 30, tzinfo=timezone.utc),
    "tasks": [
        {
            "task": "배포 체크리스트 작성",
            "assignee": "김철수",
            "due": "2026년 7월 29일 오후 2시",
            "request": "배포 전에 팀에 공유",
            "status": "대기",
        }
    ],
    "masked_content": (
        "김철수님은 배포 체크리스트를 작성해 주세요.\n"
        "[이름#2]님은 모니터링 담당자를 확인해 주세요."
    ),
}


class ReportTests(unittest.TestCase):
    def test_text_report_uses_formal_sections(self):
        report = build_text_report(SAMPLE_ANALYSIS)

        self.assertIn("회의 결과 보고서", report)
        self.assertIn("1. 회의 목적", report)
        self.assertIn("3. 결정 사항", report)
        self.assertIn("5. 업무 실행 계획", report)
        self.assertIn("배포 체크리스트 작성", report)

    def test_pdf_report_is_generated(self):
        report = build_pdf_report(SAMPLE_ANALYSIS)

        self.assertTrue(report.startswith(b"%PDF"))
        self.assertGreater(len(report), 2000)


if __name__ == "__main__":
    unittest.main()
