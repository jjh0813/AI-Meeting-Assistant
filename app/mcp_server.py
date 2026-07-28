from datetime import datetime, timezone
from urllib.parse import urlparse

import jwt
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import decode_access_token
from app.models.transcript import ActionItem, ActionItemStatus, Transcript
from app.models.user import Status, User
from app.services.google_calendar import list_upcoming_events, sync_user_tasks
from app.services.personalization import is_assigned_to_user, personalize_masked_text


def build_transport_security(*urls: str) -> TransportSecuritySettings:
    allowed_hosts = {"127.0.0.1:*", "localhost:*", "[::1]:*"}
    allowed_origins = {
        "http://127.0.0.1:*",
        "http://localhost:*",
        "http://[::1]:*",
    }
    for value in urls:
        parsed = urlparse(value)
        if not parsed.scheme or not parsed.hostname:
            continue
        host = parsed.hostname
        default_port = 443 if parsed.scheme == "https" else 80
        if parsed.port and parsed.port != default_port:
            host = f"{host}:{parsed.port}"
        allowed_hosts.add(host)
        allowed_origins.add(f"{parsed.scheme}://{host}")
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=sorted(allowed_hosts),
        allowed_origins=sorted(allowed_origins),
    )


class NotingJwtVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            payload = decode_access_token(token)
            username = payload.get("sub")
            if not username:
                return None
        except jwt.PyJWTError:
            return None
        db = SessionLocal()
        try:
            user = (
                db.query(User)
                .filter(User.username == username, User.status == Status.approved)
                .first()
            )
            if user is None:
                return None
            expires_at = payload.get("exp")
            if isinstance(expires_at, datetime):
                expires_at = int(expires_at.timestamp())
            elif expires_at is not None:
                expires_at = int(expires_at)
            return AccessToken(
                token=token,
                client_id="noting-web",
                scopes=["noting:read", "noting:calendar"],
                expires_at=expires_at,
                resource=settings.mcp_resource_server_url,
                subject=user.username,
            )
        finally:
            db.close()


mcp = FastMCP(
    "Noting Meeting Assistant",
    instructions=(
        "Noting 사용자가 소유한 회의록과 개인 업무만 조회합니다. "
        "Google Calendar를 변경하는 도구는 사용자의 명시적인 요청이 있을 때만 호출합니다."
    ),
    token_verifier=NotingJwtVerifier(),
    auth=AuthSettings(
        issuer_url=AnyHttpUrl(settings.mcp_issuer_url),
        resource_server_url=AnyHttpUrl(settings.mcp_resource_server_url),
        required_scopes=["noting:read"],
    ),
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
    transport_security=build_transport_security(
        settings.mcp_issuer_url,
        settings.mcp_resource_server_url,
    ),
)


def _current_user(db) -> User:
    access = get_access_token()
    if access is None or not access.subject:
        raise PermissionError("인증된 Noting 사용자가 필요합니다.")
    user = (
        db.query(User)
        .filter(User.username == access.subject, User.status == Status.approved)
        .first()
    )
    if user is None:
        raise PermissionError("승인된 Noting 사용자를 찾을 수 없습니다.")
    return user


@mcp.tool()
def search_meetings(query: str, limit: int = 5) -> dict:
    """현재 계정이 소유한 회의 본문·요약·업무에서 관련 근거를 검색합니다."""
    from app.api.routes.transcripts import find_rag_sources
    from app.services.embedding import embed

    db = SessionLocal()
    try:
        user = _current_user(db)
        safe_limit = max(1, min(limit, 20))
        results = find_rag_sources(
            db, user, query.strip(), embed(query.strip()), safe_limit
        )
        return {"query": query, "results": results}
    finally:
        db.close()


@mcp.tool()
def ask_meetings(question: str) -> dict:
    """현재 계정의 회의 근거만 사용하는 LangGraph Agentic RAG 답변을 반환합니다."""
    from app.api.routes.transcripts import NO_EVIDENCE_MESSAGE, find_rag_sources
    from app.services.agentic_rag import answer_question

    db = SessionLocal()
    try:
        user = _current_user(db)
        return answer_question(
            db,
            user,
            question.strip(),
            find_rag_sources=find_rag_sources,
            no_evidence_message=NO_EVIDENCE_MESSAGE,
        )
    finally:
        db.close()


@mcp.tool()
def list_my_tasks(include_completed: bool = False) -> dict:
    """현재 로그인 사용자의 이름으로 배정된 업무만 조회합니다."""
    from app.repositories import transcript as transcript_repo

    db = SessionLocal()
    try:
        user = _current_user(db)
        query = (
            db.query(ActionItem, Transcript)
            .join(Transcript, Transcript.id == ActionItem.transcript_id)
            .filter(
                Transcript.owner_user_id == user.id,
                Transcript.archived.is_(False),
                ActionItem.archived.is_(False),
            )
        )
        if not include_completed:
            query = query.filter(
                ActionItem.status.notin_(
                    [ActionItemStatus.completed, ActionItemStatus.superseded]
                )
            )
        tasks = []
        for item, transcript in query.order_by(ActionItem.created_at.desc()).all():
            pii = transcript_repo.get_pii_entries(db, user, transcript.id)
            if not is_assigned_to_user(item.assignee, pii, user.display_name):
                continue
            tasks.append(
                {
                    "id": item.id,
                    "meeting_id": transcript.id,
                    "meeting_title": personalize_masked_text(
                        transcript.title or f"회의록 #{transcript.id}",
                        pii,
                        user.display_name,
                    ),
                    "task": personalize_masked_text(
                        item.task, pii, user.display_name
                    ),
                    "assignee": user.display_name,
                    "due": personalize_masked_text(
                        item.due, pii, user.display_name
                    ),
                    "request": personalize_masked_text(
                        item.request, pii, user.display_name
                    ),
                    "status": item.status.value,
                }
            )
        return {"tasks": tasks, "count": len(tasks)}
    finally:
        db.close()


@mcp.tool()
def get_meeting(meeting_id: int) -> dict:
    """현재 계정이 소유한 특정 회의의 본문, 요약과 실행 항목을 조회합니다."""
    from app.api.routes.transcripts import stored_analysis

    db = SessionLocal()
    try:
        user = _current_user(db)
        transcript, analysis = stored_analysis(db, user, meeting_id)
        return {"id": transcript.id, **analysis}
    finally:
        db.close()


@mcp.tool()
def list_calendar_events(days: int = 7) -> dict:
    """Google Calendar에 동기화된 향후 Noting 일정을 조회합니다."""
    db = SessionLocal()
    try:
        user = _current_user(db)
        events = list_upcoming_events(db, user, max(1, min(days, 90)))
        return {"events": events, "count": len(events)}
    finally:
        db.close()


@mcp.tool()
def sync_calendar_tasks() -> dict:
    """현재 사용자의 Noting 업무를 Google Calendar에 쓰거나 갱신합니다."""
    db = SessionLocal()
    try:
        user = _current_user(db)
        result = sync_user_tasks(db, user)
        return {
            **result,
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        db.close()
