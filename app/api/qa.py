from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.message import Message
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.qa import QuestionRequest, AnswerResponse
from app.services import rag_service, session_service
from sqlalchemy import select, func, text

router = APIRouter(prefix="/api/qa", tags=["问答"])


@router.post("/", response_model=AnswerResponse)
async def ask(
    payload: QuestionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 校验 session 存在且属于当前用户（隐藏其他用户的会话存在性）
    await session_service.get_session(db, payload.session_id, current_user.id)

    # 如果是第一条消息，用问题内容更新会话标题
    count_result = await db.execute(
        select(func.count()).select_from(Message).where(Message.session_id == payload.session_id)
    )
    if count_result.scalar() == 0:
        title = payload.question[:50]  # 截取前50字
        await db.execute(
            text("UPDATE sessions SET title=:title WHERE id=:id"),
            {"title": title, "id": payload.session_id},
        )
    # 存用户消息
    await session_service.save_message(db, payload.session_id, "user", payload.question)

    # 检索 + 生成
    result = await rag_service.ask_question(db, current_user.id, payload.question, session_id=payload.session_id)

    # 存助手消息
    await session_service.save_message(
        db, payload.session_id, "assistant", result["answer"], result["sources"]
    )

    return result