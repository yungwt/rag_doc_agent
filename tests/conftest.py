import asyncio
from unittest.mock import Mock, patch, AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.main import app

TEST_PREFIX = "test"



@pytest.fixture()
def mock_embeddings_only():
    """
    只 Mock embeddings（向量模型）
    文档操作只需要向量化功能
    """
    
    # Mock embeddings
    mock_embeddings = Mock()
    # embed_documents 接受文本列表，返回向量列表
    mock_embeddings.embed_documents.return_value = [
        [0.1] * 384 for _ in range(10)  # 假设维度384
    ]
    mock_embeddings.embed_query.return_value = [0.1] * 384
    
    # 只 patch embeddings
    with patch('app.services.rag_service.embeddings', mock_embeddings):
        yield mock_embeddings  # 返回 mock 对象，方便验证


async def _delete_test_data() -> None:
    """删除所有测试数据"""
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.begin() as conn:
            # 只需删用户，其他自动级联
            await conn.execute(text("DELETE FROM users WHERE username LIKE 'test%'"))
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
    asyncio.run(_delete_test_data())


@pytest.fixture(scope="session", autouse=True)
def _final_cleanup():
    """会话结束时兜底清理所有测试（即使个别测试异常也保证不残留）"""
    yield
    asyncio.run(_delete_test_data())
