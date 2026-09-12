from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.models.user import User
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token


async def register(db: AsyncSession, username: str, email: str | None, password: str) -> User:
    """注册新用户，用户名或邮箱重复则报错"""
    # 检查用户名是否已存在
    result = await db.execute(select(User).where(User.username == username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在")

    # 检查邮箱是否已存在
    if email:
        result = await db.execute(select(User).where(User.email == email))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="邮箱已被注册")

    user = User(
        username=username,
        email=email,
        hashed_password=hash_password(password),
    )
    try:
        db.add(user)
        await db.flush()
        await db.refresh(user)
        await db.commit()
        return user
    except IntegrityError:
        # 兜底：并发注册撞上唯一约束（正常流程已被上面的 SELECT 提前拦住）
        await db.rollback()
        raise HTTPException(409, "用户名或邮箱已被占用")



async def login(db: AsyncSession, username: str, password: str) -> tuple[User, str, str]:
    """登录成功返回 (用户, access_token, refresh_token)"""
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被禁用")

    return user, create_access_token(user.id), create_refresh_token(user.id)


async def set_active(db: AsyncSession, user_id: int, active: bool) -> User:
    """启用 / 禁用账号。

    只作为 service 层函数供运维脚本调用，不暴露 HTTP 接口：当前没有角色体系
    （User 表无 is_admin），开放管理端点等于给任何已登录用户一个提权入口。
    禁用后该用户手上的 access / refresh 会立即失效（每请求都会重新查库校验）。
    """
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    user.is_active = active
    await db.commit()
    await db.refresh(user)
    return user