from sqlalchemy import ForeignKey, Enum as SQLEnum, String
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base
import enum


class DocStatus(str, enum.Enum):
    UPLOADING = "uploading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=True)
    file_size: Mapped[int] = mapped_column(nullable=True)
    status: Mapped[DocStatus] = mapped_column(
        SQLEnum(DocStatus),
        default=DocStatus.UPLOADING,
        nullable=False,
    )
    file_hash: Mapped[str] = mapped_column(String(64), unique=True,nullable=True, comment="文件MD5指纹")
    chunk_count: Mapped[int] = mapped_column(default=0)
    file_path: Mapped[str] = mapped_column(String(255), nullable=True) 