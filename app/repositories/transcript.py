from sqlalchemy.orm import Session

from app.models.transcript import ActionItem, PiiEntry, Transcript
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
    db.commit()
    db.refresh(transcript)
    return transcript


def save_analysis(
    db: Session, transcript: Transcript, summary: str, tasks: list[dict], embedding
):
    transcript.summary = summary
    if embedding is not None:
        transcript.summary_embedding = embedding
    db.query(ActionItem).filter(
        ActionItem.transcript_id == transcript.id
    ).delete()
    for t in tasks:
        db.add(
            ActionItem(
                transcript_id=transcript.id,
                department=transcript.department,
                task=t.get("task", "") or "",
                assignee=t.get("assignee", "") or "",
                due=t.get("due", "") or "",
                request=t.get("request", "") or "",
            )
        )
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
