import asyncio
import os
import uuid
from pathlib import Path
import hashlib
from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.rag_service import process_document, delete_document_vectors
from app.core.config import settings
from app.models.document import Document, DocStatus


UPLOAD_DIR = settings.UPLOAD_DIR
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
# 允许的文件类型
ALLOWED_TYPES = {".pdf", ".txt", ".md"}

# 持有后台解析任务的强引用：事件循环只保留弱引用，
# 不持有的话任务可能在长解析中途被 GC 回收，文档永远卡在"处理中"
_background_tasks: set = set()

async def upload_document(db: AsyncSession, user_id: int, file: UploadFile) -> Document:
    """保存文件，创建文档记录，状态为 uploading"""
    # 校验文件类型
    ext = Path(file.filename).suffix.lower() if file.filename else ""
    if ext not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的文件类型: {ext or '未知'}，仅支持 PDF、TXT、MD",
        )
    # 校验文件大小
    contents = await file.read()
    file_hash = hashlib.md5(contents).hexdigest()
    # 查重
    result = await db.execute(
        select(Document).where(
            Document.user_id == user_id,
            Document.file_hash == file_hash,
            Document.status != DocStatus.FAILED,  # 失败记录不占坑，允许重传同一文件
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"文件已存在（ID: {existing.id}），请勿重复上传",
        )
    if len(contents) > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"文件大小超过 {settings.MAX_UPLOAD_SIZE_MB}MB 限制",
        )

    # 生成唯一文件名，防止覆盖
    saved_name = f"{uuid.uuid4().hex}{ext}"
    file_path = UPLOAD_DIR / saved_name

    with open(file_path, "wb") as f:
        f.write(contents)

    # 取原始文件名和扩展名
    original_title = file.filename or "unknown"
    file_type = ext.lstrip(".") if ext else None

    doc = Document(
        user_id=user_id,
        title=original_title,
        file_type=file_type,
        file_size=len(contents),
        status=DocStatus.UPLOADING,
        file_hash=file_hash,
        file_path=file_path
    )
    db.add(doc)
    try:
        await db.flush()
        await db.refresh(doc)
        await db.commit()
        
        task = asyncio.create_task(process_document(doc.id, file_path))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
        return doc
        
    except IntegrityError as e:
        # ✅ 唯一约束冲突：文件已存在
        await db.rollback()
        # 删除已保存的文件
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(
            status_code=409,
            detail="文件已存在，请勿重复上传"
        )
        
    except Exception as e:
        # ✅ 其他异常：服务器错误
        await db.rollback()
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(
            status_code=500,
            detail=f"文档保存失败: {str(e)}"
        )

async def list_documents(
    db: AsyncSession,
    user_id: int,
    skip: int = 0,
    limit: int = 20,
    status: str | None = None,
) -> tuple[list[Document], int]:
    """分页查询用户的文档列表（status 可选：completed / processing / failed，None=全部）"""
    conditions = [Document.user_id == user_id]
    if status:
        # 前端的「处理中」对应 uploading + processing 两种状态
        statuses = ["uploading", "processing"] if status == "processing" else [status]
        conditions.append(Document.status.in_(statuses))

    # 查询总数（按当前筛选条件）
    count_result = await db.execute(
        select(func.count()).select_from(Document).where(*conditions)
    )
    total = count_result.scalar() or 0

    # 查询列表
    result = await db.execute(
        select(Document)
        .where(*conditions)
        # 按 id 排序：creat_time 只有秒级精度，同秒多份文档顺序不稳定会导致分页重复/遗漏
        .order_by(Document.id.desc())
        .offset(skip)
        .limit(limit)
    )
    documents = result.scalars().all()

    return list(documents), total

async def delete_document(db: AsyncSession, document_id: int, user_id: int) -> None:
    """删除文档（仅所有者可删除）"""
    # 查询文档
    result = await db.execute(
        select(Document).where(Document.id == document_id)
    )
    doc = result.scalar_one_or_none()
    
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    
    if doc.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权删除此文档")
    
    # 删除物理文件
    if doc.file_path:
        try:
            os.remove(doc.file_path)
        except FileNotFoundError:
            pass  # 文件已不在（如数据卷重建过），不该阻塞删除流程

    # 删除向量库中对应的向量
    delete_document_vectors(user_id, doc.id)

    # 删除数据库记录
    await db.delete(doc)
    # 必须显式提交：依赖清理阶段才提交的话，前端"删除成功立刻刷新"会读到旧列表
    await db.commit()