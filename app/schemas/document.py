from datetime import datetime
from pydantic import BaseModel


class DocumentResponse(BaseModel):
    id: int
    user_id: int
    title: str
    file_type: str | None
    file_size: int | None
    status: str
    chunk_count: int
    error_message: str | None = None
    creat_time: datetime
    update_time: datetime

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    total: int