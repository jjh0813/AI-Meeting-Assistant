import unittest
from types import SimpleNamespace

from app.services.masking import mask_text
from app.services.personalization import (
    is_assigned_to_user,
    personalize_masked_text,
    remask_personalized_text,
)


class PersonalizationTests(unittest.TestCase):
    def test_masking_creates_stable_indexed_name_tokens(self):
        masked, entries = mask_text("김철수님은 작성하고 박영희님은 검토합니다.")

        self.assertIn("[이름#1]", masked)
        self.assertIn("[이름#2]", masked)
        self.assertEqual(entries[0]["original_value"], "김철수")
        self.assertEqual(entries[0]["placeholder_token"], "[이름#1]")

    def test_spoken_participant_list_is_masked_from_natural_context(self):
        masked, entries = mask_text(
            "오늘 김철수, 박영희, 이민수 이렇게 세 명이 함께 회의했습니다."
        )

        self.assertEqual(masked.count("[이름#"), 3)
        self.assertEqual(
            [entry["original_value"] for entry in entries],
            ["김철수", "박영희", "이민수"],
        )

    def test_names_in_list_are_masked_when_corroborated_later(self):
        masked, entries = mask_text(
            "김철수, 박영희, 이민수 순서로 의견을 냈습니다. "
            "마지막으로 김철수님이 결론을 정리했습니다."
        )

        self.assertEqual(masked.count("[이름#"), 4)
        self.assertEqual(
            {entry["original_value"] for entry in entries},
            {"김철수", "박영희", "이민수"},
        )

    def test_general_work_list_is_not_mistaken_for_names(self):
        masked, entries = mask_text(
            "일정, 변경, 조치 사항을 확인하고 프로젝트 변경, 결과 공유 및 정리를 논의했습니다."
        )

        self.assertEqual(
            masked,
            "일정, 변경, 조치 사항을 확인하고 프로젝트 변경, 결과 공유 및 정리를 논의했습니다.",
        )
        self.assertEqual(entries, [])

    def test_speaker_label_is_masked_without_structured_participant_header(self):
        masked, entries = mask_text("김철수: 배포 일정을 확인하겠습니다.")

        self.assertTrue(masked.startswith("[이름#1]:"))
        self.assertEqual(entries[0]["original_value"], "김철수")

    def test_only_current_users_name_is_restored(self):
        entries = [
            SimpleNamespace(
                pii_type="name",
                original_value="김철수",
                placeholder_token="[이름#1]",
            ),
            SimpleNamespace(
                pii_type="name",
                original_value="박영희",
                placeholder_token="[이름#2]",
            ),
        ]

        result = personalize_masked_text(
            "[이름#1]님은 작성하고 [이름#2]님은 검토합니다.",
            entries,
            "김철수",
        )

        self.assertEqual(result, "김철수님은 작성하고 [이름]님은 검토합니다.")

    def test_assignment_uses_private_token_mapping(self):
        entries = [
            SimpleNamespace(
                pii_type="name",
                original_value="김철수",
                placeholder_token="[이름#1]",
            )
        ]

        self.assertTrue(is_assigned_to_user("[이름#1]", entries, "김철수"))
        self.assertFalse(is_assigned_to_user("[이름#1]", entries, "박영희"))

    def test_edit_preserves_other_users_hidden_identity(self):
        entries = [
            SimpleNamespace(
                pii_type="name",
                original_value="김철수",
                placeholder_token="[이름#1]",
            ),
            SimpleNamespace(
                pii_type="name",
                original_value="박영희",
                placeholder_token="[이름#2]",
            ),
        ]

        masked, saved_entries = remask_personalized_text(
            "김철수님은 작성하고 [이름]님은 검토합니다.",
            entries,
            "김철수",
        )

        self.assertIn("[이름#2]", masked)
        self.assertIn("[이름#3]", masked)
        self.assertEqual(
            {entry["original_value"] for entry in saved_entries},
            {"김철수", "박영희"},
        )


if __name__ == "__main__":
    unittest.main()
