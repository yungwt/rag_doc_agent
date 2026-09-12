from fastapi import APIRouter, Depends, HTTPException
from openai import APIError
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
    user_msg = await session_service.save_message(db, payload.session_id, "user", payload.question)
    # 立刻提交：生成要几秒到几十秒，不提交的话这期间的请求读不到这条问题
    # （用户切走页面再切回来会重新拉历史，就会看不到自己刚问的内容）
    await db.commit()

    # 检索 + 生成
    try:
        result = await rag_service.ask_question(
            db, current_user.id, payload.question,
            session_id=payload.session_id, history_limit=current_user.history_limit,
        )
    except APIError as e:
        # 模型服务侧的错误（额度耗尽 / 限流 / 连不上）转成可读提示，不再裸 500
        code = getattr(e, "status_code", None)
        if code == 403:
            detail = "模型服务不可用：账号额度不足或已被限制，请检查模型平台余额"
        elif code == 429:
            detail = "模型调用过于频繁，请稍后重试"
        else:
            detail = "模型服务调用失败，请稍后重试"
        # 生成失败：删掉刚落的用户消息，避免用户重试后历史重复提问
        # （首条消息更新的标题不用回滚：消息删掉后计数归 0，下次成功提问会重新覆盖）
        await db.delete(user_msg)
        await db.commit()
        raise HTTPException(status_code=503, detail=detail) from e

    # 存助手消息
    await session_service.save_message(
        db, payload.session_id, "assistant", result["answer"], result["sources"]
    )
    # 显式提交：assistant 消息只 flush 的话，commit 要等响应发出后的 teardown 才发生，
    # 答完立刻重拉历史的请求可能短暂读不到刚生成的回答
    await db.commit()

    return result