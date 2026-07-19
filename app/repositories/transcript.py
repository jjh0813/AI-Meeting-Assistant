from sqlalchemy.orm import Session

from app.models.transcript import PiiEntry, Transcript
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
