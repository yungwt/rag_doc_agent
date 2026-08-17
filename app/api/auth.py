from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    blacklist_token,
    is_token_blacklisted,
    set_auth_cookies,
    clear_auth_cookies,
)
from app.models.user import User
from app.schemas.user import UserRegister, UserLogin, UserResponse
from app.services import auth_service

router = APIRouter(prefix="/api/auth", tags=["认证"])


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(payload: UserRegister, db: AsyncSession = Depends(get_db)):
    user = await auth_service.register(db, payload.username, payload.email, payload.password)
    return user


@router.post("/login", response_model=UserResponse)
async def login(payload: UserLogin, response: Response, db: AsyncSession = Depends(get_db)):
    user, access_token, refresh_token = await auth_service.login(
        db, payload.username, payload.password
    )
    set_auth_cookies(response, access_token, refresh_token)
    return user


@router.post("/logout")
async def logout(request: Request, response: Response):
    access_token = request.cookies.get(settings.COOKIE_ACCESS_NAME)
    refresh_token = request.cookies.get(settings.COOKIE_REFRESH_NAME)

    # 兼容 Authorization header（Swagger / 非浏览器客户端）
    if not access_token:
        auth = request.headers.get("Authorization")
        if auth and auth.lower().startswith("bearer "):
            access_token = auth[7:].strip()

    now = int(datetime.now(timezone.utc).timestamp())
    for token in (access_token, refresh_token):
        if not token:
            continue
        try:
            payload = decode_token(token)
            remaining = payload["exp"] - now
            await blacklist_token(token, max(remaining, 1))
        except HTTPException:
            pass  # token 无效或已过期，忽略

    clear_auth_cookies(response)
    return {"msg": "已登出"}


@router.post("/refresh")
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    refresh_token: str | None = Body(None, embed=True),
):
    token = request.cookies.get(settings.COOKIE_REFRESH_NAME) or refresh_token
    if not token:
        raise HTTPException(status_code=401, detail="缺少刷新令牌")

    payload = decode_token(token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="无效的刷新令牌")
    if await is_token_blacklisted(token):
        raise HTTPException(status_code=401, detail="刷新令牌已失效")

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=401, detail="无效的刷新令牌")

    user = await db.get(User, int(user_id))
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")

    set_auth_cookies(response, create_access_token(user.id), create_refresh_token(user.id))
    return {"msg": "已刷新"}
