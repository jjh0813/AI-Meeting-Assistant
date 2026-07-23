from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_approved_user, get_current_admin
from app.core.database import get_db
from app.models.transcript import ActionItemStatus
from app.models.user import User
from app.repositories import transcript as transcript_repo
from app.schemas.transcript import (
    ActionItemStatusUpdate,
    TranscriptCreate,
    TranscriptQuestionRequest,
    TranscriptSearchRequest,
)
from app.services.analyzer import analyze, summarize
from app.services.chunking import split_text
from app.services.embedding import embed
from app.services.masking import mask_text
from app.services.qa import answer_from_meetings
from app.services.question_guard import guard_meeting_question
from app.services.report import build_pdf_report, build_text_report
from app.services.stt import transcribe

router = APIRouter(prefix="/transcripts", tags=["transcripts"])

MIN_RAG_SIMILARITY = 0.60
MIN_TASK_DUPLICATE_SIMILARITY = 0.75
MEETING_ONLY_MESSAGE = "Noting은 내 부서 회의록과 업무 관련 질문만 답할 수 있습니다."


def find_rag_sources(
    db: Session, current_user: User, query_embedding: list[float], limit: int
) -> list[dict]:
    chunk_matches = transcript_repo.search_similar_chunks(
        db, current_user, query_embedding, limit
    )
    chunk_sources = [
        {
            "id": transcript.id,
            "chunk_id": chunk.id,
            "chunk_index": chunk.chunk_index,
            "content": chunk.content,
            "summary": transcript.summary,
            "source_type": "chunk",
            "similarity": round(1 - float(distance), 4),
            "created_at": transcript.created_at.isoformat()
            if transcript.created_at
            else None,
        }
        for chunk, transcript, distance in chunk_matches
    ]
    summary_matches = transcript_repo.search_similar_summaries(
        db, current_user, query_embedding, limit
    )
    chunk_transcript_ids = {source["id"] for source in chunk_sources}
    summary_sources = [
        {
            "id": transcript.id,
            "chunk_id": None,
            "chunk_index": None,
            "content": transcript.summary,
            "summary": transcript.summary,
            "source_type": "summary",
            "similarity": round(1 - float(distance), 4),
            "created_at": transcript.created_at.isoformat()
            if transcript.created_at
            else None,
        }
        for transcript, distance in summary_matches
        if transcript.id not in chunk_transcript_ids
    ]
    return sorted(
        chunk_sources + summary_sources,
        key=lambda source: source["similarity"],
        reverse=True,
    )[:limit]


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

    results = find_rag_sources(db, current_user, query_embedding, body.limit)
    return {
        "query": query,
        "results": results,
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

    guard_result = guard_meeting_question(question)
    if guard_result is not None:
        message, reason = guard_result
        return {
            "answer": message,
            "sources": [],
            "grounded": False,
            "blocked": True,
            "blocked_reason": reason,
        }

    query_embedding = embed(question)
    if query_embedding is None:
        raise HTTPException(
            status_code=503,
            detail="검색용 임베딩을 생성하지 못했습니다. Ollama 임베딩 모델 상태를 확인해 주세요.",
        )

    sources = [
        source
        for source in find_rag_sources(db, current_user, query_embedding, limit=3)
        if source["similarity"] >= MIN_RAG_SIMILARITY
    ]
    if not sources:
        return {
            "answer": MEETING_ONLY_MESSAGE,
            "sources": [],
            "grounded": False,
            "blocked": True,
            "blocked_reason": "low_similarity",
        }

    return {
        "answer": answer_from_meetings(question, sources),
        "sources": sources,
        "grounded": True,
        "blocked": False,
        "blocked_reason": None,
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
    indexed_chunks = []
    for chunk_index, content in enumerate(split_text(transcript.masked_content)):
        chunk_embedding = embed(content)
        if chunk_embedding is not None:
            indexed_chunks.append(
                {
                    "chunk_index": chunk_index,
                    "content": content,
                    "embedding": chunk_embedding,
                }
            )
    indexed_tasks = []
    for task in result["tasks"]:
        task_text = " ".join(
            value
            for value in (
                task.get("task", ""),
                task.get("request", ""),
                task.get("assignee", ""),
                task.get("due", ""),
            )
            if value
        )
        indexed_tasks.append(
            {
                **task,
                "task_embedding": embed(task_text) if task_text else None,
            }
        )
    transcript_repo.save_analysis(
        db,
        transcript,
        result["summary"],
        indexed_tasks,
        embedding,
        indexed_chunks,
    )
    return {
        "id": transcript.id,
        "summary": result["summary"],
        "tasks": result["tasks"],
        "indexed_chunks": len(indexed_chunks),
        "indexed_tasks": sum(
            1 for task in indexed_tasks if task["task_embedding"] is not None
        ),
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
            {
                "id": i.id,
                "task": i.task,
                "assignee": i.assignee,
                "due": i.due,
                "request": i.request,
                "status": i.status.value,
            }
            for i in items
        ],
    }


@router.patch("/{transcript_id}/tasks/{task_id}")
def update_task_status(
    transcript_id: int,
    task_id: int,
    body: ActionItemStatusUpdate,
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    action_item = transcript_repo.get_action_item(
        db, current_user, transcript_id, task_id
    )
    if action_item is None:
        raise HTTPException(status_code=404, detail="업무를 찾을 수 없습니다.")
    updated = transcript_repo.update_action_item_status(
        db, action_item, ActionItemStatus(body.status)
    )
    return {
        "id": updated.id,
        "transcript_id": updated.transcript_id,
        "status": updated.status.value,
    }


@router.get("/{transcript_id}/task-duplicates")
def find_task_duplicates(
    transcript_id: int,
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    transcript = transcript_repo.get_transcript(db, current_user, transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="회의록을 찾을 수 없습니다.")

    items = transcript_repo.get_action_items(db, current_user, transcript_id)
    results = []
    for item in items:
        if (
            item.status == ActionItemStatus.completed
            or item.task_embedding is None
        ):
            continue
        matches = transcript_repo.search_similar_action_items(
            db,
            current_user,
            item.task_embedding,
            exclude_transcript_id=transcript_id,
        )
        duplicates = [
            {
                "id": candidate.id,
                "transcript_id": candidate.transcript_id,
                "task": candidate.task,
                "assignee": candidate.assignee,
                "due": candidate.due,
                "request": candidate.request,
                "status": candidate.status.value,
                "similarity": round(1 - float(distance), 4),
            }
            for candidate, distance in matches
            if 1 - float(distance) >= MIN_TASK_DUPLICATE_SIMILARITY
        ]
        if duplicates:
            results.append(
                {
                    "task": {
                        "id": item.id,
                        "task": item.task,
                        "assignee": item.assignee,
                        "due": item.due,
                        "request": item.request,
                        "status": item.status.value,
                    },
                    "duplicate_candidates": duplicates,
                }
            )
    return {
        "transcript_id": transcript_id,
        "duplicate_groups": results,
        "threshold": MIN_TASK_DUPLICATE_SIMILARITY,
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
