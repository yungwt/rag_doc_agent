from datetime import datetime, timedelta, timezone

import bcrypt
import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Request, Response, status
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.user import User


# ── Redis 连接 ──
# 从 Redis 取出来的数据自动转成 str，默认是 bytes
redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)


# ─── 密码工具 ────────────────────────────────────────────
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ─── JWT 工具 ────────────────────────────────────────────
def create_access_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def create_refresh_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": str(user_id), "exp": expire, "type": "refresh"}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def _decode_token(token: str) -> dict | None:
    """底层解码，失败返回 None（供内部判断过期/续期用）"""
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    except JWTError:
        return None


def decode_token(token: str) -> dict:
    """解析 token，出错统一抛 401"""
    payload = _decode_token(token)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的认证凭据")
    return payload


# ─── 黑名单（登出 / 强制下线）────────────────────────────
async def blacklist_token(token: str, expire_seconds: int):
    """将 token 加入 Redis 黑名单，过期时间跟随 token 剩余有效期"""
    await redis.setex(f"blacklist:{token}", expire_seconds, "1")


async def is_token_blacklisted(token: str) -> bool:
    return await redis.exists(f"blacklist:{token}") > 0


# ─── Cookie 设置 / 清除 ────────────────────────────────────
def set_auth_cookies(response: Response, access_token: str, refresh_token: str | None = None) -> None:
    """登录/刷新成功后把 token 写入 httpOnly Cookie"""
    response.set_cookie(
        key=settings.COOKIE_ACCESS_NAME,
        value=access_token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        path="/",
    )
    if refresh_token:
        response.set_cookie(
            key=settings.COOKIE_REFRESH_NAME,
            value=refresh_token,
            max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite=settings.COOKIE_SAMESITE,
            path="/",  # 需随所有请求发送，供 get_current_user 自动续期
        )


def clear_auth_cookies(response: Response) -> None:
    """登出时清除 Cookie（path 必须与 set 时一致）"""
    response.delete_cookie(settings.COOKIE_ACCESS_NAME, path="/")
    response.delete_cookie(settings.COOKIE_REFRESH_NAME, path="/")


# ─── 获取当前用户（FastAPI 依赖）──────────────────────────
async def _load_user(db: AsyncSession, payload: dict) -> User:
    """按 payload 里的 sub 查用户，缺失或不存在抛 401"""
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的认证凭据")
    result = await db.get(User, int(user_id))
    if not result:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    return result


async def get_current_user(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """优先从 Cookie 取 access_token；过期则用 refresh_token 自动续期"""
    access_token = request.cookies.get(settings.COOKIE_ACCESS_NAME)

    # 回退到 Authorization header（Swagger / 非浏览器客户端）
    if not access_token:
        auth = request.headers.get("Authorization")
        if auth and auth.lower().startswith("bearer "):
            access_token = auth[7:].strip()

    # access_token 仍有效 → 正常放行
    if access_token:
        payload = _decode_token(access_token)
        if payload is not None:
            if await is_token_blacklisted(access_token):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="凭据已失效，请重新登录")
            return await _load_user(db, payload)

    # access_token 过期/缺失 → 用 refresh_token 自动续期
    refresh_token = request.cookies.get(settings.COOKIE_REFRESH_NAME)
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")

    refresh_payload = _decode_token(refresh_token)
    if refresh_payload is None or refresh_payload.get("type") != "refresh":
        clear_auth_cookies(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期，请重新登录")
    if await is_token_blacklisted(refresh_token):
        clear_auth_cookies(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效，请重新登录")

    user = await _load_user(db, refresh_payload)

    # 续期：只刷新 access_token，refresh_token 保持不变
    set_auth_cookies(response, create_access_token(user.id))
    return user
