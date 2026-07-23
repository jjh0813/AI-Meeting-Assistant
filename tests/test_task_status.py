import unittest

from pydantic import ValidationError

from app.models.transcript import ActionItemStatus
from app.schemas.transcript import ActionItemStatusUpdate


class ActionItemStatusTests(unittest.TestCase):
    def test_supported_status_values(self):
        for value in ("대기", "진행중", "완료"):
            request = ActionItemStatusUpdate(status=value)
            self.assertEqual(ActionItemStatus(request.status).value, value)

    def test_unknown_status_is_rejected(self):
        with self.assertRaises(ValidationError):
            ActionItemStatusUpdate(status="취소")


if __name__ == "__main__":
    unittest.main()
