from pydantic import BaseModel


class TranscriptCreate(BaseModel):
    content: str
