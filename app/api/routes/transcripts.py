from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_approved_user, get_current_admin
from app.core.database import get_db
from app.models.user import User
from app.repositories import transcript as transcript_repo
from app.schemas.transcript import (
    TranscriptCreate,
    TranscriptQuestionRequest,
    TranscriptSearchRequest,
)
from app.services.analyzer import analyze, summarize
from app.services.embedding import embed
from app.services.masking import mask_text
from app.services.qa import answer_from_meetings
from app.services.report import build_pdf_report, build_text_report
from app.services.stt import transcribe

router = APIRouter(prefix="/transcripts", tags=["transcripts"])

MIN_RAG_SIMILARITY = 0.55
MEETING_ONLY_MESSAGE = "Noting은 내 부서 회의록과 업무 관련 질문만 답할 수 있습니다."


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
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in transcripts
    ]


@router.post("/search")
def search_transcripts(
    body: TranscriptSearchRequest,
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    query = body.query.strip()
    if not query:
        raise HTTPException(status_code=422, detail="검색어를 입력해 주세요.")

    query_embedding = embed(query)
    if query_embedding is None:
        raise HTTPException(
            status_code=503,
            detail="검색용 임베딩을 생성하지 못했습니다. Ollama 임베딩 모델 상태를 확인해 주세요.",
        )

    matches = transcript_repo.search_similar_summaries(
        db, current_user, query_embedding, body.limit
    )
    return {
        "query": query,
        "results": [
            {
                "id": transcript.id,
                "summary": transcript.summary,
                "masked_content": transcript.masked_content,
                "similarity": round(1 - float(distance), 4),
                "created_at": transcript.created_at.isoformat()
                if transcript.created_at
                else None,
            }
            for transcript, distance in matches
        ],
    }


@router.post("/ask")
def ask_about_meetings(
    body: TranscriptQuestionRequest,
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="질문을 입력해 주세요.")

    query_embedding = embed(question)
    if query_embedding is None:
        raise HTTPException(
            status_code=503,
            detail="검색용 임베딩을 생성하지 못했습니다. Ollama 임베딩 모델 상태를 확인해 주세요.",
        )

    matches = transcript_repo.search_similar_summaries(
        db, current_user, query_embedding, limit=3
    )
    sources = [
        {
            "id": transcript.id,
            "summary": transcript.summary,
            "similarity": round(1 - float(distance), 4),
            "created_at": transcript.created_at.isoformat()
            if transcript.created_at
            else None,
        }
        for transcript, distance in matches
        if 1 - float(distance) >= MIN_RAG_SIMILARITY
    ]
    if not sources:
        return {
            "answer": MEETING_ONLY_MESSAGE,
            "sources": [],
            "grounded": False,
        }

    return {
        "answer": answer_from_meetings(question, sources),
        "sources": sources,
        "grounded": True,
    }


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
    embedding = embed(result["summary"]) if result["summary"] else None
    transcript_repo.save_analysis(
        db, transcript, result["summary"], result["tasks"], embedding
    )
    return {
        "id": transcript.id,
        "summary": result["summary"],
        "tasks": result["tasks"],
    }


@router.get("/{transcript_id}/tasks")
def get_transcript_tasks(
    transcript_id: int,
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    transcript = transcript_repo.get_transcript(db, current_user, transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="회의록을 찾을 수 없습니다.")
    items = transcript_repo.get_action_items(db, current_user, transcript_id)
    return {
        "id": transcript.id,
        "summary": transcript.summary,
        "tasks": [
            {"task": i.task, "assignee": i.assignee, "due": i.due, "request": i.request}
            for i in items
        ],
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
        "analysis_required": True,
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
