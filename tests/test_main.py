import unittest

from fastapi.testclient import TestClient

from app.api.routes.transcripts import router as transcript_router
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
        self.assertIn('/ui/styles.css', response.text)
        self.assertIn('/ui/app.js', response.text)
        self.assertIn("qa-dashboard", response.text)
        self.assertIn("meeting-detail", response.text)

        script = self.client.get("/ui/app.js")
        self.assertEqual(script.status_code, 200)
        self.assertIn('sessionStorage.getItem("noting_token")', script.text)
        self.assertIn("HTTPS", script.text)
        self.assertIn("updateTaskStatus", script.text)
        self.assertIn('method: "PATCH"', script.text)
        self.assertIn("startAutoAnalysis", script.text)
        self.assertIn("/analysis/start", script.text)
        self.assertIn("selectCalendarDate", script.text)

    def test_analysis_endpoint_uses_post(self):
        route = next(
            route
            for route in transcript_router.routes
            if getattr(route, "path", None) == "/transcripts/{transcript_id}/analysis"
        )

        self.assertIn("POST", route.methods)
        self.assertNotIn("GET", route.methods)

    def test_background_analysis_endpoint_uses_post(self):
        route = next(
            route
            for route in transcript_router.routes
            if getattr(route, "path", None)
            == "/transcripts/{transcript_id}/analysis/start"
        )

        self.assertIn("POST", route.methods)
        self.assertEqual(route.status_code, 202)

    def test_archive_routes_use_expected_methods(self):
        methods_by_path = {}
        for route in transcript_router.routes:
            path = getattr(route, "path", None)
            if path in {
                "/transcripts/archive",
                "/transcripts/{transcript_id}/archive",
                "/transcripts/{transcript_id}/restore",
                "/transcripts/{transcript_id}",
                "/transcripts/tasks/archive",
                "/transcripts/{transcript_id}/tasks/{task_id}/archive",
                "/transcripts/{transcript_id}/tasks/{task_id}/restore",
                "/transcripts/{transcript_id}/tasks/{task_id}",
            }:
                methods_by_path.setdefault(path, set()).update(route.methods)

        self.assertIn("GET", methods_by_path["/transcripts/archive"])
        self.assertIn(
            "POST", methods_by_path["/transcripts/{transcript_id}/archive"]
        )
        self.assertIn(
            "POST", methods_by_path["/transcripts/{transcript_id}/restore"]
        )
        self.assertIn("DELETE", methods_by_path["/transcripts/{transcript_id}"])
        self.assertIn("GET", methods_by_path["/transcripts/tasks/archive"])
        self.assertIn(
            "POST",
            methods_by_path[
                "/transcripts/{transcript_id}/tasks/{task_id}/archive"
            ],
        )
        self.assertIn(
            "POST",
            methods_by_path[
                "/transcripts/{transcript_id}/tasks/{task_id}/restore"
            ],
        )
        self.assertIn(
            "DELETE",
            methods_by_path["/transcripts/{transcript_id}/tasks/{task_id}"],
        )


if __name__ == "__main__":
    unittest.main()
