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
