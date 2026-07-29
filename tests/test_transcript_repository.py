from app.repositories.transcript import deduplicate_analysis_tasks


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
