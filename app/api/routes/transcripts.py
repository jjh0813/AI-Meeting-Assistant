import logging
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
)
from sqlalchemy.orm import Session

from app.api.deps import get_approved_user, get_current_admin
from app.core.database import SessionLocal, get_db
from app.models.transcript import ActionItemStatus, Transcript
from app.models.user import User
from app.repositories import transcript as transcript_repo
from app.schemas.transcript import (
    ActionItemStatusUpdate,
    TranscriptCreate,
    TranscriptQuestionRequest,
    TranscriptSearchRequest,
    TranscriptTitleUpdate,
)
from app.services.analyzer import analyze, summarize
from app.services.chunking import split_text
from app.services.embedding import embed
from app.services.masking import mask_text
from app.services.personalization import (
    is_assigned_to_user,
    personalize_masked_text,
    remask_personalized_text,
)
from app.services.qa import answer_from_meetings
from app.services.question_guard import guard_meeting_question
from app.services.report import build_pdf_report, build_text_report
from app.services.retrieval import (
    allows_semantic_only_evidence,
    answer_indicates_missing_evidence,
    asks_for_personal_tasks,
    has_sufficient_evidence,
    rerank_sources,
)
from app.services.stt import transcribe

router = APIRouter(prefix="/transcripts", tags=["transcripts"])
logger = logging.getLogger(__name__)

MIN_TASK_DUPLICATE_SIMILARITY = 0.75
MEETING_ONLY_MESSAGE = "Noting은 내 회의록과 업무 관련 질문만 답할 수 있습니다."
NO_EVIDENCE_MESSAGE = "질문과 관련된 내용을 회의록에서 확인할 수 없습니다."
MAX_AUDIO_BYTES = 25 * 1024 * 1024
ALLOWED_AUDIO_EXTENSIONS = {
    ".aac",
    ".flac",
    ".m4a",
    ".mp3",
    ".mp4",
    ".ogg",
    ".wav",
    ".webm",
}
ALLOWED_AUDIO_CONTENT_TYPES = {
    "audio/aac",
    "audio/flac",
    "audio/m4a",
    "audio/mp4",
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "audio/webm",
    "audio/x-m4a",
    "audio/x-wav",
    "video/mp4",
    "video/webm",
}


def read_audio_upload(file: UploadFile) -> bytes:
    filename = file.filename or ""
    extension = Path(filename).suffix.lower()
    content_type = (file.content_type or "").lower()
    if (
        extension not in ALLOWED_AUDIO_EXTENSIONS
        and content_type not in ALLOWED_AUDIO_CONTENT_TYPES
    ):
        raise HTTPException(
            status_code=415,
            detail="지원하지 않는 파일 형식입니다. WAV, MP3, M4A 등 음성 파일을 업로드해 주세요.",
        )
    audio_bytes = file.file.read(MAX_AUDIO_BYTES + 1)
    if not audio_bytes:
        raise HTTPException(status_code=422, detail="비어 있는 음성 파일입니다.")
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail="음성 파일은 25MB 이하만 업로드할 수 있습니다.",
        )
    return audio_bytes


def serialize_action_item(item, pii_entries, current_user: User) -> dict:
    return {
        "id": item.id,
        "task": personalize_masked_text(
            item.task, pii_entries, current_user.display_name
        ),
        "assignee": personalize_masked_text(
            item.assignee, pii_entries, current_user.display_name
        ),
        "due": personalize_masked_text(
            item.due, pii_entries, current_user.display_name
        ),
        "request": personalize_masked_text(
            item.request, pii_entries, current_user.display_name
        ),
        "status": item.status.value,
        "superseded_by_id": item.superseded_by_id,
        "is_mine": is_assigned_to_user(
            item.assignee, pii_entries, current_user.display_name
        ),
    }


def serialize_transcript(
    db: Session, current_user: User, transcript: Transcript
) -> dict:
    pii_entries = transcript_repo.get_pii_entries(
        db, current_user, transcript.id
    )
    analysis_status = transcript.analysis_status or (
        "completed" if transcript.summary is not None else "pending"
    )
    return {
        "id": transcript.id,
        "title": personalize_masked_text(
            transcript.title or f"회의록 #{transcript.id}",
            pii_entries,
            current_user.display_name,
        ),
        "title_is_manual": transcript.title_is_manual,
        "department": transcript.department.value,
        "masked_content": personalize_masked_text(
            transcript.masked_content, pii_entries, current_user.display_name
        ),
        "summary": personalize_masked_text(
            transcript.summary, pii_entries, current_user.display_name
        ),
        "analysis_status": analysis_status,
        "analysis_error": transcript.analysis_error,
        "created_at": transcript.created_at.isoformat()
        if transcript.created_at
        else None,
    }


def stored_analysis(db: Session, current_user: User, transcript_id: int):
    transcript = transcript_repo.get_transcript(db, current_user, transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="회의록을 찾을 수 없습니다.")
    if transcript.summary is None:
        raise HTTPException(
            status_code=409,
            detail="보고서를 만들기 전에 회의록을 분석해 주세요.",
        )
    items = transcript_repo.get_action_items(db, current_user, transcript_id)
    pii_entries = transcript_repo.get_pii_entries(db, current_user, transcript_id)
    return transcript, {
        "title": personalize_masked_text(
            transcript.title or f"회의록 #{transcript.id}",
            pii_entries,
            current_user.display_name,
        ),
        "summary": personalize_masked_text(
            transcript.summary, pii_entries, current_user.display_name
        ),
        "tasks": [
            serialize_action_item(item, pii_entries, current_user)
            for item in items
        ],
    }


def find_rag_sources(
    db: Session,
    current_user: User,
    query: str,
    query_embedding: list[float],
    limit: int,
) -> list[dict]:
    candidate_limit = min(max(limit * 4, 20), 100)
    chunk_matches = transcript_repo.search_similar_chunks(
        db, current_user, query_embedding, candidate_limit
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
        db, current_user, query_embedding, candidate_limit
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
    task_matches = transcript_repo.search_action_items_for_qa(
        db, current_user, query_embedding, candidate_limit
    )
    personal_task_query = asks_for_personal_tasks(query)
    task_sources = []
    for item, transcript, distance in task_matches:
        pii_entries = transcript_repo.get_pii_entries(
            db, current_user, transcript.id
        )
        if personal_task_query and not is_assigned_to_user(
            item.assignee, pii_entries, current_user.display_name
        ):
            continue
        task_sources.append(
            {
                "id": transcript.id,
                "chunk_id": None,
                "chunk_index": None,
                "content": "\n".join(
                    (
                        f"업무: {item.task or '업무명 없음'}",
                        f"담당자: {item.assignee or '담당 미지정'}",
                        f"기한: {item.due or '기한 미정'}",
                        f"요청사항: {item.request or '요청사항 없음'}",
                        f"상태: {item.status.value}",
                    )
                ),
                "summary": transcript.summary,
                "source_type": "action_item",
                "similarity": round(1 - float(distance), 4),
                "created_at": transcript.created_at.isoformat()
                if transcript.created_at
                else None,
            }
        )
    pii_cache = {}
    personalized_sources = []
    for source in chunk_sources + summary_sources + task_sources:
        transcript_id = source["id"]
        if transcript_id not in pii_cache:
            pii_cache[transcript_id] = transcript_repo.get_pii_entries(
                db, current_user, transcript_id
            )
        pii_entries = pii_cache[transcript_id]
        personalized_sources.append(
            {
                **source,
                "content": personalize_masked_text(
                    source["content"], pii_entries, current_user.display_name
                ),
                "summary": personalize_masked_text(
                    source["summary"], pii_entries, current_user.display_name
                ),
            }
        )
    return rerank_sources(query, personalized_sources, limit)


def run_analysis_pipeline(db: Session, current_user: User, transcript: Transcript):
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
        result["title"],
        result["summary"],
        indexed_tasks,
        embedding,
        indexed_chunks,
    )
    saved_items = transcript_repo.get_action_items(db, current_user, transcript.id)
    pii_entries = transcript_repo.get_pii_entries(
        db, current_user, transcript.id
    )
    return {
        "id": transcript.id,
        "title": personalize_masked_text(
            transcript.title or f"회의록 #{transcript.id}",
            pii_entries,
            current_user.display_name,
        ),
        "title_is_manual": transcript.title_is_manual,
        "summary": personalize_masked_text(
            result["summary"], pii_entries, current_user.display_name
        ),
        "tasks": [
            serialize_action_item(item, pii_entries, current_user)
            for item in saved_items
        ],
        "indexed_chunks": len(indexed_chunks),
        "indexed_tasks": sum(
            1 for task in indexed_tasks if task["task_embedding"] is not None
        ),
    }


def run_analysis_job(transcript_id: int, user_id: int):
    db = SessionLocal()
    try:
        current_user = db.query(User).filter(User.id == user_id).first()
        if current_user is None:
            raise RuntimeError("분석을 요청한 사용자를 찾을 수 없습니다.")
        transcript = transcript_repo.get_transcript(db, current_user, transcript_id)
        if transcript is None:
            raise RuntimeError("분석할 회의록을 찾을 수 없습니다.")
        run_analysis_pipeline(db, current_user, transcript)
    except Exception as exc:
        db.rollback()
        logger.exception("Background analysis failed for transcript %s", transcript_id)
        transcript = db.query(Transcript).filter(Transcript.id == transcript_id).first()
        if transcript is not None:
            transcript_repo.update_analysis_status(
                db,
                transcript,
                "failed",
                str(exc)[:500] or "분석 중 알 수 없는 오류가 발생했습니다.",
            )
    finally:
        db.close()


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
        **serialize_transcript(db, current_user, transcript),
    }


@router.get("")
def list_transcripts(
    current_user: User = Depends(get_approved_user), db: Session = Depends(get_db)
):
    transcripts = transcript_repo.list_transcripts(db, current_user)
    return [serialize_transcript(db, current_user, t) for t in transcripts]


@router.get("/archive")
def list_archived_transcripts(
    current_user: User = Depends(get_approved_user), db: Session = Depends(get_db)
):
    transcripts = transcript_repo.list_archived_transcripts(db, current_user)
    return [
        {
            **serialize_transcript(db, current_user, transcript),
            "archived_at": transcript.archived_at.isoformat()
            if transcript.archived_at
            else None,
            "task_count": len(
                transcript_repo.get_action_items(db, current_user, transcript.id)
            ),
        }
        for transcript in transcripts
    ]


@router.get("/tasks/archive")
def list_archived_tasks(
    current_user: User = Depends(get_approved_user), db: Session = Depends(get_db)
):
    rows = transcript_repo.list_archived_action_items(db, current_user)
    results = []
    for item, transcript in rows:
        pii_entries = transcript_repo.get_pii_entries(
            db, current_user, transcript.id
        )
        serialized = serialize_action_item(item, pii_entries, current_user)
        if not serialized["is_mine"]:
            continue
        results.append(
            {
                **serialized,
                "transcript_id": transcript.id,
                "transcript_title": personalize_masked_text(
                    transcript.title or f"회의록 #{transcript.id}",
                    pii_entries,
                    current_user.display_name,
                ),
                "archived_at": item.archived_at.isoformat()
                if item.archived_at
                else None,
            }
        )
    return results


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

    results = find_rag_sources(
        db, current_user, query, query_embedding, body.limit
    )
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

    allow_semantic_only = allows_semantic_only_evidence(question)
    sources = [
        source
        for source in find_rag_sources(
            db, current_user, question, query_embedding, limit=3
        )
        if has_sufficient_evidence(
            source, allow_semantic_only=allow_semantic_only
        )
    ]
    if not sources:
        return {
            "answer": NO_EVIDENCE_MESSAGE,
            "sources": [],
            "grounded": False,
            "blocked": True,
            "blocked_reason": "low_similarity",
        }

    answer = answer_from_meetings(
        question, sources, current_user.display_name
    )
    if answer_indicates_missing_evidence(answer):
        return {
            "answer": answer,
            "sources": [],
            "grounded": False,
            "blocked": True,
            "blocked_reason": "insufficient_context",
        }
    return {
        "answer": answer,
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
    pii_entries = transcript_repo.get_pii_entries(db, current_user, transcript_id)
    safe_content = personalize_masked_text(
        transcript.masked_content, pii_entries, current_user.display_name
    )
    summary = summarize(safe_content)
    return {
        "id": transcript.id,
        "summary": personalize_masked_text(
            summary, pii_entries, current_user.display_name
        ),
    }


@router.post("/{transcript_id}/analysis")
def analyze_transcript(
    transcript_id: int,
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    transcript = transcript_repo.get_transcript(db, current_user, transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="회의록을 찾을 수 없습니다.")
    return run_analysis_pipeline(db, current_user, transcript)


@router.post("/{transcript_id}/analysis/start", status_code=202)
def start_transcript_analysis(
    transcript_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    transcript = transcript_repo.get_transcript(db, current_user, transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="회의록을 찾을 수 없습니다.")
    if transcript.analysis_status == "completed" and transcript.summary is not None:
        return {"id": transcript.id, "analysis_status": "completed"}

    # Re-submitting a processing job is intentional: if the web process was
    # restarted mid-analysis, the persisted state can be recovered by retrying.
    transcript_repo.update_analysis_status(db, transcript, "processing")
    background_tasks.add_task(run_analysis_job, transcript.id, current_user.id)
    return {"id": transcript.id, "analysis_status": "processing"}


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
    pii_entries = transcript_repo.get_pii_entries(db, current_user, transcript_id)
    return {
        "id": transcript.id,
        "title": personalize_masked_text(
            transcript.title or f"회의록 #{transcript.id}",
            pii_entries,
            current_user.display_name,
        ),
        "title_is_manual": transcript.title_is_manual,
        "department": transcript.department.value,
        "masked_content": personalize_masked_text(
            transcript.masked_content, pii_entries, current_user.display_name
        ),
        "created_at": transcript.created_at.isoformat()
        if transcript.created_at
        else None,
        "summary": personalize_masked_text(
            transcript.summary, pii_entries, current_user.display_name
        ),
        "analysis_status": transcript.analysis_status,
        "analysis_error": transcript.analysis_error,
        "tasks": [
            serialize_action_item(item, pii_entries, current_user)
            for item in items
        ],
    }


@router.patch("/{transcript_id}/title")
def update_transcript_title(
    transcript_id: int,
    body: TranscriptTitleUpdate,
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    transcript = transcript_repo.get_transcript(db, current_user, transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="회의록을 찾을 수 없습니다.")
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="회의 제목을 입력해 주세요.")
    updated = transcript_repo.update_transcript_title(db, transcript, title)
    return {
        "id": updated.id,
        "title": updated.title,
        "title_is_manual": updated.title_is_manual,
    }


@router.post("/{transcript_id}/archive")
def archive_transcript(
    transcript_id: int,
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    transcript = transcript_repo.get_transcript(db, current_user, transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="회의록을 찾을 수 없습니다.")
    archived = transcript_repo.archive_transcript(db, transcript)
    return {
        "id": archived.id,
        "archived": archived.archived,
        "archived_at": archived.archived_at.isoformat()
        if archived.archived_at
        else None,
    }


@router.post("/{transcript_id}/restore")
def restore_transcript(
    transcript_id: int,
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    transcript = transcript_repo.get_transcript(db, current_user, transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="회의록을 찾을 수 없습니다.")
    restored = transcript_repo.restore_transcript(db, transcript)
    return {"id": restored.id, "archived": restored.archived}


@router.delete("/{transcript_id}", status_code=204)
def delete_transcript(
    transcript_id: int,
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    transcript = transcript_repo.get_transcript(db, current_user, transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="회의록을 찾을 수 없습니다.")
    try:
        transcript_repo.delete_archived_transcript(db, transcript)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(status_code=204)


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


@router.post("/{transcript_id}/tasks/{task_id}/archive")
def archive_task(
    transcript_id: int,
    task_id: int,
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    item = transcript_repo.get_action_item(
        db, current_user, transcript_id, task_id
    )
    if item is None:
        raise HTTPException(status_code=404, detail="할 일을 찾을 수 없습니다.")
    archived = transcript_repo.archive_action_item(db, item)
    return {"id": archived.id, "archived": archived.archived}


@router.post("/{transcript_id}/tasks/{task_id}/restore")
def restore_task(
    transcript_id: int,
    task_id: int,
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    item = transcript_repo.get_action_item(
        db, current_user, transcript_id, task_id
    )
    if item is None:
        raise HTTPException(status_code=404, detail="할 일을 찾을 수 없습니다.")
    restored = transcript_repo.restore_action_item(db, item)
    return {"id": restored.id, "archived": restored.archived}


@router.delete("/{transcript_id}/tasks/{task_id}", status_code=204)
def delete_task(
    transcript_id: int,
    task_id: int,
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    item = transcript_repo.get_action_item(
        db, current_user, transcript_id, task_id
    )
    if item is None:
        raise HTTPException(status_code=404, detail="할 일을 찾을 수 없습니다.")
    try:
        transcript_repo.delete_archived_action_item(db, item)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(status_code=204)


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
            item.status in (ActionItemStatus.completed, ActionItemStatus.superseded)
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


@router.get("/{transcript_id}/schedule-change-candidates")
def find_schedule_change_candidates(
    transcript_id: int,
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    transcript = transcript_repo.get_transcript(db, current_user, transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="회의록을 찾을 수 없습니다.")

    items = transcript_repo.get_action_items(db, current_user, transcript_id)
    candidates = []
    for item in items:
        if (
            item.status in (ActionItemStatus.completed, ActionItemStatus.superseded)
            or item.task_embedding is None
            or not item.due.strip()
        ):
            continue
        matches = transcript_repo.search_similar_action_items(
            db,
            current_user,
            item.task_embedding,
            exclude_transcript_id=transcript_id,
        )
        for previous, distance in matches:
            similarity = 1 - float(distance)
            if (
                similarity < MIN_TASK_DUPLICATE_SIMILARITY
                or (
                    previous.created_at is not None
                    and item.created_at is not None
                    and previous.created_at >= item.created_at
                )
                or not previous.due.strip()
                or previous.due.strip() == item.due.strip()
            ):
                continue
            candidates.append(
                {
                    "task": {
                        "id": item.id,
                        "task": item.task,
                        "assignee": item.assignee,
                        "due": item.due,
                    },
                    "previous_task": {
                        "id": previous.id,
                        "transcript_id": previous.transcript_id,
                        "task": previous.task,
                        "assignee": previous.assignee,
                        "due": previous.due,
                        "status": previous.status.value,
                    },
                    "similarity": round(similarity, 4),
                }
            )
    return {
        "transcript_id": transcript_id,
        "change_candidates": candidates,
        "threshold": MIN_TASK_DUPLICATE_SIMILARITY,
    }


@router.post(
    "/{transcript_id}/tasks/{task_id}/schedule-changes/{previous_task_id}/confirm"
)
def confirm_task_schedule_change(
    transcript_id: int,
    task_id: int,
    previous_task_id: int,
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    current_item = transcript_repo.get_action_item(
        db, current_user, transcript_id, task_id
    )
    if current_item is None:
        raise HTTPException(status_code=404, detail="새 업무를 찾을 수 없습니다.")
    previous_item = transcript_repo.get_action_item_by_id(
        db, current_user, previous_task_id
    )
    if previous_item is None:
        raise HTTPException(status_code=404, detail="이전 업무를 찾을 수 없습니다.")
    if previous_item.transcript_id == transcript_id:
        raise HTTPException(status_code=400, detail="같은 회의의 업무는 변경 대상으로 지정할 수 없습니다.")
    if (
        previous_item.created_at is not None
        and current_item.created_at is not None
        and previous_item.created_at >= current_item.created_at
    ):
        raise HTTPException(status_code=400, detail="이전 회의에서 생성된 업무만 변경 대상으로 지정할 수 있습니다.")
    if (
        current_item.status in (ActionItemStatus.completed, ActionItemStatus.superseded)
        or previous_item.status
        in (ActionItemStatus.completed, ActionItemStatus.superseded)
    ):
        raise HTTPException(status_code=400, detail="완료되거나 이미 변경된 업무입니다.")
    if (
        not current_item.due.strip()
        or not previous_item.due.strip()
        or current_item.due.strip() == previous_item.due.strip()
    ):
        raise HTTPException(status_code=400, detail="서로 다른 기존·신규 기한이 필요합니다.")
    if current_item.task_embedding is None:
        raise HTTPException(status_code=400, detail="새 업무의 임베딩이 없습니다. 회의록을 다시 분석해 주세요.")

    distance = transcript_repo.get_action_item_similarity(
        db,
        current_user,
        current_item.task_embedding,
        previous_item.id,
    )
    similarity = None if distance is None else 1 - distance
    if similarity is None or similarity < MIN_TASK_DUPLICATE_SIMILARITY:
        raise HTTPException(status_code=400, detail="일정 변경으로 확인할 만큼 유사한 업무가 아닙니다.")

    updated_previous = transcript_repo.confirm_schedule_change(
        db, previous_item, current_item
    )
    return {
        "previous_task_id": updated_previous.id,
        "previous_due": updated_previous.due,
        "new_task_id": current_item.id,
        "new_due": current_item.due,
        "similarity": round(similarity, 4),
        "status": updated_previous.status.value,
    }


@router.get("/{transcript_id}/report")
def get_text_report(
    transcript_id: int,
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    transcript, analysis = stored_analysis(db, current_user, transcript_id)
    return {"id": transcript.id, "report": build_text_report(analysis)}


@router.get("/{transcript_id}/report.pdf")
def get_pdf_report(
    transcript_id: int,
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    transcript, analysis = stored_analysis(db, current_user, transcript_id)
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
    existing = transcript_repo.get_transcript(db, current_user, transcript_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="회의록을 찾을 수 없습니다.")
    existing_pii = transcript_repo.get_pii_entries(
        db, current_user, transcript_id
    )
    masked_content, pii_items = remask_personalized_text(
        body.content, existing_pii, current_user.display_name
    )
    transcript = transcript_repo.update_transcript(
        db, current_user, transcript_id, masked_content, pii_items
    )
    if transcript is None:
        raise HTTPException(status_code=404, detail="회의록을 찾을 수 없습니다.")
    return {
        **serialize_transcript(db, current_user, transcript),
        "analysis_required": True,
    }


@router.post("/upload")
def upload_and_transcribe(
    file: UploadFile = File(...),
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    audio_bytes = read_audio_upload(file)
    text = transcribe(audio_bytes, file.filename or "audio")
    masked_content, pii_items = mask_text(text)
    transcript = transcript_repo.create_transcript(
        db, current_user, masked_content, pii_items
    )
    return serialize_transcript(db, current_user, transcript)
