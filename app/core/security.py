import uuid
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
# jti 让每个令牌字符串唯一：exp 只精确到秒，同一秒内为同一用户签发会得到完全
# 相同的 JWT，轮换时「拉黑旧令牌」会把刚签发的新令牌一起拉黑（新 Cookie 一出生即失效）。
def create_access_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "exp": expire, "type": "access", "jti": uuid.uuid4().hex}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def create_refresh_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": str(user_id), "exp": expire, "type": "refresh", "jti": uuid.uuid4().hex}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def _decode_token(token: str) -> dict | None:
    """底层解码，失败返回 None（供内部判断过期/续期用）

    强制要求 exp：JWT 的 exp 是可选的，缺了就等于一张永久凭证。
    """
    try:
        return jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=["HS256"],
            options={"require_exp": True},
        )
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
# refresh Cookie 只在刷新端点需要被读到，收窄 path 后不再跟着每个业务请求发送
REFRESH_COOKIE_PATH = "/api/auth"


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
            path=REFRESH_COOKIE_PATH,
        )


def clear_auth_cookies(response: Response) -> None:
    """登出时清除 Cookie（path 必须与 set 时一致，否则浏览器匹配不到、删不掉）"""
    response.delete_cookie(settings.COOKIE_ACCESS_NAME, path="/")
    response.delete_cookie(settings.COOKIE_REFRESH_NAME, path=REFRESH_COOKIE_PATH)


# ─── 获取当前用户（FastAPI 依赖）──────────────────────────
async def _load_user(db: AsyncSession, payload: dict) -> User:
    """按 payload 里的 sub 查用户，缺失/不存在/已禁用一律抛 401"""
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的认证凭据")
    result = await db.get(User, int(user_id))
    if not result:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    # 校验状态，否则禁用账号后已发出的 token 仍能一直用。
    # 用 401 而非 403：语义是"当前凭据不再有效"，前端据此跳登录页
    if not result.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号已被禁用")
    return result


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """取 access_token 校验后返回用户；拿不到就直接 401

    只认 access_token。refresh Cookie 收窄在 /api/auth 下发送，业务请求读不到，
    续期由前端显式调用 /api/auth/refresh 完成。
    """
    access_token = request.cookies.get(settings.COOKIE_ACCESS_NAME)

    # 回退到 Authorization header（Swagger / 非浏览器客户端）
    if not access_token:
        auth = request.headers.get("Authorization")
        if auth and auth.lower().startswith("bearer "):
            access_token = auth[7:].strip()

    if not access_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")

    # 必须校验 type，否则 refresh_token 能直接当通行证打所有业务接口
    payload = _decode_token(access_token)
    if payload is None or payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期，请重新登录")
    if await is_token_blacklisted(access_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="凭据已失效，请重新登录")

    return await _load_user(db, payload)
