import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException

from app.api.routes.transcripts import stored_analysis
from app.api.routes.users import router as users_router


class AccessAndReportTests(unittest.TestCase):
    def test_same_department_list_requires_approved_user(self):
        route = next(
            route
            for route in users_router.routes
            if route.path == "/users/same-department"
        )
        dependency_names = {
            dependency.call.__name__ for dependency in route.dependant.dependencies
        }

        self.assertIn("get_approved_user", dependency_names)
        self.assertNotIn("get_current_user", dependency_names)

    @patch("app.api.routes.transcripts.transcript_repo.get_pii_entries")
    @patch("app.api.routes.transcripts.transcript_repo.get_action_items")
    @patch("app.api.routes.transcripts.transcript_repo.get_transcript")
    def test_stored_analysis_uses_persisted_summary_and_tasks(
        self, get_transcript, get_action_items, get_pii_entries
    ):
        get_transcript.return_value = SimpleNamespace(
            id=7, title="월말 결산 점검", summary="저장된 요약"
        )
        get_action_items.return_value = [
            SimpleNamespace(
                id=3,
                task="보고서 제출",
                assignee="[이름]",
                due="8월 1일",
                request="검토",
                status=SimpleNamespace(value="대기"),
                superseded_by_id=None,
            )
        ]
        get_pii_entries.return_value = []
        current_user = SimpleNamespace(display_name="김철수")

        transcript, analysis = stored_analysis(Mock(), current_user, 7)

        self.assertEqual(transcript.id, 7)
        self.assertEqual(analysis["title"], "월말 결산 점검")
        self.assertEqual(analysis["summary"], "저장된 요약")
        self.assertEqual(analysis["tasks"][0]["task"], "보고서 제출")

    @patch("app.api.routes.transcripts.transcript_repo.get_transcript")
    def test_report_requires_completed_analysis(self, get_transcript):
        get_transcript.return_value = SimpleNamespace(id=7, title=None, summary=None)

        with self.assertRaises(HTTPException) as context:
            stored_analysis(Mock(), Mock(), 7)

        self.assertEqual(context.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
