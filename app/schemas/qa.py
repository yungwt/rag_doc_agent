from pydantic import BaseModel, Field


class QuestionRequest(BaseModel):
    question: str = Field(max_length=2000)
    session_id: int


class SourceInfo(BaseModel):
    document_id: int
    title: str
    chunk_index: int
    content: str


class AnswerResponse(BaseModel):
    answer: str
    sources: list[SourceInfo]