import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app.repositories.transcript import get_transcript


class AccountIsolationTests(unittest.TestCase):
    def test_transcript_lookup_filters_by_owner_user_id(self):
        query = Mock()
        query.filter.return_value = query
        query.first.return_value = None
        db = Mock()
        db.query.return_value = query

        get_transcript(db, SimpleNamespace(id=42), transcript_id=7)

        criteria = query.filter.call_args.args
        owner_filter = next(
            criterion
            for criterion in criteria
            if "owner_user_id" in str(criterion)
        )
        self.assertEqual(owner_filter.right.value, 42)


if __name__ == "__main__":
    unittest.main()
