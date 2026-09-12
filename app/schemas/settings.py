from pydantic import BaseModel, Field


class HistoryLimitUpdate(BaseModel):
    """记忆长度更新请求；传 null 表示重置为跟随全局默认"""
    history_limit: int | None = Field(default=None, ge=1, le=50)


class SettingsResponse(BaseModel):
    history_limit: int          # 当前生效的记忆长度
    default_history_limit: int  # 全局默认值（前端展示参考）
