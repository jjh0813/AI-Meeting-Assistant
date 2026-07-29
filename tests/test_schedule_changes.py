import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException

from app.api.routes.transcripts import (
    confirm_task_schedule_change,
    find_schedule_change_candidates,
)
from app.services.task_matching import (
    assignees_match,
    has_meaningful_due,
    schedule_match_score,
)


def _task(
    task_id,
    transcript_id,
    task,
    assignee,
    due,
    created_at,
    request="",
):
    return SimpleNamespace(
        id=task_id,
        transcript_id=transcript_id,
        task=task,
        assignee=assignee,
        due=due,
        request=request,
        status=SimpleNamespace(value="대기"),
        task_embedding=[0.1] * 768,
        created_at=created_at,
    )


class ScheduleChangeMatchingTests(unittest.TestCase):
    def test_missing_due_labels_are_not_treated_as_dates(self):
        for value in ("", "언급 없음", "기한 미정", "없음", "추후 결정"):
            with self.subTest(value=value):
                self.assertFalse(has_meaningful_due(value))
        self.assertTrue(has_meaningful_due("8월 21일 금요일 오후 3시"))

    def test_unrelated_task_is_rejected_even_with_high_vector_similarity(self):
        score = schedule_match_score(
            "답변 근거 표시 방식 개선안 작성",
            "",
            "캐시 설정 조정 후 부하 테스트",
            "",
            0.91,
        )

        self.assertFalse(score.accepted)
        self.assertEqual(score.lexical_similarity, 0)

    def test_related_task_requires_shared_terms_or_very_strong_vector(self):
        related = schedule_match_score(
            "사용 가이드 최종본 제출",
            "보안 검토 반영",
            "사용 가이드 초안 작성",
            "",
            0.84,
        )
        paraphrased = schedule_match_score(
            "결과 자료 마무리",
            "",
            "최종 보고서를 완성",
            "",
            0.94,
        )

        self.assertTrue(related.accepted)
        self.assertGreaterEqual(related.lexical_similarity, 0.2)
        self.assertTrue(paraphrased.accepted)

    def test_assignee_must_match(self):
        self.assertTrue(
            assignees_match("김철수 과장", [], "김철수님", [], "김철수")
        )
        self.assertFalse(
            assignees_match("김철수", [], "박영희", [], "김철수")
        )

    def test_indexed_assignee_tokens_are_resolved_per_meeting(self):
        current_pii = [
            SimpleNamespace(
                pii_type="name",
                placeholder_token="[이름#1]",
                original_value="김철수",
            )
        ]
        previous_same = [
            SimpleNamespace(
                pii_type="name",
                placeholder_token="[이름#2]",
                original_value="김철수",
            )
        ]
        previous_other = [
            SimpleNamespace(
                pii_type="name",
                placeholder_token="[이름#1]",
                original_value="박영희",
            )
        ]

        self.assertTrue(
            assignees_match(
                "[이름#1]",
                current_pii,
                "[이름#2]",
                previous_same,
                "김철수",
            )
        )
        self.assertFalse(
            assignees_match(
                "[이름#1]",
                current_pii,
                "[이름#1]",
                previous_other,
                "김철수",
            )
        )
        self.assertFalse(
            assignees_match("[이름]", [], "[이름]", [], "김철수")
        )

    @patch("app.api.routes.transcripts.transcript_repo.get_pii_entries")
    @patch("app.api.routes.transcripts.transcript_repo.search_similar_action_items")
    @patch("app.api.routes.transcripts.transcript_repo.get_action_items")
    @patch("app.api.routes.transcripts.transcript_repo.get_transcript")
    def test_endpoint_returns_only_most_recent_valid_match(
        self,
        get_transcript,
        get_action_items,
        search_similar_action_items,
        get_pii_entries,
    ):
        current = _task(
            20,
            4,
            "사용 가이드 최종본 제출",
            "김철수",
            "8월 21일",
            datetime(2026, 8, 19, tzinfo=timezone.utc),
            request="보안 검토 반영",
        )
        unrelated = _task(
            11,
            2,
            "캐시 설정 조정 후 부하 테스트",
            "김철수",
            "8월 10일",
            datetime(2026, 8, 7, tzinfo=timezone.utc),
        )
        newest_related = _task(
            12,
            3,
            "사용 가이드 초안 작성",
            "김철수",
            "8월 14일",
            datetime(2026, 8, 12, tzinfo=timezone.utc),
        )
        older_related = _task(
            13,
            2,
            "사용 가이드 작성",
            "김철수",
            "8월 11일",
            datetime(2026, 8, 7, tzinfo=timezone.utc),
        )
        wrong_assignee = _task(
            14,
            3,
            "사용 가이드 최종본 제출",
            "박영희",
            "8월 15일",
            datetime(2026, 8, 12, tzinfo=timezone.utc),
        )
        get_transcript.return_value = SimpleNamespace(id=4)
        get_action_items.return_value = [current]
        get_pii_entries.return_value = []
        search_similar_action_items.return_value = [
            (wrong_assignee, 0.02),
            (unrelated, 0.09),
            (newest_related, 0.16),
            (older_related, 0.12),
        ]
        user = SimpleNamespace(id=1, display_name="김철수")

        result = find_schedule_change_candidates(4, user, Mock())

        self.assertEqual(len(result["change_candidates"]), 1)
        candidate = result["change_candidates"][0]
        self.assertEqual(candidate["task"]["id"], 20)
        self.assertEqual(candidate["previous_task"]["id"], 12)
        self.assertEqual(
            candidate["previous_task"]["task"],
            "사용 가이드 초안 작성",
        )

    @patch("app.api.routes.transcripts.transcript_repo.confirm_schedule_change")
    @patch("app.api.routes.transcripts.transcript_repo.get_pii_entries")
    @patch("app.api.routes.transcripts.transcript_repo.get_action_item_similarity")
    @patch("app.api.routes.transcripts.transcript_repo.get_action_item_by_id")
    @patch("app.api.routes.transcripts.transcript_repo.get_action_item")
    def test_confirmation_rejects_different_assignee(
        self,
        get_action_item,
        get_action_item_by_id,
        get_action_item_similarity,
        get_pii_entries,
        confirm_schedule_change,
    ):
        current = _task(
            20,
            4,
            "사용 가이드 최종본 제출",
            "김철수",
            "8월 21일",
            datetime(2026, 8, 19, tzinfo=timezone.utc),
        )
        previous = _task(
            12,
            3,
            "사용 가이드 초안 작성",
            "박영희",
            "8월 14일",
            datetime(2026, 8, 12, tzinfo=timezone.utc),
        )
        get_action_item.return_value = current
        get_action_item_by_id.return_value = previous
        get_action_item_similarity.return_value = 0.02
        get_pii_entries.return_value = []
        user = SimpleNamespace(id=1, display_name="김철수")

        with self.assertRaises(HTTPException) as context:
            confirm_task_schedule_change(4, 20, 12, user, Mock())

        self.assertEqual(context.exception.status_code, 400)
        confirm_schedule_change.assert_not_called()


if __name__ == "__main__":
    unittest.main()
