import asyncio
from unittest.mock import Mock, patch, AsyncMock
import shutil
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
import chromadb
from app.core.config import settings,BASE_DIR
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
    # 1. 删除数据库数据
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.begin() as conn:
            # 只需删用户，其他自动级联
            await conn.execute(text("DELETE FROM users WHERE username LIKE 'test%'"))
    finally:
        await engine.dispose()

     # 2. 删除测试上传的文件
    upload_dir = Path(BASE_DIR / "uploads")
    if upload_dir.exists():
        for file in upload_dir.iterdir():
            if file.is_file():
                file.unlink()
    
    # 3. 删除测试 Chroma 数据（物理删除整个向量库文件夹）
    # 删文件前先清空 chromadb 进程级缓存的连接，否则缓存的连接仍指向
    # 已删除的 sqlite 文件，后续写入会报 "attempt to write a readonly database"。
    chroma_dir = Path(settings.CHROMA_PERSIST_DIR)
    try:
        chroma_client = chromadb.PersistentClient(path=str(chroma_dir))
        chroma_client.clear_system_cache()
    except Exception as e:
        print(f"⚠️ Chroma 客户端缓存清理失败: {e}")
    if chroma_dir.exists():
        shutil.rmtree(chroma_dir)

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
