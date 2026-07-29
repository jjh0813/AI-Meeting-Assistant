from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.repositories.transcript import deduplicate_analysis_tasks
from app.repositories.transcript import create_transcript


def test_deduplicate_analysis_tasks_removes_exact_normalized_duplicates():
    tasks = [
        {
            "task": "답변 근거 표시 방식의 개선안 작성",
            "assignee": "김철수",
            "due": "8월 21일 오후 3시",
            "request": "개선안을 작성해 주세요.",
        },
        {
            "task": "  답변 근거 표시 방식의  개선안 작성 ",
            "assignee": "김철수",
            "due": "8월 21일 오후 3시",
            "request": "개선안을 작성해 주세요.",
        },
    ]

    result = deduplicate_analysis_tasks(tasks)

    assert result == [tasks[0]]


def test_deduplicate_analysis_tasks_keeps_real_schedule_changes():
    tasks = [
        {
            "task": "답변 근거 표시 방식의 개선안 작성",
            "assignee": "김철수",
            "due": "8월 14일 오후 1시",
            "request": "",
        },
        {
            "task": "답변 근거 표시 방식의 개선안 작성",
            "assignee": "김철수",
            "due": "8월 21일 오후 3시",
            "request": "",
        },
    ]

    result = deduplicate_analysis_tasks(tasks)

    assert result == tasks


class _CreateTranscriptSession:
    def __init__(self):
        self.added = []

    def add(self, value):
        self.added.append(value)

    def flush(self):
        self.added[0].id = 1

    def commit(self):
        pass

    def refresh(self, value):
        pass


def test_create_transcript_uses_selected_meeting_date_at_kst_noon():
    db = _CreateTranscriptSession()
    user = SimpleNamespace(id=7, department="개발")

    transcript = create_transcript(
        db,
        user,
        "masked meeting",
        [],
        meeting_date=date(2026, 8, 16),
    )

    assert transcript.created_at == datetime(2026, 8, 16, 3, 0, tzinfo=timezone.utc)
