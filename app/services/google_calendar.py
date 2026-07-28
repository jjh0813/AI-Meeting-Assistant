import base64
import hashlib
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import quote, urlencode

import httpx
import jwt
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.calendar import GoogleCalendarConnection, GoogleCalendarEventLink
from app.models.transcript import ActionItem, ActionItemStatus, Transcript
from app.models.user import Status, User
from app.services.errors import ExternalServiceError
from app.services.personalization import is_assigned_to_user, personalize_masked_text

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_CALENDAR_API = "https://www.googleapis.com/calendar/v3"
GOOGLE_SCOPES = (
    "openid",
    "email",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.app.created",
)
KST = timezone(timedelta(hours=9), name="Asia/Seoul")
_DATE_PATTERNS = (
    re.compile(r"(?P<year>\d{4})[년./-]\s*(?P<month>\d{1,2})[월./-]\s*(?P<day>\d{1,2})일?"),
    re.compile(r"(?P<month>\d{1,2})월\s*(?P<day>\d{1,2})일"),
)
_KOREAN_TIME = re.compile(
    r"(?:(?P<period>오전|오후)\s*)?(?P<hour>\d{1,2})시(?:\s*(?P<minute>\d{1,2})분)?"
)
_CLOCK_TIME = re.compile(r"(?<!\d)(?P<hour>\d{1,2}):(?P<minute>\d{2})(?!\d)")


@dataclass(frozen=True)
class ParsedDue:
    start: datetime | date
    end: datetime | date
    all_day: bool


def calendar_is_configured() -> bool:
    return bool(
        settings.google_client_id
        and settings.google_client_secret
        and settings.google_calendar_redirect_uri
    )


def _fernet() -> Fernet:
    source = settings.token_encryption_key or settings.secret_key
    key = base64.urlsafe_b64encode(hashlib.sha256(source.encode("utf-8")).digest())
    return Fernet(key)


def _encrypt(value: str | None) -> str | None:
    if not value:
        return None
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def _decrypt(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise ExternalServiceError(
            "저장된 Google Calendar 인증 정보를 복호화하지 못했습니다. 다시 연결해 주세요.",
            status_code=401,
        ) from exc


def create_oauth_state(user: User) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user.id),
            "purpose": "google_calendar_oauth",
            "nonce": secrets.token_urlsafe(18),
            "iat": now,
            "exp": now + timedelta(minutes=10),
        },
        settings.secret_key,
        algorithm="HS256",
    )


def verify_oauth_state(state: str) -> int:
    try:
        payload = jwt.decode(state, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise ValueError("Google Calendar 연결 요청이 만료되었거나 올바르지 않습니다.") from exc
    if payload.get("purpose") != "google_calendar_oauth":
        raise ValueError("Google Calendar 연결 요청의 용도가 올바르지 않습니다.")
    try:
        return int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Google Calendar 연결 사용자를 확인할 수 없습니다.") from exc


def build_authorization_url(user: User) -> str:
    if not calendar_is_configured():
        raise ExternalServiceError(
            "Google Calendar OAuth 설정이 없습니다. 서버 환경변수를 확인해 주세요.",
            status_code=503,
        )
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_calendar_redirect_uri,
        "response_type": "code",
        "scope": " ".join(GOOGLE_SCOPES),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "select_account consent",
        "state": create_oauth_state(user),
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def _token_expiry(token_data: dict) -> datetime:
    seconds = max(int(token_data.get("expires_in") or 3600), 60)
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


def _same_google_account(
    connection: GoogleCalendarConnection,
    *,
    google_subject: str | None,
    google_email: str | None,
) -> bool:
    if connection.google_subject and google_subject:
        return secrets.compare_digest(connection.google_subject, google_subject)
    if connection.google_email and google_email:
        return connection.google_email.casefold() == google_email.casefold()
    return False


def _dedicated_calendar_body(user: User) -> dict:
    display_name = (user.display_name or user.username).strip()
    return {
        "summary": f"Noting - {display_name} ({user.username})",
        "description": (
            f"Noting 계정 {user.username} 전용 캘린더입니다. "
            "이 계정에 배정된 업무 일정만 자동으로 동기화됩니다."
        ),
        "timeZone": settings.google_calendar_timezone,
    }


def _create_dedicated_calendar(access_token: str, user: User) -> str:
    try:
        response = httpx.post(
            f"{GOOGLE_CALENDAR_API}/calendars",
            headers={"Authorization": f"Bearer {access_token}"},
            json=_dedicated_calendar_body(user),
            timeout=30,
        )
        response.raise_for_status()
        calendar_id = str(response.json().get("id") or "").strip()
    except (httpx.HTTPError, ValueError) as exc:
        raise ExternalServiceError(
            "Noting 계정 전용 Google 캘린더를 만들지 못했습니다. "
            "Google 권한을 확인한 후 다시 연결해 주세요.",
            status_code=502,
        ) from exc
    if not calendar_id:
        raise ExternalServiceError(
            "Google이 생성된 전용 캘린더 ID를 반환하지 않았습니다.",
            status_code=502,
        )
    return calendar_id


def exchange_code(db: Session, code: str, state: str) -> GoogleCalendarConnection:
    user_id = verify_oauth_state(state)
    user = db.query(User).filter(User.id == user_id, User.status == Status.approved).first()
    if user is None:
        raise ValueError("승인된 Noting 사용자를 찾을 수 없습니다.")
    try:
        response = httpx.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_calendar_redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=30,
        )
        response.raise_for_status()
        token_data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ExternalServiceError(
            "Google Calendar 인증 코드를 토큰으로 교환하지 못했습니다.",
            status_code=502,
        ) from exc

    access_token = str(token_data.get("access_token") or "")
    if not access_token:
        raise ExternalServiceError(
            "Google에서 Calendar 액세스 토큰을 반환하지 않았습니다.",
            status_code=502,
        )

    existing = (
        db.query(GoogleCalendarConnection)
        .filter(GoogleCalendarConnection.user_id == user.id)
        .first()
    )
    old_refresh = _decrypt(existing.encrypted_refresh_token) if existing else None
    google_subject = None
    email = None
    try:
        info = httpx.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
        if info.is_success:
            userinfo = info.json()
            google_subject = userinfo.get("sub")
            email = userinfo.get("email")
    except (httpx.HTTPError, ValueError):
        logger.info("Google userinfo lookup failed for user %s", user.id)

    same_google_account = bool(
        existing
        and _same_google_account(
            existing,
            google_subject=google_subject,
            google_email=email,
        )
    )
    refresh_token = str(token_data.get("refresh_token") or "")
    if not refresh_token and same_google_account:
        refresh_token = old_refresh or ""

    calendar_id = existing.calendar_id if existing and same_google_account else "primary"
    if not calendar_id or calendar_id == "primary":
        calendar_id = _create_dedicated_calendar(access_token, user)

    connection = existing or GoogleCalendarConnection(user_id=user.id)
    connection.google_subject = google_subject or (
        connection.google_subject if same_google_account else None
    )
    connection.google_email = email or connection.google_email
    connection.calendar_id = calendar_id
    connection.encrypted_access_token = _encrypt(access_token)
    connection.encrypted_refresh_token = _encrypt(refresh_token)
    connection.token_expires_at = _token_expiry(token_data)
    connection.scopes = str(token_data.get("scope") or " ".join(GOOGLE_SCOPES))
    db.add(connection)
    db.commit()
    db.refresh(connection)
    return connection


def get_connection_record(
    db: Session, user: User
) -> GoogleCalendarConnection | None:
    return (
        db.query(GoogleCalendarConnection)
        .filter(GoogleCalendarConnection.user_id == user.id)
        .first()
    )


def _connection_is_active(connection: GoogleCalendarConnection | None) -> bool:
    return bool(
        connection
        and (
            connection.encrypted_access_token
            or connection.encrypted_refresh_token
        )
    )


def get_connection(db: Session, user: User) -> GoogleCalendarConnection | None:
    connection = get_connection_record(db, user)
    return connection if _connection_is_active(connection) else None


def connection_status(db: Session, user: User) -> dict:
    connection = get_connection_record(db, user)
    connected = _connection_is_active(connection)
    requires_reconnect = bool(
        connected
        and connection
        and (not connection.calendar_id or connection.calendar_id == "primary")
    )
    return {
        "configured": calendar_is_configured(),
        "connected": connected,
        "isolated": bool(
            connection
            and connection.calendar_id
            and connection.calendar_id != "primary"
        ),
        "requires_reconnect": bool(requires_reconnect),
        "email": connection.google_email if connection else None,
        "calendar_id": connection.calendar_id if connection else None,
        "reminder_minutes": settings.google_calendar_reminder_minutes,
    }


def _refresh_access_token(
    db: Session, connection: GoogleCalendarConnection
) -> str:
    refresh_token = _decrypt(connection.encrypted_refresh_token)
    if not refresh_token:
        raise ExternalServiceError(
            "Google Calendar 갱신 토큰이 없습니다. 연결을 해제한 뒤 다시 연결해 주세요.",
            status_code=401,
        )
    try:
        response = httpx.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        response.raise_for_status()
        token_data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ExternalServiceError(
            "Google Calendar 인증을 갱신하지 못했습니다. 다시 연결해 주세요.",
            status_code=401,
        ) from exc
    access_token = str(token_data.get("access_token") or "")
    if not access_token:
        raise ExternalServiceError(
            "Google Calendar 갱신 응답에 액세스 토큰이 없습니다.",
            status_code=502,
        )
    connection.encrypted_access_token = _encrypt(access_token)
    connection.token_expires_at = _token_expiry(token_data)
    db.commit()
    return access_token


def get_access_token(db: Session, connection: GoogleCalendarConnection) -> str:
    expiry = connection.token_expires_at
    if expiry is not None and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if expiry is None or expiry <= datetime.now(timezone.utc) + timedelta(minutes=2):
        return _refresh_access_token(db, connection)
    access_token = _decrypt(connection.encrypted_access_token)
    if not access_token:
        return _refresh_access_token(db, connection)
    return access_token


def parse_due_text(value: str, now: datetime | None = None) -> ParsedDue | None:
    text = " ".join((value or "").strip().split())
    if not text:
        return None
    reference = (now or datetime.now(KST)).astimezone(KST)
    target_date = None
    if "모레" in text:
        target_date = reference.date() + timedelta(days=2)
    elif "내일" in text:
        target_date = reference.date() + timedelta(days=1)
    elif "오늘" in text:
        target_date = reference.date()
    else:
        for pattern in _DATE_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            year_text = match.groupdict().get("year")
            year = int(year_text) if year_text else reference.year
            month = int(match.group("month"))
            day = int(match.group("day"))
            if not year_text and reference.month == 12 and month == 1:
                year += 1
            try:
                target_date = date(year, month, day)
            except ValueError:
                return None
            break
    if target_date is None:
        return None

    hour = minute = None
    match = _KOREAN_TIME.search(text)
    if match:
        hour = int(match.group("hour"))
        minute = int(match.group("minute") or 0)
        if match.group("period") == "오후" and hour < 12:
            hour += 12
        if match.group("period") == "오전" and hour == 12:
            hour = 0
    else:
        match = _CLOCK_TIME.search(text)
        if match:
            hour = int(match.group("hour"))
            minute = int(match.group("minute"))

    if hour is None:
        return ParsedDue(
            start=target_date,
            end=target_date + timedelta(days=1),
            all_day=True,
        )
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return None
    start = datetime.combine(target_date, time(hour, minute), tzinfo=KST)
    return ParsedDue(start=start, end=start + timedelta(hours=1), all_day=False)


def _event_body(
    *,
    title: str,
    description: str,
    parsed_due: ParsedDue,
    action_item_id: int | None = None,
    user_id: int | None = None,
) -> dict:
    if parsed_due.all_day:
        start = {"date": parsed_due.start.isoformat()}
        end = {"date": parsed_due.end.isoformat()}
    else:
        start = {
            "dateTime": parsed_due.start.isoformat(),
            "timeZone": settings.google_calendar_timezone,
        }
        end = {
            "dateTime": parsed_due.end.isoformat(),
            "timeZone": settings.google_calendar_timezone,
        }
    private_properties = {"source": "noting"}
    if action_item_id is not None:
        private_properties["notingActionItemId"] = str(action_item_id)
    if user_id is not None:
        private_properties["notingUserId"] = str(user_id)
    return {
        "summary": title,
        "description": description,
        "start": start,
        "end": end,
        "reminders": {
            "useDefault": False,
            "overrides": [
                {
                    "method": "popup",
                    "minutes": settings.google_calendar_reminder_minutes,
                },
                {
                    "method": "email",
                    "minutes": settings.google_calendar_reminder_minutes,
                },
            ],
        },
        "extendedProperties": {"private": private_properties},
    }


def _calendar_request(
    db: Session,
    connection: GoogleCalendarConnection,
    method: str,
    path: str,
    *,
    json_body: dict | None = None,
    params: dict | None = None,
):
    token = get_access_token(db, connection)
    try:
        response = httpx.request(
            method,
            f"{GOOGLE_CALENDAR_API}{path}",
            headers={"Authorization": f"Bearer {token}"},
            json=json_body,
            params=params,
            timeout=30,
        )
        if response.status_code == 401:
            token = _refresh_access_token(db, connection)
            response = httpx.request(
                method,
                f"{GOOGLE_CALENDAR_API}{path}",
                headers={"Authorization": f"Bearer {token}"},
                json=json_body,
                params=params,
                timeout=30,
            )
        response.raise_for_status()
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ExternalServiceError(
            "Google Calendar API 요청에 실패했습니다.",
            status_code=502,
        ) from exc


def _personal_sync_tasks(db: Session, user: User):
    rows = (
        db.query(ActionItem, Transcript)
        .join(Transcript, Transcript.id == ActionItem.transcript_id)
        .filter(
            Transcript.owner_user_id == user.id,
            Transcript.archived.is_(False),
            ActionItem.archived.is_(False),
            ActionItem.status.notin_(
                [ActionItemStatus.completed, ActionItemStatus.superseded]
            ),
        )
        .all()
    )
    results = []
    today = datetime.now(KST).date()
    for item, transcript in rows:
        from app.repositories import transcript as transcript_repo

        pii_entries = transcript_repo.get_pii_entries(db, user, transcript.id)
        if not is_assigned_to_user(item.assignee, pii_entries, user.display_name):
            continue
        due = personalize_masked_text(item.due, pii_entries, user.display_name)
        parsed = parse_due_text(due)
        if parsed is None:
            continue
        event_date = (
            parsed.start.date()
            if isinstance(parsed.start, datetime)
            else parsed.start
        )
        if event_date < today:
            continue
        results.append((item, transcript, pii_entries, due, parsed))
    return results


def sync_user_tasks(db: Session, user: User) -> dict:
    connection = get_connection(db, user)
    if connection is None:
        raise ExternalServiceError(
            "Google Calendar가 연결되어 있지 않습니다.",
            status_code=409,
        )
    selected_calendar = (connection.calendar_id or "").strip()
    if not selected_calendar or selected_calendar == "primary":
        raise ExternalServiceError(
            "계정별 전용 Google 캘린더 설정이 필요합니다. "
            "Google Calendar를 다시 연결해 주세요.",
            status_code=409,
        )
    links = {
        link.action_item_id: link
        for link in db.query(GoogleCalendarEventLink)
        .filter(GoogleCalendarEventLink.user_id == user.id)
        .all()
    }
    active_ids = set()
    created = updated = deleted = 0
    for item, transcript, pii_entries, due, parsed in _personal_sync_tasks(db, user):
        active_ids.add(item.id)
        title = personalize_masked_text(
            item.task or "Noting 업무", pii_entries, user.display_name
        )
        meeting_title = personalize_masked_text(
            transcript.title or f"회의록 #{transcript.id}",
            pii_entries,
            user.display_name,
        )
        request = personalize_masked_text(
            item.request or "", pii_entries, user.display_name
        )
        description = (
            f"{request}\n\n출처: {meeting_title}\nNoting에서 자동 동기화된 일정입니다."
        ).strip()
        body = _event_body(
            title=title,
            description=description,
            parsed_due=parsed,
            action_item_id=item.id,
            user_id=user.id,
        )
        link = links.get(item.id)
        if link is None:
            data = _calendar_request(
                db,
                connection,
                "POST",
                f"/calendars/{quote(selected_calendar, safe='')}/events",
                json_body=body,
            )
            link = GoogleCalendarEventLink(
                user_id=user.id,
                action_item_id=item.id,
                calendar_id=selected_calendar,
                google_event_id=data["id"],
                due_snapshot=due,
                title_snapshot=title,
            )
            db.add(link)
            created += 1
        elif link.calendar_id != selected_calendar:
            try:
                _calendar_request(
                    db,
                    connection,
                    "DELETE",
                    f"/calendars/{quote(link.calendar_id, safe='')}/events/"
                    f"{quote(link.google_event_id, safe='')}",
                )
            except ExternalServiceError:
                logger.warning(
                    "Failed to delete Google event %s while moving calendars",
                    link.google_event_id,
                )
            data = _calendar_request(
                db,
                connection,
                "POST",
                f"/calendars/{quote(selected_calendar, safe='')}/events",
                json_body=body,
            )
            link.google_event_id = data["id"]
            link.calendar_id = selected_calendar
            link.due_snapshot = due
            link.title_snapshot = title
            link.synced_at = datetime.now(timezone.utc)
            updated += 1
        elif link.due_snapshot != due or link.title_snapshot != title:
            _calendar_request(
                db,
                connection,
                "PUT",
                f"/calendars/{quote(link.calendar_id, safe='')}/events/"
                f"{quote(link.google_event_id, safe='')}",
                json_body=body,
            )
            link.calendar_id = selected_calendar
            link.due_snapshot = due
            link.title_snapshot = title
            link.synced_at = datetime.now(timezone.utc)
            updated += 1

    for action_item_id, link in links.items():
        if action_item_id in active_ids:
            continue
        try:
            _calendar_request(
                db,
                connection,
                "DELETE",
                f"/calendars/{quote(link.calendar_id, safe='')}/events/"
                f"{quote(link.google_event_id, safe='')}",
            )
        except ExternalServiceError:
            logger.warning("Failed to delete stale Google event %s", link.google_event_id)
        db.delete(link)
        deleted += 1
    db.commit()
    return {
        "created": created,
        "updated": updated,
        "deleted": deleted,
        "calendar_id": selected_calendar,
        "reminder_minutes": settings.google_calendar_reminder_minutes,
    }


def create_manual_event(
    db: Session,
    user: User,
    *,
    title: str,
    start: str,
    end: str | None,
    description: str,
    all_day: bool,
) -> dict:
    connection = get_connection(db, user)
    if connection is None:
        raise ExternalServiceError(
            "Google Calendar가 연결되어 있지 않습니다.",
            status_code=409,
        )
    try:
        if all_day:
            start_date = date.fromisoformat(start)
            end_date = date.fromisoformat(end) if end else start_date + timedelta(days=1)
            parsed = ParsedDue(start_date, end_date, True)
        else:
            start_dt = datetime.fromisoformat(start)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=KST)
            end_dt = datetime.fromisoformat(end) if end else start_dt + timedelta(hours=1)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=KST)
            parsed = ParsedDue(start_dt, end_dt, False)
    except ValueError as exc:
        raise ValueError("일정 시작 또는 종료 날짜 형식이 올바르지 않습니다.") from exc
    body = _event_body(
        title=title,
        description=description,
        parsed_due=parsed,
        user_id=user.id,
    )
    return _calendar_request(
        db,
        connection,
        "POST",
        f"/calendars/{quote(connection.calendar_id, safe='')}/events",
        json_body=body,
    )


def list_upcoming_events(db: Session, user: User, days: int = 7) -> list[dict]:
    connection = get_connection(db, user)
    if connection is None:
        raise ExternalServiceError(
            "Google Calendar가 연결되어 있지 않습니다.",
            status_code=409,
        )
    now = datetime.now(timezone.utc)
    data = _calendar_request(
        db,
        connection,
        "GET",
        f"/calendars/{quote(connection.calendar_id, safe='')}/events",
        params={
            "timeMin": now.isoformat(),
            "timeMax": (now + timedelta(days=max(1, min(days, 90)))).isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
            "privateExtendedProperty": f"notingUserId={user.id}",
            "maxResults": 50,
        },
    )
    return [
        {
            "id": item.get("id"),
            "title": item.get("summary"),
            "description": item.get("description"),
            "start": item.get("start"),
            "end": item.get("end"),
            "html_link": item.get("htmlLink"),
        }
        for item in data.get("items", [])
    ]


def disconnect_calendar(db: Session, user: User) -> bool:
    connection = get_connection_record(db, user)
    if not _connection_is_active(connection):
        return False

    identity_filters = []
    if connection.google_subject:
        identity_filters.append(
            GoogleCalendarConnection.google_subject == connection.google_subject
        )
    if connection.google_email:
        identity_filters.append(
            func.lower(GoogleCalendarConnection.google_email)
            == connection.google_email.casefold()
        )
    shared_google_account = False
    if identity_filters:
        shared_google_account = (
            db.query(GoogleCalendarConnection)
            .filter(
                GoogleCalendarConnection.id != connection.id,
                or_(*identity_filters),
                or_(
                    GoogleCalendarConnection.encrypted_access_token.isnot(None),
                    GoogleCalendarConnection.encrypted_refresh_token.isnot(None),
                ),
            )
            .first()
            is not None
        )

    token = None
    if not shared_google_account:
        token = _decrypt(connection.encrypted_refresh_token) or _decrypt(
            connection.encrypted_access_token
        )
    if token:
        try:
            httpx.post(
                GOOGLE_REVOKE_URL,
                params={"token": token},
                headers={"content-type": "application/x-www-form-urlencoded"},
                timeout=15,
            )
        except httpx.HTTPError:
            logger.info("Google token revocation failed for user %s", user.id)
    connection.encrypted_access_token = None
    connection.encrypted_refresh_token = None
    connection.token_expires_at = None
    db.add(connection)
    db.commit()
    return True
