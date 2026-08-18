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
    except IntegrityError as e:
        await db.rollback()
        if "username" in str(e):
            raise HTTPException(409, "用户名已存在")
        if "email" in str(e):
            raise HTTPException(409, "邮箱已存在")
        raise HTTPException(500, "注册失败")



async def login(db: AsyncSession, username: str, password: str) -> tuple[User, str, str]:
    """登录成功返回 (用户, access_token, refresh_token)"""
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被禁用")

    return user, create_access_token(user.id), create_refresh_token(user.id)