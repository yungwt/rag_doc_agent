from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.message import Message
from app.models.user import User
from app.schemas.session import (
    SessionCreate,
    SessionResponse,
    SessionListResponse,
    MessageResponse,
    MessageListResponse,
)
from app.services import session_service

router = APIRouter(prefix="/api/sessions", tags=["会话"])


@router.post("/", response_model=SessionResponse, status_code=201)
async def create_session(
    payload: SessionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await session_service.create_session(db, current_user.id, payload.title)


@router.get("/", response_model=SessionListResponse)
async def list_sessions(
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sessions, total = await session_service.list_sessions(db, current_user.id, skip, limit)
    return SessionListResponse(sessions=sessions, total=total)


@router.get("/{session_id}/messages", response_model=MessageListResponse)
async def list_messages(
    session_id: int,
    limit: int = Query(10, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 校验会话属于当前用户
    await session_service.get_session(db, session_id, current_user.id)
    messages = await session_service.get_history(db, session_id, limit)
    # total 与其他列表接口语义对齐：会话消息总数，不受 limit 影响。
    # 前端拿它和 len(messages) 对比，就知道有没有更早的消息被截断
    total = await db.scalar(
        select(func.count()).select_from(Message).where(Message.session_id == session_id)
    )
    return MessageListResponse(messages=messages, total=total or 0)  


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await session_service.delete_session(db, session_id, current_user.id)