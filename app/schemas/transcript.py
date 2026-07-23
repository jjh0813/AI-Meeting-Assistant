from typing import Literal

from pydantic import BaseModel, Field


class TranscriptCreate(BaseModel):
    content: str


class TranscriptSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=5, ge=1, le=20)


class TranscriptQuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class ActionItemStatusUpdate(BaseModel):
    status: Literal["대기", "진행중", "완료"]
