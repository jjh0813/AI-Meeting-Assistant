import json

from sqlalchemy.orm import Session

from app.core.prompts import QUESTION_REWRITE_PROMPT
from app.models.user import User
from app.services.embedding import embed
from app.services.errors import ExternalServiceError
from app.services.llm import call_llm
from app.services.qa import answer_from_meetings
from app.services.question_guard import guard_meeting_question
from app.services.retrieval import (
    allows_semantic_only_evidence,
    answer_indicates_missing_evidence,
    has_sufficient_evidence,
)

MAX_REWRITTEN_LENGTH = 300


def _rewrite_question(question: str):
    try:
        raw = call_llm(QUESTION_REWRITE_PROMPT.format(question=question), json_mode=True)
        data = json.loads(raw)
    except (ExternalServiceError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    rewritten = str(data.get("rewritten_question") or "").strip()
    if not rewritten or rewritten == question.strip():
        return None
    if len(rewritten) > MAX_REWRITTEN_LENGTH:
        return None
    if guard_meeting_question(rewritten) is not None:
        return None
    return rewritten


def _search(db, current_user, query_text, find_rag_sources):
    query_embedding = embed(query_text)
    if query_embedding is None:
        return None
    allow_semantic_only = allows_semantic_only_evidence(query_text)
    return [
        source
        for source in find_rag_sources(db, current_user, query_text, query_embedding, limit=3)
        if has_sufficient_evidence(source, allow_semantic_only=allow_semantic_only)
    ]


def _blocked(reason, message, attempts, rewritten, rewritten_question):
    return {
        "answer": message,
        "sources": [],
        "grounded": False,
        "blocked": True,
        "blocked_reason": reason,
        "retrieval_attempts": attempts,
        "rewritten": rewritten,
        "rewritten_question": rewritten_question,
    }


def answer_question(
    db: Session,
    current_user: User,
    question: str,
    *,
    find_rag_sources,
    no_evidence_message: str,
) -> dict:
    guard_result = guard_meeting_question(question)
    if guard_result is not None:
        message, reason = guard_result
        return _blocked(reason, message, 0, False, None)

    sources = _search(db, current_user, question, find_rag_sources)
    if sources is None:
        raise ExternalServiceError(
            "검색용 임베딩을 생성하지 못했습니다. Ollama 임베딩 모델 상태를 확인해 주세요.",
            status_code=503,
        )

    attempts = 1
    rewritten_flag = False
    rewritten_question = None

    if not sources:
        rewritten_question = _rewrite_question(question)
        if rewritten_question is None:
            return _blocked("low_similarity", no_evidence_message, 1, False, None)
        rewritten_flag = True
        attempts = 2
        second = _search(db, current_user, rewritten_question, find_rag_sources)
        if not second:
            return _blocked(
                "low_similarity", no_evidence_message, 2, True, rewritten_question
            )
        sources = second

    answer = answer_from_meetings(question, sources, current_user.display_name)
    if answer_indicates_missing_evidence(answer):
        return _blocked(
            "insufficient_context", answer, attempts, rewritten_flag, rewritten_question
        )

    return {
        "answer": answer,
        "sources": sources,
        "grounded": True,
        "blocked": False,
        "blocked_reason": None,
        "retrieval_attempts": attempts,
        "rewritten": rewritten_flag,
        "rewritten_question": rewritten_question,
    }
