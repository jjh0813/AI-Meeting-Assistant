from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.services import google_calendar as gc
from app.services.errors import ExternalServiceError


KST = timezone(timedelta(hours=9))


def test_parse_korean_all_day_due():
    parsed = gc.parse_due_text(
        "8월 1일까지",
        now=datetime(2026, 7, 27, 12, 0, tzinfo=KST),
    )

    assert parsed is not None
    assert parsed.all_day is True
    assert parsed.start == date(2026, 8, 1)
    assert parsed.end == date(2026, 8, 2)


def test_parse_korean_timed_due_as_one_hour_event():
    parsed = gc.parse_due_text(
        "2026년 8월 3일 오후 2시 30분",
        now=datetime(2026, 7, 27, 12, 0, tzinfo=KST),
    )

    assert parsed is not None
    assert parsed.all_day is False
    assert parsed.start.isoformat() == "2026-08-03T14:30:00+09:00"
    assert parsed.end - parsed.start == timedelta(hours=1)


def test_parse_relative_due():
    parsed = gc.parse_due_text(
        "내일 오전 10시",
        now=datetime(2026, 7, 27, 12, 0, tzinfo=KST),
    )

    assert parsed is not None
    assert parsed.start.isoformat() == "2026-07-28T10:00:00+09:00"


def test_invalid_due_returns_none():
    assert gc.parse_due_text("다음 회의 전까지") is None
    assert gc.parse_due_text("2026년 13월 40일") is None


def test_event_body_has_one_day_popup_and_email_reminders(monkeypatch):
    monkeypatch.setattr(gc.settings, "google_calendar_reminder_minutes", 1440)
    parsed = gc.ParsedDue(
        start=date(2026, 8, 1),
        end=date(2026, 8, 2),
        all_day=True,
    )

    body = gc._event_body(
        title="보고서 제출",
        description="Noting 업무",
        parsed_due=parsed,
        action_item_id=7,
        user_id=3,
    )

    assert body["start"] == {"date": "2026-08-01"}
    assert body["end"] == {"date": "2026-08-02"}
    assert body["reminders"]["useDefault"] is False
    assert body["reminders"]["overrides"] == [
        {"method": "popup", "minutes": 1440},
        {"method": "email", "minutes": 1440},
    ]
    private = body["extendedProperties"]["private"]
    assert private["notingActionItemId"] == "7"
    assert private["notingUserId"] == "3"


def test_oauth_state_round_trip():
    user = type("User", (), {"id": 42})()

    state = gc.create_oauth_state(user)

    assert gc.verify_oauth_state(state) == 42


def test_oauth_requests_permission_for_app_created_calendars():
    assert "https://www.googleapis.com/auth/calendar.app.created" in gc.GOOGLE_SCOPES


def test_oauth_always_prompts_for_google_account_selection(monkeypatch):
    monkeypatch.setattr(gc.settings, "google_client_id", "client-id")
    monkeypatch.setattr(gc.settings, "google_client_secret", "client-secret")
    monkeypatch.setattr(
        gc.settings,
        "google_calendar_redirect_uri",
        "https://noting.example/calendar/google/callback",
    )

    url = gc.build_authorization_url(SimpleNamespace(id=7))
    query = parse_qs(urlparse(url).query)

    assert query["prompt"] == ["select_account consent"]


def test_dedicated_calendar_body_identifies_noting_account(monkeypatch):
    monkeypatch.setattr(gc.settings, "google_calendar_timezone", "Asia/Seoul")
    user = SimpleNamespace(
        id=7,
        username="acc_user",
        display_name="김철수",
    )

    body = gc._dedicated_calendar_body(user)

    assert body["summary"] == "Noting - 김철수 (acc_user)"
    assert "acc_user 전용 캘린더" in body["description"]
    assert body["timeZone"] == "Asia/Seoul"


def test_create_dedicated_calendar_returns_google_calendar_id(monkeypatch):
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"id": "noting-user-7@group.calendar.google.com"}
    post = Mock(return_value=response)
    monkeypatch.setattr(gc.httpx, "post", post)
    user = SimpleNamespace(
        id=7,
        username="acc_user",
        display_name="김철수",
    )

    calendar_id = gc._create_dedicated_calendar("access-token", user)

    assert calendar_id == "noting-user-7@group.calendar.google.com"
    assert post.call_args.args[0] == f"{gc.GOOGLE_CALENDAR_API}/calendars"
    assert post.call_args.kwargs["json"]["summary"] == "Noting - 김철수 (acc_user)"


def test_create_dedicated_calendar_rejects_missing_id(monkeypatch):
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {}
    monkeypatch.setattr(gc.httpx, "post", Mock(return_value=response))
    user = SimpleNamespace(username="acc_user", display_name="김철수")

    with pytest.raises(ExternalServiceError) as exc_info:
        gc._create_dedicated_calendar("access-token", user)

    assert exc_info.value.status_code == 502


def test_sync_automatically_prepares_legacy_primary_calendar(monkeypatch):
    connection = SimpleNamespace(calendar_id="primary")
    monkeypatch.setattr(gc, "get_connection", Mock(return_value=connection))
    monkeypatch.setattr(gc, "get_access_token", Mock(return_value="access-token"))
    create_calendar = Mock(
        return_value="noting-user-7@group.calendar.google.com"
    )
    monkeypatch.setattr(gc, "_create_dedicated_calendar", create_calendar)
    monkeypatch.setattr(gc, "_personal_sync_tasks", Mock(return_value=[]))
    db = Mock()
    links_query = Mock()
    links_query.filter.return_value = links_query
    links_query.all.return_value = []
    db.query.return_value = links_query

    result = gc.sync_user_tasks(db, SimpleNamespace(id=7))

    assert result["calendar_id"] == "noting-user-7@group.calendar.google.com"
    assert connection.calendar_id == "noting-user-7@group.calendar.google.com"
    create_calendar.assert_called_once()


def test_create_dedicated_calendar_requests_reconnect_when_scope_is_missing(
    monkeypatch,
):
    request = httpx.Request("POST", f"{gc.GOOGLE_CALENDAR_API}/calendars")
    response = httpx.Response(403, request=request)
    google_response = Mock()
    google_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "forbidden",
        request=request,
        response=response,
    )
    monkeypatch.setattr(gc.httpx, "post", Mock(return_value=google_response))
    user = SimpleNamespace(username="acc_user", display_name="김철수")

    with pytest.raises(ExternalServiceError) as exc_info:
        gc._create_dedicated_calendar("access-token", user)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Google Calendar 연결 권한을 갱신해 주세요."


def test_inactive_connection_preserves_calendar_but_reports_disconnected(monkeypatch):
    connection = SimpleNamespace(
        calendar_id="noting-user-7@group.calendar.google.com",
        google_email="owner@example.com",
        encrypted_refresh_token=None,
        encrypted_access_token=None,
    )
    monkeypatch.setattr(
        gc,
        "get_connection_record",
        Mock(return_value=connection),
    )

    status = gc.connection_status(Mock(), SimpleNamespace(id=7))

    assert status["connected"] is False
    assert status["isolated"] is True
    assert status["calendar_id"] == "noting-user-7@group.calendar.google.com"


def test_disconnect_does_not_revoke_shared_google_account(monkeypatch):
    connection = SimpleNamespace(
        id=10,
        google_subject="google-user-1",
        google_email="shared@example.com",
        encrypted_refresh_token="encrypted-refresh",
        encrypted_access_token="encrypted-access",
    )
    monkeypatch.setattr(gc, "get_connection_record", Mock(return_value=connection))
    revoke = Mock()
    monkeypatch.setattr(gc.httpx, "post", revoke)
    db = Mock()
    shared_query = Mock()
    shared_query.filter.return_value = shared_query
    shared_query.first.return_value = SimpleNamespace(id=11)
    db.query.return_value = shared_query

    assert gc.disconnect_calendar(db, SimpleNamespace(id=7)) is True

    revoke.assert_not_called()
    assert connection.encrypted_access_token is None
    assert connection.encrypted_refresh_token is None
    db.add.assert_called_once_with(connection)
    db.commit.assert_called_once()


def test_disconnect_revokes_when_google_account_is_not_shared(monkeypatch):
    connection = SimpleNamespace(
        id=10,
        google_subject="google-user-1",
        google_email="owner@example.com",
        encrypted_refresh_token="encrypted-refresh",
        encrypted_access_token="encrypted-access",
    )
    monkeypatch.setattr(gc, "get_connection_record", Mock(return_value=connection))
    monkeypatch.setattr(gc, "_decrypt", Mock(return_value="refresh-token"))
    revoke_response = Mock(spec=httpx.Response)
    revoke = Mock(return_value=revoke_response)
    monkeypatch.setattr(gc.httpx, "post", revoke)
    db = Mock()
    shared_query = Mock()
    shared_query.filter.return_value = shared_query
    shared_query.first.return_value = None
    db.query.return_value = shared_query

    assert gc.disconnect_calendar(db, SimpleNamespace(id=7)) is True

    assert revoke.call_args.args[0] == gc.GOOGLE_REVOKE_URL
    assert connection.encrypted_access_token is None
    assert connection.encrypted_refresh_token is None


def test_sync_deletes_event_link_for_completed_or_inactive_task(monkeypatch):
    connection = SimpleNamespace(
        calendar_id="noting-user-7@group.calendar.google.com"
    )
    link = SimpleNamespace(
        action_item_id=31,
        calendar_id=connection.calendar_id,
        google_event_id="google-event-31",
    )
    monkeypatch.setattr(gc, "get_connection", Mock(return_value=connection))
    monkeypatch.setattr(
        gc, "_ensure_dedicated_calendar", Mock(return_value=connection.calendar_id)
    )
    monkeypatch.setattr(gc, "_personal_sync_tasks", Mock(return_value=[]))
    request = Mock(return_value={})
    monkeypatch.setattr(gc, "_calendar_request", request)
    db = Mock()
    links_query = Mock()
    links_query.filter.return_value = links_query
    links_query.all.return_value = [link]
    db.query.return_value = links_query

    result = gc.sync_user_tasks(db, SimpleNamespace(id=7))

    assert result["deleted"] == 1
    assert result["delete_failed"] == 0
    assert request.call_args.args[2] == "DELETE"
    assert "google-event-31" in request.call_args.args[3]
    db.delete.assert_called_once_with(link)


def test_sync_keeps_event_link_when_google_delete_fails(monkeypatch):
    connection = SimpleNamespace(
        calendar_id="noting-user-7@group.calendar.google.com"
    )
    link = SimpleNamespace(
        action_item_id=31,
        calendar_id=connection.calendar_id,
        google_event_id="google-event-31",
    )
    monkeypatch.setattr(gc, "get_connection", Mock(return_value=connection))
    monkeypatch.setattr(
        gc, "_ensure_dedicated_calendar", Mock(return_value=connection.calendar_id)
    )
    monkeypatch.setattr(gc, "_personal_sync_tasks", Mock(return_value=[]))
    monkeypatch.setattr(
        gc,
        "_calendar_request",
        Mock(side_effect=ExternalServiceError("Google 삭제 실패", status_code=502)),
    )
    db = Mock()
    links_query = Mock()
    links_query.filter.return_value = links_query
    links_query.all.return_value = [link]
    db.query.return_value = links_query

    result = gc.sync_user_tasks(db, SimpleNamespace(id=7))

    assert result["deleted"] == 0
    assert result["delete_failed"] == 1
    db.delete.assert_not_called()
