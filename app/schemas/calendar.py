from pydantic import BaseModel, Field


class CalendarSyncRequest(BaseModel):
    calendar_id: str = Field(default="primary", min_length=1, max_length=256)


class CalendarEventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    start: str = Field(min_length=1, max_length=64)
    end: str | None = Field(default=None, max_length=64)
    description: str = Field(default="", max_length=4000)
    all_day: bool = False
