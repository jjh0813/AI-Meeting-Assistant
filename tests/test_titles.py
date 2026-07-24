import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app.repositories.transcript import update_transcript_title


class TranscriptTitleTests(unittest.TestCase):
    def test_manual_title_is_persisted_and_protected_from_reanalysis(self):
        db = Mock()
        transcript = SimpleNamespace(
            title="AI 자동 제목",
            title_is_manual=False,
        )

        updated = update_transcript_title(db, transcript, "사용자가 수정한 제목")

        self.assertEqual(updated.title, "사용자가 수정한 제목")
        self.assertTrue(updated.title_is_manual)
        db.commit.assert_called_once()
        db.refresh.assert_called_once_with(transcript)


if __name__ == "__main__":
    unittest.main()
