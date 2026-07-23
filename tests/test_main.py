import unittest

from fastapi.testclient import TestClient

from app.main import app


class MainRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_root_redirects_to_ui(self):
        response = self.client.get("/", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "/ui/")

    def test_ui_serves_login_page(self):
        response = self.client.get("/ui/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("아이디를 입력하세요", response.text)


if __name__ == "__main__":
    unittest.main()
