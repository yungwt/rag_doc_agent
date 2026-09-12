from datetime import datetime
from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    title: str = Field(default="新对话", max_length=200)


class SessionResponse(BaseModel):
    id: int
    user_id: int
    title: str
    creat_time: datetime
    update_time: datetime

    model_config = {"from_attributes": True}


class SessionListResponse(BaseModel):
    sessions: list[SessionResponse]
    total: int


class MessageResponse(BaseModel):
    id: int
    session_id: int
    role: str
    content: str
    sources: list | None
    creat_time: datetime

    model_config = {"from_attributes": True}


class MessageListResponse(BaseModel):
    messages: list[MessageResponse]
    total: int