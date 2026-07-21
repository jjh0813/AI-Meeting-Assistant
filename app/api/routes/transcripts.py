from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_approved_user, get_current_admin
from app.core.database import get_db
from app.models.user import User
from app.repositories import transcript as transcript_repo
from app.schemas.transcript import TranscriptCreate
from app.services.analyzer import analyze, summarize
from app.services.masking import mask_text
from app.services.report import build_pdf_report, build_text_report
from app.services.stt import transcribe

router = APIRouter(prefix="/transcripts", tags=["transcripts"])


@router.post("")
def create_transcript(
    body: TranscriptCreate,
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    masked_content, pii_items = mask_text(body.content)
    transcript = transcript_repo.create_transcript(
        db, current_user, masked_content, pii_items
    )
    return {
        "id": transcript.id,
        "department": transcript.department.value,
        "masked_content": transcript.masked_content,
    }


@router.get("")
def list_transcripts(
    current_user: User = Depends(get_approved_user), db: Session = Depends(get_db)
):
    transcripts = transcript_repo.list_transcripts(db, current_user)
    return [
        {
            "id": t.id,
            "department": t.department.value,
            "masked_content": t.masked_content,
        }
        for t in transcripts
    ]


@router.get("/{transcript_id}/pii")
def read_pii(
    transcript_id: int,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    entries = transcript_repo.get_pii_entries(db, current_user, transcript_id)
    return [
        {"pii_type": e.pii_type, "original_value": e.original_value} for e in entries
    ]


@router.get("/{transcript_id}/summary")
def summarize_transcript(
    transcript_id: int,
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    transcript = transcript_repo.get_transcript(db, current_user, transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="회의록을 찾을 수 없습니다.")
    summary = summarize(transcript.masked_content)
    return {"id": transcript.id, "summary": summary}


@router.get("/{transcript_id}/analysis")
def analyze_transcript(
    transcript_id: int,
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    transcript = transcript_repo.get_transcript(db, current_user, transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="회의록을 찾을 수 없습니다.")
    result = analyze(transcript.masked_content)
    return {
        "id": transcript.id,
        "summary": result["summary"],
        "tasks": result["tasks"],
    }


@router.get("/{transcript_id}/report")
def get_text_report(
    transcript_id: int,
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    transcript = transcript_repo.get_transcript(db, current_user, transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="회의록을 찾을 수 없습니다.")
    analysis = analyze(transcript.masked_content)
    return {"id": transcript.id, "report": build_text_report(analysis)}


@router.get("/{transcript_id}/report.pdf")
def get_pdf_report(
    transcript_id: int,
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    transcript = transcript_repo.get_transcript(db, current_user, transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="회의록을 찾을 수 없습니다.")
    analysis = analyze(transcript.masked_content)
    content = build_pdf_report(analysis)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=report_{transcript.id}.pdf"
        },
    )


@router.put("/{transcript_id}")
def update_transcript(
    transcript_id: int,
    body: TranscriptCreate,
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    masked_content, pii_items = mask_text(body.content)
    transcript = transcript_repo.update_transcript(
        db, current_user, transcript_id, masked_content, pii_items
    )
    if transcript is None:
        raise HTTPException(status_code=404, detail="회의록을 찾을 수 없습니다.")
    return {
        "id": transcript.id,
        "department": transcript.department.value,
        "masked_content": transcript.masked_content,
    }


@router.post("/upload")
def upload_and_transcribe(
    file: UploadFile = File(...),
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    audio_bytes = file.file.read()
    text = transcribe(audio_bytes, file.filename or "audio")
    masked_content, pii_items = mask_text(text)
    transcript = transcript_repo.create_transcript(
        db, current_user, masked_content, pii_items
    )
    return {
        "id": transcript.id,
        "department": transcript.department.value,
        "masked_content": transcript.masked_content,
    }

