from sqlalchemy import ForeignKey, Text, String
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(nullable=False, comment="切片序号，从0开始")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="切片文本内容")
    vector_id: Mapped[str] = mapped_column(String(255),nullable=True, comment="Chroma向量库中的ID")