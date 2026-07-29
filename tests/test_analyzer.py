import unittest
from unittest.mock import patch

from app.services.analyzer import analyze
from app.services.errors import ExternalServiceError


class AnalyzerTests(unittest.TestCase):
    @patch("app.services.analyzer.call_llm")
    def test_valid_analysis_response_is_normalized(self, call_llm):
        call_llm.return_value = (
            '{"title":"서비스 배포 일정 확정",'
            '"summary":"배포 일정을 확정했다.",'
            '"tasks":[{"task":"배포","assignee":"[이름]",'
            '"due":"8월 1일","request":"점검"}]}'
        )

        result = analyze("회의 내용")

        self.assertIn("주제:", result["summary"])
        self.assertIn("핵심 논의:", result["summary"])
        self.assertIn("결정 사항:", result["summary"])
        self.assertIn("미결 사항:", result["summary"])
        self.assertEqual(result["title"], "서비스 배포 일정 확정")
        self.assertEqual(result["tasks"][0]["task"], "배포")

    @patch("app.services.analyzer.call_llm")
    def test_structured_summary_object_is_normalized(self, call_llm):
        call_llm.return_value = (
            '{"title":"베타 서비스 착수 회의",'
            '"summary":{'
            '"topic":"베타 서비스 착수",'
            '"meeting_datetime":"2026년 8월 3일 오전 10시",'
            '"participants":["김철수","박영희"],'
            '"purpose":"베타 범위와 일정을 확정합니다.",'
            '"key_points":["배포 기준을 논의했습니다."],'
            '"decisions":["8월 14일에 배포합니다."],'
            '"unresolved_items":["롤백 기준은 추가 논의합니다."]},'
            '"tasks":[{"task":"부하 테스트","assignee":"김철수",'
            '"due":"8월 6일 오후 2시","request":null}]}'
        )

        result = analyze("회의 내용")

        self.assertIn("참석자: 김철수, 박영희", result["summary"])
        self.assertIn("결정 사항:\n- 8월 14일에 배포합니다.", result["summary"])
        self.assertEqual(result["tasks"][0]["request"], "")
        self.assertIsInstance(
            call_llm.call_args.kwargs["json_schema"],
            dict,
        )

    @patch("app.services.analyzer.call_llm", return_value="not-json")
    def test_invalid_json_raises_without_returning_empty_analysis(self, _):
        with self.assertRaises(ExternalServiceError):
            analyze("회의 내용")

    @patch(
        "app.services.analyzer.call_llm",
        return_value='{"title":"회의 제목","summary":"요약","tasks":"잘못된 형식"}',
    )
    def test_invalid_task_shape_is_rejected(self, _):
        with self.assertRaises(ExternalServiceError):
            analyze("회의 내용")

    @patch(
        "app.services.analyzer.call_llm",
        return_value='{"summary":"요약","tasks":[]}',
    )
    def test_missing_generated_title_is_rejected(self, _):
        with self.assertRaises(ExternalServiceError):
            analyze("회의 내용")


if __name__ == "__main__":
    unittest.main()
