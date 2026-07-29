import unittest

from app.services.meeting_summary import (
    format_structured_summary,
    parse_structured_summary,
)


class MeetingSummaryTests(unittest.TestCase):
    def test_parses_standard_summary(self):
        summary = (
            "주제: 서비스 배포 점검\n"
            "일시: 2026년 7월 29일 오전 10시\n"
            "참석자: 김철수, [이름#2]\n"
            "회의 목적: 배포 전 위험 요소를 확인합니다.\n"
            "핵심 논의:\n"
            "- API 응답 시간을 점검했습니다.\n"
            "- 배포 순서를 합의했습니다.\n"
            "결정 사항:\n"
            "- 오후 3시에 배포합니다.\n"
            "미결 사항:\n"
            "- 모니터링 담당자를 확정해야 합니다."
        )

        result = parse_structured_summary(summary)

        self.assertEqual(result["topic"], "서비스 배포 점검")
        self.assertEqual(result["participants"], "김철수, [이름#2]")
        self.assertEqual(len(result["key_points"]), 2)
        self.assertEqual(result["decisions"], ["오후 3시에 배포합니다."])

    def test_legacy_summary_remains_available(self):
        result = parse_structured_summary(
            "배포 일정을 확정했습니다. 장애 대응 절차를 검토했습니다.",
            "주간 배포 회의",
        )

        self.assertEqual(result["topic"], "주간 배포 회의")
        self.assertEqual(len(result["key_points"]), 2)
        self.assertEqual(result["decisions"], ["언급 없음"])

    def test_formatter_fills_missing_fields(self):
        formatted = format_structured_summary(
            "월간 결산 회의",
            "핵심 논의:\n- 결산 자료를 검토했습니다.",
        )

        self.assertIn("주제: 월간 결산 회의", formatted)
        self.assertIn("일시: 언급 없음", formatted)
        self.assertIn("참석자: 언급 없음", formatted)
        self.assertIn("미결 사항:\n- 언급 없음", formatted)


if __name__ == "__main__":
    unittest.main()
