import unittest
from unittest.mock import patch

from app.services.analyzer import analyze
from app.services.errors import ExternalServiceError


class AnalyzerTests(unittest.TestCase):
    @patch("app.services.analyzer.call_llm")
    def test_valid_analysis_response_is_normalized(self, call_llm):
        call_llm.return_value = (
            '{"summary":"배포 일정을 확정했다.",'
            '"tasks":[{"task":"배포","assignee":"[이름]",'
            '"due":"8월 1일","request":"점검"}]}'
        )

        result = analyze("회의 내용")

        self.assertEqual(result["summary"], "배포 일정을 확정했다.")
        self.assertEqual(result["tasks"][0]["task"], "배포")

    @patch("app.services.analyzer.call_llm", return_value="not-json")
    def test_invalid_json_raises_without_returning_empty_analysis(self, _):
        with self.assertRaises(ExternalServiceError):
            analyze("회의 내용")

    @patch(
        "app.services.analyzer.call_llm",
        return_value='{"summary":"요약","tasks":"잘못된 형식"}',
    )
    def test_invalid_task_shape_is_rejected(self, _):
        with self.assertRaises(ExternalServiceError):
            analyze("회의 내용")


if __name__ == "__main__":
    unittest.main()
