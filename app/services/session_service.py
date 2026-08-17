from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.models.session import Session
from app.models.message import Message


async def create_session(db: AsyncSession, user_id: int, title: str = "新对话") -> Session:
    session = Session(user_id=user_id, title=title)
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return session


async def list_sessions(
    db: AsyncSession, user_id: int, skip: int = 0, limit: int = 20
) -> tuple[list[Session], int]:
    count_result = await db.execute(
        select(func.count()).select_from(Session).where(Session.user_id == user_id)
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        select(Session)
        .where(Session.user_id == user_id)
        .order_by(Session.update_time.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all()), total


async def get_session(db: AsyncSession, session_id: int, user_id: int) -> Session:
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    return session


async def delete_session(db: AsyncSession, session_id: int, user_id: int):
    session = await get_session(db, session_id, user_id)
    # 先删所有消息
    await db.execute(
        text("DELETE FROM messages WHERE session_id = :id"),
        {"id": session_id},
    )
    await db.delete(session)
    await db.flush()

async def save_message(
    db: AsyncSession, session_id: int, role: str, content: str, sources: list | None = None
) -> Message:
    msg = Message(session_id=session_id, role=role, content=content, sources=sources)
    db.add(msg)
    await db.flush()
    await db.refresh(msg)
    # 顺便更新 session 的 update_time
    await db.execute(
        text("UPDATE sessions SET update_time=now() WHERE id=:id"),
        {"id": session_id},
    )
    return msg


async def get_history(db: AsyncSession, session_id: int, limit: int = 10) -> list[Message]:
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.creat_time.desc())
        .limit(limit)
    )
    messages = list(result.scalars().all())
    messages = messages[::-1]  
    
    return messages