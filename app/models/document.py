from sqlalchemy import ForeignKey, Enum as SQLEnum, String, UniqueConstraint
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
    # 同一用户内文件指纹唯一；不同用户允许各自上传相同内容的文件
    __table_args__ = (UniqueConstraint("user_id", "file_hash", name="uq_documents_user_filehash"),)

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
    file_hash: Mapped[str] = mapped_column(String(64), nullable=True, comment="文件MD5指纹")
    chunk_count: Mapped[int] = mapped_column(default=0)
    file_path: Mapped[str] = mapped_column(String(255), nullable=True) 
    # 解析/向量化失败的原因，仅 status=failed 时有值，供前端展示
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="处理失败的原因")