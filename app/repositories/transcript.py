from sqlalchemy.orm import Session

from app.models.transcript import (
    ActionItem,
    ActionItemStatus,
    PiiEntry,
    Transcript,
    TranscriptChunk,
)
from app.models.user import User


def create_transcript(
    db: Session, current_user: User, masked_content: str, pii_items: list[dict]
) -> Transcript:
    transcript = Transcript(
        department=current_user.department, masked_content=masked_content
    )
    db.add(transcript)
    db.flush()
    for item in pii_items:
        db.add(
            PiiEntry(
                transcript_id=transcript.id,
                department=current_user.department,
                pii_type=item["pii_type"],
                original_value=item["original_value"],
            )
        )
    db.commit()
    db.refresh(transcript)
    return transcript


def list_transcripts(db: Session, current_user: User) -> list[Transcript]:
    return (
        db.query(Transcript)
        .filter(Transcript.department == current_user.department)
        .all()
    )


def get_pii_entries(
    db: Session, current_user: User, transcript_id: int
) -> list[PiiEntry]:
    return (
        db.query(PiiEntry)
        .filter(
            PiiEntry.transcript_id == transcript_id,
            PiiEntry.department == current_user.department,
        )
        .all()
    )


def get_transcript(db: Session, current_user: User, transcript_id: int):
    return (
        db.query(Transcript)
        .filter(
            Transcript.id == transcript_id,
            Transcript.department == current_user.department,
        )
        .first()
    )


def update_transcript(
    db: Session,
    current_user: User,
    transcript_id: int,
    masked_content: str,
    pii_items: list[dict],
):
    transcript = get_transcript(db, current_user, transcript_id)
    if transcript is None:
        return None

    transcript.masked_content = masked_content
    # The previous analysis describes the old text, so it must never remain
    # searchable or be shown as current after the user edits a meeting.
    transcript.summary = None
    transcript.summary_embedding = None
    transcript.analysis_status = "pending"
    transcript.analysis_error = None
    if not transcript.title_is_manual:
        transcript.title = None
    db.query(PiiEntry).filter(
        PiiEntry.transcript_id == transcript_id,
        PiiEntry.department == current_user.department,
    ).delete()
    for item in pii_items:
        db.add(
            PiiEntry(
                transcript_id=transcript.id,
                department=current_user.department,
                pii_type=item["pii_type"],
                original_value=item["original_value"],
            )
        )
    db.query(ActionItem).filter(ActionItem.transcript_id == transcript_id).delete()
    db.query(TranscriptChunk).filter(
        TranscriptChunk.transcript_id == transcript_id,
        TranscriptChunk.department == current_user.department,
    ).delete()
    db.commit()
    db.refresh(transcript)
    return transcript


def save_analysis(
    db: Session,
    transcript: Transcript,
    title: str,
    summary: str,
    tasks: list[dict],
    embedding,
    chunks: list[dict],
):
    if not transcript.title_is_manual:
        transcript.title = title.strip() or None
    transcript.summary = summary
    transcript.summary_embedding = embedding
    transcript.analysis_status = "completed"
    transcript.analysis_error = None
    existing_items: dict[tuple[str, str], list[ActionItem]] = {}
    for item in (
        db.query(ActionItem)
        .filter(ActionItem.transcript_id == transcript.id)
        .all()
    ):
        key = (item.task.strip(), item.assignee.strip())
        existing_items.setdefault(key, []).append(item)

    for t in tasks:
        key = (
            (t.get("task", "") or "").strip(),
            (t.get("assignee", "") or "").strip(),
        )
        matching_items = existing_items.get(key, [])
        if matching_items:
            action_item = matching_items.pop(0)
            action_item.task = t.get("task", "") or ""
            action_item.assignee = t.get("assignee", "") or ""
            action_item.due = t.get("due", "") or ""
            action_item.request = t.get("request", "") or ""
            action_item.task_embedding = t.get("task_embedding")
        else:
            db.add(
                ActionItem(
                    transcript_id=transcript.id,
                    department=transcript.department,
                    task=t.get("task", "") or "",
                    assignee=t.get("assignee", "") or "",
                    due=t.get("due", "") or "",
                    request=t.get("request", "") or "",
                    status=ActionItemStatus.pending,
                    task_embedding=t.get("task_embedding"),
                )
            )

    for remaining_items in existing_items.values():
        for item in remaining_items:
            db.delete(item)
    db.query(TranscriptChunk).filter(
        TranscriptChunk.transcript_id == transcript.id
    ).delete()
    for chunk in chunks:
        db.add(
            TranscriptChunk(
                transcript_id=transcript.id,
                department=transcript.department,
                chunk_index=chunk["chunk_index"],
                content=chunk["content"],
                embedding=chunk["embedding"],
            )
        )
    db.commit()
    db.refresh(transcript)
    return transcript


def update_analysis_status(
    db: Session,
    transcript: Transcript,
    status: str,
    error: str | None = None,
) -> Transcript:
    transcript.analysis_status = status
    transcript.analysis_error = error
    db.commit()
    db.refresh(transcript)
    return transcript


def update_transcript_title(
    db: Session,
    transcript: Transcript,
    title: str,
) -> Transcript:
    transcript.title = title.strip()
    transcript.title_is_manual = True
    db.commit()
    db.refresh(transcript)
    return transcript


def get_action_items(
    db: Session, current_user: User, transcript_id: int
) -> list[ActionItem]:
    return (
        db.query(ActionItem)
        .filter(
            ActionItem.transcript_id == transcript_id,
            ActionItem.department == current_user.department,
        )
        .all()
    )


def get_action_item(
    db: Session,
    current_user: User,
    transcript_id: int,
    action_item_id: int,
):
    return (
        db.query(ActionItem)
        .filter(
            ActionItem.id == action_item_id,
            ActionItem.transcript_id == transcript_id,
            ActionItem.department == current_user.department,
        )
        .first()
    )


def get_action_item_by_id(
    db: Session,
    current_user: User,
    action_item_id: int,
):
    return (
        db.query(ActionItem)
        .filter(
            ActionItem.id == action_item_id,
            ActionItem.department == current_user.department,
        )
        .first()
    )


def update_action_item_status(
    db: Session,
    action_item: ActionItem,
    status: ActionItemStatus,
) -> ActionItem:
    action_item.status = status
    if status != ActionItemStatus.superseded:
        action_item.superseded_by_id = None
    db.commit()
    db.refresh(action_item)
    return action_item


def search_similar_action_items(
    db: Session,
    current_user: User,
    task_embedding: list[float],
    exclude_transcript_id: int,
    limit: int = 3,
):
    distance = ActionItem.task_embedding.cosine_distance(task_embedding).label(
        "distance"
    )
    return (
        db.query(ActionItem, distance)
        .filter(
            ActionItem.department == current_user.department,
            ActionItem.transcript_id != exclude_transcript_id,
            ActionItem.status.notin_(
                [ActionItemStatus.completed, ActionItemStatus.superseded]
            ),
            ActionItem.task_embedding.is_not(None),
        )
        .order_by(distance)
        .limit(limit)
        .all()
    )


def get_action_item_similarity(
    db: Session,
    current_user: User,
    query_embedding: list[float],
    candidate_id: int,
):
    distance = ActionItem.task_embedding.cosine_distance(query_embedding).label(
        "distance"
    )
    row = (
        db.query(distance)
        .filter(
            ActionItem.id == candidate_id,
            ActionItem.department == current_user.department,
            ActionItem.task_embedding.is_not(None),
        )
        .first()
    )
    return None if row is None else float(row[0])


def confirm_schedule_change(
    db: Session,
    previous_item: ActionItem,
    current_item: ActionItem,
) -> ActionItem:
    previous_item.status = ActionItemStatus.superseded
    previous_item.superseded_by_id = current_item.id
    db.commit()
    db.refresh(previous_item)
    return previous_item


def search_similar_summaries(
    db: Session, current_user: User, query_embedding: list[float], limit: int
):
    """Return the closest analyzed meeting summaries within the user's department."""
    distance = Transcript.summary_embedding.cosine_distance(query_embedding).label(
        "distance"
    )
    return (
        db.query(Transcript, distance)
        .filter(
            Transcript.department == current_user.department,
            Transcript.summary.is_not(None),
            Transcript.summary_embedding.is_not(None),
        )
        .order_by(distance)
        .limit(limit)
        .all()
    )


def search_similar_chunks(
    db: Session, current_user: User, query_embedding: list[float], limit: int
):
    """Return the closest masked meeting chunks within the user's department."""
    distance = TranscriptChunk.embedding.cosine_distance(query_embedding).label(
        "distance"
    )
    return (
        db.query(TranscriptChunk, Transcript, distance)
        .join(Transcript, Transcript.id == TranscriptChunk.transcript_id)
        .filter(
            TranscriptChunk.department == current_user.department,
            Transcript.department == current_user.department,
            TranscriptChunk.embedding.is_not(None),
        )
        .order_by(distance)
        .limit(limit)
        .all()
    )
