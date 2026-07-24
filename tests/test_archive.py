import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app.repositories.transcript import (
    archive_action_item,
    archive_transcript,
    delete_archived_action_item,
    delete_archived_transcript,
    restore_action_item,
    restore_transcript,
)


class TranscriptArchiveTests(unittest.TestCase):
    def test_archive_marks_transcript_and_commits(self):
        db = Mock()
        transcript = SimpleNamespace(archived=False, archived_at=None)

        result = archive_transcript(db, transcript)

        self.assertTrue(result.archived)
        self.assertIsNotNone(result.archived_at)
        db.commit.assert_called_once()
        db.refresh.assert_called_once_with(transcript)

    def test_restore_clears_archive_state(self):
        db = Mock()
        transcript = SimpleNamespace(archived=True, archived_at="stored")

        result = restore_transcript(db, transcript)

        self.assertFalse(result.archived)
        self.assertIsNone(result.archived_at)
        db.commit.assert_called_once()
        db.refresh.assert_called_once_with(transcript)

    def test_permanent_delete_rejects_active_transcript(self):
        db = Mock()
        transcript = SimpleNamespace(archived=False)

        with self.assertRaises(ValueError):
            delete_archived_transcript(db, transcript)

        db.delete.assert_not_called()
        db.commit.assert_not_called()

    def test_action_item_archive_and_restore(self):
        db = Mock()
        item = SimpleNamespace(archived=False, archived_at=None)

        archive_action_item(db, item)
        self.assertTrue(item.archived)
        self.assertIsNotNone(item.archived_at)

        restore_action_item(db, item)
        self.assertFalse(item.archived)
        self.assertIsNone(item.archived_at)
        self.assertEqual(db.commit.call_count, 2)

    def test_permanent_delete_rejects_active_action_item(self):
        db = Mock()
        item = SimpleNamespace(archived=False)

        with self.assertRaises(ValueError):
            delete_archived_action_item(db, item)

        db.delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
