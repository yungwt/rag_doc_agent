from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.settings import HistoryLimitUpdate, SettingsResponse

router = APIRouter(prefix="/api/settings", tags=["设置"])


@router.get("/", response_model=SettingsResponse)
async def get_settings(current_user: User = Depends(get_current_user)):
    """查看当前生效的记忆长度"""
    return SettingsResponse(
        history_limit=current_user.history_limit or settings.SESSION_HISTORY_LIMIT,
        default_history_limit=settings.SESSION_HISTORY_LIMIT,
    )


@router.put("/history-limit", response_model=SettingsResponse)
async def update_history_limit(
    payload: HistoryLimitUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """修改记忆长度；传 null 重置为跟随全局默认"""
    current_user.history_limit = payload.history_limit
    # 必须显式提交：靠 get_db 的 teardown 提交会晚于响应返回，用户保存后立刻刷新会读到旧值
    await db.commit()
    return SettingsResponse(
        history_limit=payload.history_limit or settings.SESSION_HISTORY_LIMIT,
        default_history_limit=settings.SESSION_HISTORY_LIMIT,
    )
