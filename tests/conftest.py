import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.main import app

# 所有测试用户统一以该前缀开头，便于最后统一清理
TEST_USER_PREFIX = "test"


async def _delete_test_users() -> None:
    """删除所有测试用户（username 以 test 开头）"""
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(f"DELETE FROM users WHERE username LIKE '{TEST_USER_PREFIX}%'")
            )
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def client():
    """session 级测试客户端。

    全程共享一个 event loop，避免模块级 redis / engine 跨 loop 复用报
    ``Event loop is closed``。用 https 作为 base_url，使 Secure Cookie 能被发送。
    """
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_cookies(client):
    """每个测试前清空 cookie，保证测试之间独立"""
    client.cookies.clear()
    yield


@pytest.fixture(autouse=True)
def _cleanup_after_test():
    """每个测试后清理测试用户，保证数据隔离"""
    yield
    asyncio.run(_delete_test_users())


@pytest.fixture(scope="session", autouse=True)
def _final_cleanup():
    """会话结束时兜底清理所有测试用户（即使个别测试异常也保证不残留）"""
    yield
    asyncio.run(_delete_test_users())
