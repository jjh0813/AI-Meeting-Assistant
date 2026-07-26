import pytest

from app.services import agentic_rag as ar

NO_EV = "근거없음"


class FakeUser:
    display_name = "장재형"


@pytest.fixture
def patched(monkeypatch):
    state = {"find_calls": 0, "rewrite_calls": 0, "answer_questions": []}
    monkeypatch.setattr(ar, "embed", lambda q: [0.1] * 768)
    monkeypatch.setattr(ar, "has_sufficient_evidence", lambda s, allow_semantic_only=False: True)
    monkeypatch.setattr(ar, "allows_semantic_only_evidence", lambda q: False)
    monkeypatch.setattr(ar, "guard_meeting_question", lambda q: None)
    monkeypatch.setattr(ar, "answer_indicates_missing_evidence", lambda a: False)

    def _answer(q, sources, name):
        state["answer_questions"].append(q)
        return "답변"

    monkeypatch.setattr(ar, "answer_from_meetings", _answer)
    return state, monkeypatch


def _find(state, sequences):
    def inner(db, user, q, emb, limit=3):
        i = state["find_calls"]
        state["find_calls"] += 1
        return sequences[i] if i < len(sequences) else []

    return inner


def _llm(state, json_text=None, raises=False):
    def inner(prompt, json_mode=False):
        state["rewrite_calls"] += 1
        if raises:
            raise ar.ExternalServiceError("x")
        return json_text

    return inner


def _call(find):
    return ar.answer_question(
        object(), FakeUser(), "내 할 일 뭐야?",
        find_rag_sources=find, no_evidence_message=NO_EV,
    )


def test_first_search_success_no_rewrite(patched):
    state, mp = patched
    mp.setattr(ar, "call_llm", _llm(state))
    r = _call(_find(state, [[{"id": 1}]]))
    assert r["grounded"] and r["retrieval_attempts"] == 1 and r["rewritten"] is False
    assert state["rewrite_calls"] == 0
    assert state["answer_questions"] == ["내 할 일 뭐야?"]


def test_rewrite_then_success_uses_original_question(patched):
    state, mp = patched
    mp.setattr(ar, "call_llm", _llm(state, '{"rewritten_question":"내 담당 업무"}'))
    r = _call(_find(state, [[], [{"id": 2}]]))
    assert r["grounded"] and r["retrieval_attempts"] == 2 and r["rewritten"] is True
    assert r["rewritten_question"] == "내 담당 업무"
    assert state["answer_questions"] == ["내 할 일 뭐야?"]


def test_rewrite_then_still_blocked(patched):
    state, mp = patched
    mp.setattr(ar, "call_llm", _llm(state, '{"rewritten_question":"내 담당 업무"}'))
    r = _call(_find(state, [[], []]))
    assert r["blocked"] and r["blocked_reason"] == "low_similarity"
    assert r["retrieval_attempts"] == 2


def test_rewrite_json_fail_blocks(patched):
    state, mp = patched
    mp.setattr(ar, "call_llm", _llm(state, "not json"))
    r = _call(_find(state, [[]]))
    assert r["blocked"] and r["blocked_reason"] == "low_similarity"
    assert r["retrieval_attempts"] == 1


def test_rewrite_llm_error_no_crash(patched):
    state, mp = patched
    mp.setattr(ar, "call_llm", _llm(state, raises=True))
    r = _call(_find(state, [[]]))
    assert r["blocked"] and r["blocked_reason"] == "low_similarity"


def test_out_of_scope_skips_embed_and_llm(patched):
    state, mp = patched
    mp.setattr(ar, "guard_meeting_question", lambda q: ("범위 밖", "out_of_scope"))
    mp.setattr(ar, "call_llm", _llm(state))
    r = _call(_find(state, [[{"id": 1}]]))
    assert r["blocked"] and r["blocked_reason"] == "out_of_scope"
    assert state["find_calls"] == 0 and state["rewrite_calls"] == 0
