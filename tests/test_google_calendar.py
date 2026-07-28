from datetime import date, datetime, timedelta, timezone

from app.services import google_calendar as gc


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
