from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_approved_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.calendar import CalendarEventCreate
from app.services.errors import ExternalServiceError
from app.services.google_calendar import (
    build_authorization_url,
    connection_status,
    create_manual_event,
    disconnect_calendar,
    exchange_code,
    list_upcoming_events,
    sync_user_tasks,
)

router = APIRouter(prefix="/calendar/google", tags=["google-calendar"])


@router.get("/status")
def google_calendar_status(
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    return connection_status(db, current_user)


@router.get("/connect")
def connect_google_calendar(current_user: User = Depends(get_approved_user)):
    return {"authorization_url": build_authorization_url(current_user)}


@router.get("/callback")
def google_calendar_callback(
    code: str = Query(min_length=1),
    state: str = Query(min_length=1),
    db: Session = Depends(get_db),
):
    try:
        exchange_code(db, code, state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ExternalServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return RedirectResponse(url="/ui/#/main", status_code=302)


@router.post("/sync")
def sync_google_calendar(
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    return sync_user_tasks(db, current_user)


@router.get("/events")
def upcoming_google_events(
    days: int = Query(default=7, ge=1, le=90),
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    return {"events": list_upcoming_events(db, current_user, days)}


@router.post("/events")
def add_google_event(
    body: CalendarEventCreate,
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    try:
        event = create_manual_event(
            db,
            current_user,
            title=body.title.strip(),
            start=body.start,
            end=body.end,
            description=body.description,
            all_day=body.all_day,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "id": event.get("id"),
        "title": event.get("summary"),
        "html_link": event.get("htmlLink"),
    }


@router.delete("/disconnect")
def disconnect_google_calendar(
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    return {"disconnected": disconnect_calendar(db, current_user)}
