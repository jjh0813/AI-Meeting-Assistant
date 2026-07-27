import json
import operator
import re
from dataclasses import dataclass
from typing import Annotated, Callable, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
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
    asks_for_personal_tasks,
    has_sufficient_evidence,
)

MAX_RETRIEVAL_ATTEMPTS = 2
MAX_REWRITTEN_LENGTH = 300

INTENT_LABELS = {
    "personal_task": "내 담당 업무",
    "task": "업무·담당자",
    "schedule": "일정·기한",
    "decision": "결정 사항",
    "unresolved": "미결·보류 사항",
    "general": "일반 회의 내용",
}
RETRIEVERS_BY_INTENT = {
    "personal_task": ["action_item"],
    "task": ["action_item", "chunk"],
    "schedule": ["action_item", "chunk"],
    "decision": ["summary", "chunk"],
    "unresolved": ["action_item", "chunk", "summary"],
    "general": ["chunk", "summary", "action_item"],
}
SOURCE_LABELS = {
    "chunk": "회의 본문",
    "summary": "회의 요약",
    "action_item": "실행 항목",
}
_SCHEDULE_TERMS = re.compile(r"일정|기한|마감|언제|날짜|몇\s*시|회의\s*시간")
_TASK_TERMS = re.compile(r"업무|할\s*일|담당|책임자|누가|요청\s*사항")
_DECISION_TERMS = re.compile(r"결정|확정|합의|정하기로|결론")
_UNRESOLVED_TERMS = re.compile(
    r"미결|미정|보류|정해지지|확정되지|추가\s*논의|남은\s*문제|해결되지"
)


class AgentState(TypedDict, total=False):
    question: str
    query: str
    intent: str
    selected_source_types: list[str]
    raw_sources: list[dict]
    sources: list[dict]
    answer: str
    blocked: bool
    blocked_reason: str | None
    grounded: bool
    retrieval_attempts: int
    rewritten: bool
    rewritten_question: str | None
    evidence_sufficient: bool
    verification: str
    trace: Annotated[list[dict], operator.add]


@dataclass(frozen=True)
class AgentRuntime:
    db: Session
    current_user: User
    find_rag_sources: Callable
    no_evidence_message: str


def classify_question_intent(question: str) -> str:
    normalized = " ".join(question.lower().split())
    if asks_for_personal_tasks(normalized):
        return "personal_task"
    if _UNRESOLVED_TERMS.search(normalized):
        return "unresolved"
    if _SCHEDULE_TERMS.search(normalized):
        return "schedule"
    if _TASK_TERMS.search(normalized):
        return "task"
    if _DECISION_TERMS.search(normalized):
        return "decision"
    return "general"


def _event(node: str, label: str, status: str, detail: str) -> dict:
    return {
        "node": node,
        "label": label,
        "status": status,
        "detail": detail,
    }


def _rewrite_question(question: str) -> str | None:
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


def _search(
    runtime: AgentRuntime,
    query_text: str,
    original_question: str,
    source_types: list[str],
) -> list[dict]:
    query_embedding = embed(query_text)
    if query_embedding is None:
        raise ExternalServiceError(
            "검색용 임베딩을 생성하지 못했습니다. Ollama 임베딩 모델 상태를 확인해 주세요.",
            status_code=503,
        )
    return runtime.find_rag_sources(
        runtime.db,
        runtime.current_user,
        query_text,
        query_embedding,
        limit=3,
        source_types=set(source_types),
    )


def _build_agent_graph(runtime: AgentRuntime):
    def scope_guard(state: AgentState) -> dict:
        guard_result = guard_meeting_question(state["question"])
        if guard_result is not None:
            message, reason = guard_result
            return {
                "answer": message,
                "blocked": True,
                "blocked_reason": reason,
                "grounded": False,
                "verification": "blocked",
                "trace": [
                    _event(
                        "scope_guard",
                        "질문 범위 검사",
                        "blocked",
                        "회의록·업무 범위를 벗어나 검색 전에 차단했습니다.",
                    )
                ],
            }
        return {
            "blocked": False,
            "trace": [
                _event(
                    "scope_guard",
                    "질문 범위 검사",
                    "completed",
                    "회의록과 업무에 관한 질문으로 확인했습니다.",
                )
            ],
        }

    def route_intent(state: AgentState) -> dict:
        intent = classify_question_intent(state["question"])
        return {
            "intent": intent,
            "trace": [
                _event(
                    "route_intent",
                    "질문 의도 분류",
                    "completed",
                    f"질문을 ‘{INTENT_LABELS[intent]}’ 유형으로 분류했습니다.",
                )
            ],
        }

    def select_retriever(state: AgentState) -> dict:
        source_types = RETRIEVERS_BY_INTENT[state["intent"]]
        labels = " · ".join(SOURCE_LABELS[item] for item in source_types)
        return {
            "selected_source_types": source_types,
            "trace": [
                _event(
                    "select_retriever",
                    "검색기 선택",
                    "completed",
                    f"{labels} 검색기를 선택했습니다.",
                )
            ],
        }

    def retrieve(state: AgentState) -> dict:
        attempt = state.get("retrieval_attempts", 0) + 1
        sources = _search(
            runtime,
            state["query"],
            state["question"],
            state["selected_source_types"],
        )
        return {
            "raw_sources": sources,
            "retrieval_attempts": attempt,
            "trace": [
                _event(
                    "retrieve",
                    "회의 근거 검색",
                    "completed",
                    f"{attempt}차 검색에서 후보 근거 {len(sources)}건을 찾았습니다.",
                )
            ],
        }

    def grade_evidence(state: AgentState) -> dict:
        allow_semantic_only = allows_semantic_only_evidence(state["question"])
        sufficient = [
            source
            for source in state.get("raw_sources", [])
            if has_sufficient_evidence(
                source, allow_semantic_only=allow_semantic_only
            )
        ]
        enough = bool(sufficient)
        top_score = max(
            (
                float(source.get("retrieval_score", source.get("similarity", 0)))
                for source in state.get("raw_sources", [])
            ),
            default=0,
        )
        if enough:
            detail = (
                f"기준을 통과한 근거 {len(sufficient)}건을 확보했습니다. "
                f"최고 검색 점수는 {top_score:.4f}입니다."
            )
            status = "completed"
        elif state["retrieval_attempts"] < MAX_RETRIEVAL_ATTEMPTS:
            detail = (
                f"충분한 근거가 없어 질문을 한 번 보정합니다. "
                f"현재 최고 검색 점수는 {top_score:.4f}입니다."
            )
            status = "retry"
        else:
            detail = "두 번의 검색에서도 답변할 근거를 확보하지 못했습니다."
            status = "blocked"
        updates = {
            "sources": sufficient,
            "evidence_sufficient": enough,
            "trace": [
                _event(
                    "grade_evidence",
                    "근거 품질 평가",
                    status,
                    detail,
                )
            ],
        }
        if not enough and state["retrieval_attempts"] >= MAX_RETRIEVAL_ATTEMPTS:
            updates.update(
                {
                    "answer": runtime.no_evidence_message,
                    "blocked": True,
                    "blocked_reason": "low_similarity",
                    "grounded": False,
                    "verification": "insufficient_evidence",
                }
            )
        return updates

    def rewrite_query(state: AgentState) -> dict:
        rewritten = _rewrite_question(state["question"])
        if rewritten is None:
            return {
                "answer": runtime.no_evidence_message,
                "blocked": True,
                "blocked_reason": "low_similarity",
                "grounded": False,
                "verification": "rewrite_failed",
                "trace": [
                    _event(
                        "rewrite_query",
                        "검색 질문 보정",
                        "blocked",
                        "원래 의미를 보존하는 안전한 검색 질문을 만들지 못했습니다.",
                    )
                ],
            }
        return {
            "query": rewritten,
            "rewritten": True,
            "rewritten_question": rewritten,
            "trace": [
                _event(
                    "rewrite_query",
                    "검색 질문 보정",
                    "retry",
                    f"원래 의도를 유지한 질문으로 보정했습니다: {rewritten}",
                )
            ],
        }

    def generate_answer(state: AgentState) -> dict:
        answer = answer_from_meetings(
            state["question"],
            state["sources"],
            runtime.current_user.display_name,
        )
        return {
            "answer": answer,
            "trace": [
                _event(
                    "generate_answer",
                    "근거 기반 답변 생성",
                    "completed",
                    f"검증된 회의 근거 {len(state['sources'])}건만 사용했습니다.",
                )
            ],
        }

    def verify_answer(state: AgentState) -> dict:
        missing = answer_indicates_missing_evidence(state["answer"])
        if missing:
            return {
                "blocked": True,
                "blocked_reason": "insufficient_context",
                "grounded": False,
                "verification": "insufficient_context",
                "trace": [
                    _event(
                        "verify_answer",
                        "답변 근거 검증",
                        "blocked",
                        "생성된 답변이 근거 부족을 나타내므로 최종 답변을 차단했습니다.",
                    )
                ],
            }
        return {
            "blocked": False,
            "blocked_reason": None,
            "grounded": True,
            "verification": "passed",
            "trace": [
                _event(
                    "verify_answer",
                    "답변 근거 검증",
                    "completed",
                    "회의록 근거로 답변할 수 있음을 확인했습니다.",
                )
            ],
        }

    def finish(state: AgentState) -> dict:
        return {
            "trace": [
                _event(
                    "finish",
                    "처리 완료",
                    "blocked" if state.get("blocked") else "completed",
                    "안전하게 차단했습니다."
                    if state.get("blocked")
                    else "근거와 함께 답변을 완료했습니다.",
                )
            ]
        }

    def after_scope(state: AgentState) -> Literal["route_intent", "finish"]:
        return "finish" if state.get("blocked") else "route_intent"

    def after_grade(
        state: AgentState,
    ) -> Literal["generate_answer", "rewrite_query", "finish"]:
        if state.get("evidence_sufficient"):
            return "generate_answer"
        if state.get("blocked"):
            return "finish"
        return "rewrite_query"

    def after_rewrite(state: AgentState) -> Literal["retrieve", "finish"]:
        return "finish" if state.get("blocked") else "retrieve"

    graph = StateGraph(AgentState)
    graph.add_node("scope_guard", scope_guard)
    graph.add_node("route_intent", route_intent)
    graph.add_node("select_retriever", select_retriever)
    graph.add_node("retrieve", retrieve)
    graph.add_node("grade_evidence", grade_evidence)
    graph.add_node("rewrite_query", rewrite_query)
    graph.add_node("generate_answer", generate_answer)
    graph.add_node("verify_answer", verify_answer)
    graph.add_node("finish", finish)

    graph.add_edge(START, "scope_guard")
    graph.add_conditional_edges(
        "scope_guard",
        after_scope,
        {"route_intent": "route_intent", "finish": "finish"},
    )
    graph.add_edge("route_intent", "select_retriever")
    graph.add_edge("select_retriever", "retrieve")
    graph.add_edge("retrieve", "grade_evidence")
    graph.add_conditional_edges(
        "grade_evidence",
        after_grade,
        {
            "generate_answer": "generate_answer",
            "rewrite_query": "rewrite_query",
            "finish": "finish",
        },
    )
    graph.add_conditional_edges(
        "rewrite_query",
        after_rewrite,
        {"retrieve": "retrieve", "finish": "finish"},
    )
    graph.add_edge("generate_answer", "verify_answer")
    graph.add_edge("verify_answer", "finish")
    graph.add_edge("finish", END)
    return graph.compile()


def _result_from_state(state: AgentState) -> dict:
    blocked = bool(state.get("blocked"))
    return {
        "answer": state.get("answer") or "",
        "sources": [] if blocked else state.get("sources", []),
        "grounded": bool(state.get("grounded")),
        "blocked": blocked,
        "blocked_reason": state.get("blocked_reason"),
        "retrieval_attempts": state.get("retrieval_attempts", 0),
        "rewritten": bool(state.get("rewritten")),
        "rewritten_question": state.get("rewritten_question"),
        "intent": state.get("intent"),
        "intent_label": INTENT_LABELS.get(state.get("intent", ""), "범위 검사"),
        "selected_source_types": state.get("selected_source_types", []),
        "verification": state.get("verification", "not_run"),
        "trace": state.get("trace", []),
        "agentic": True,
    }


def answer_question(
    db: Session,
    current_user: User,
    question: str,
    *,
    find_rag_sources,
    no_evidence_message: str,
) -> dict:
    runtime = AgentRuntime(
        db=db,
        current_user=current_user,
        find_rag_sources=find_rag_sources,
        no_evidence_message=no_evidence_message,
    )
    graph = _build_agent_graph(runtime)
    final_state = graph.invoke(
        {
            "question": question,
            "query": question,
            "retrieval_attempts": 0,
            "rewritten": False,
            "rewritten_question": None,
            "blocked": False,
            "grounded": False,
            "trace": [],
        }
    )
    return _result_from_state(final_state)
