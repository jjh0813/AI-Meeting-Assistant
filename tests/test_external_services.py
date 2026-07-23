import unittest
from unittest.mock import Mock, patch

import httpx

from app.services.embedding import embed
from app.services.errors import ExternalServiceError
from app.services.llm import call_llm


class ExternalServiceTests(unittest.TestCase):
    @patch("app.services.llm.httpx.post")
    def test_llm_timeout_becomes_user_safe_error(self, post):
        post.side_effect = httpx.ReadTimeout("timeout")

        with self.assertRaises(ExternalServiceError) as context:
            call_llm("prompt")

        self.assertEqual(context.exception.status_code, 504)
        self.assertNotIn("http", context.exception.detail.lower())

    @patch("app.services.embedding.httpx.post")
    def test_empty_embedding_is_rejected(self, post):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"embedding": []}
        post.return_value = response

        with self.assertRaises(ExternalServiceError) as context:
            embed("text")

        self.assertEqual(context.exception.status_code, 502)


if __name__ == "__main__":
    unittest.main()
