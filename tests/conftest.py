import asyncio
import os
from unittest.mock import Mock, patch
from urllib.parse import urlsplit, urlunsplit
import shutil
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
import chromadb

# ══════════════════════════════════════════════════════════════
# 物理隔离：以下环境变量必须在 import app 之前硬指定（不能用 setdefault，
# 容器/.env 里已有同名值），保证测试永远碰不到真实数据：
#   1. 独立测试库 rag_doc_agent_test（会话结束整个 DROP，真实库零写入）
#   2. Redis 走 db1（黑名单等键不进真实 db0）
#   3. 向量库 / 上传目录重定向到 tests/ 下的专属目录
# ══════════════════════════════════════════════════════════════
_TESTS_DIR = Path(__file__).resolve().parent
TEST_DB_NAME = "rag_doc_agent_test"

os.environ["MYSQL_DATABASE"] = TEST_DB_NAME

_parts = urlsplit(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
os.environ["REDIS_URL"] = urlunsplit((_parts.scheme, _parts.netloc, "/1", "", ""))

os.environ["CHROMA_PERSIST_DIR"] = str(_TESTS_DIR / ".chroma_test")
os.environ["UPLOAD_DIR"] = str(_TESTS_DIR / ".test_uploads")

from app.core.config import settings
from app.main import app

TEST_PREFIX = "test"

# 测试会话开始前的 uploads 文件名单（快照），清理时只删名单之外的新增文件
_baseline_uploads: set[str] = set()


# ════════════════════════ Mock fixtures ════════════════════════

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from pydantic import Field


class RecordingLLM(FakeListChatModel):
    """固定回复的可运行假 LLM，额外记录收到的 messages，供断言 prompt 内容"""

    # pydantic 模型：必须声明为字段，运行时动态挂属性会被拒
    prompts_seen: list = Field(default_factory=list)

    def __init__(self, responses):
        super().__init__(responses=responses)

    def _call(self, messages, stop=None, run_manager=None, **kwargs):
        self.prompts_seen.append(messages)
        return super()._call(messages, stop=stop, run_manager=run_manager, **kwargs)


class ExplodingLLM(FakeListChatModel):
    """调用即抛 openai.APIError 的假 LLM，用于验证生成失败时的回滚逻辑"""

    def __init__(self):
        super().__init__(responses=["不应被用到"])

    def _call(self, messages, stop=None, run_manager=None, **kwargs):
        import httpx
        from openai import APIError

        raise APIError("模拟模型服务故障", request=httpx.Request("POST", "http://mock"), body=None)


@pytest.fixture()
def mock_llm():
    """Mock LLM（链路验证用，不消耗 API 额度）。

    - 支持被 prompt | llm 组链、ainvoke 调用，固定回复「【模拟回答】…」
    - fake.prompts_seen 记录每次收到的 messages，可断言 prompt 组装逻辑
    """
    fake = RecordingLLM(responses=["【模拟回答】这是测试环境的固定回复。"])
    with patch("app.services.rag_service.llm", fake):
        yield fake


@pytest.fixture()
def mock_embeddings_only():
    """只 Mock embeddings（向量模型），文档操作只需要向量化功能"""
    mock_embeddings = Mock()
    mock_embeddings.embed_documents.return_value = [
        [0.1] * 384 for _ in range(10)
    ]
    mock_embeddings.embed_query.return_value = [0.1] * 384

    with patch('app.services.rag_service.embeddings', mock_embeddings):
        yield mock_embeddings


@pytest.fixture()
def mock_models(mock_embeddings_only, mock_llm):
    """同时 Mock embeddings + LLM：完整 QA 链路测试用，全程零 API 调用"""


# ════════════════════════ 数据库 / 清理 ════════════════════════

async def _create_test_db() -> None:
    """创建独立测试库并授权业务账号（用 root，密码来自 .env 的 MYSQL_ROOT_PASSWORD）"""
    import aiomysql

    conn = await aiomysql.connect(
        host=settings.MYSQL_HOST, port=settings.MYSQL_PORT,
        user="root", password=os.environ.get("MYSQL_ROOT_PASSWORD", ""),
        autocommit=True,
    )
    try:
        cur = await conn.cursor()
        await cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{TEST_DB_NAME}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        # IF NOT EXISTS：账号已存在时不影响原密码；不存在则补建
        await cur.execute(
            f"CREATE USER IF NOT EXISTS '{settings.MYSQL_USER}'@'%' "
            f"IDENTIFIED BY '{settings.MYSQL_PASSWORD}'"
        )
        await cur.execute(
            f"GRANT ALL PRIVILEGES ON `{TEST_DB_NAME}`.* TO '{settings.MYSQL_USER}'@'%'"
        )
        await cur.close()
    finally:
        conn.close()


async def _drop_test_db() -> None:
    import aiomysql

    conn = await aiomysql.connect(
        host=settings.MYSQL_HOST, port=settings.MYSQL_PORT,
        user="root", password=os.environ.get("MYSQL_ROOT_PASSWORD", ""),
        autocommit=True,
    )
    try:
        cur = await conn.cursor()
        await cur.execute(f"DROP DATABASE IF EXISTS `{TEST_DB_NAME}`")
        await cur.close()
    finally:
        conn.close()


async def _delete_test_data() -> None:
    """删除所有测试数据（只作用于测试库 / 测试专属目录）"""
    # 1. 删除测试库中的测试用户（其余数据级联删除）
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM users WHERE username LIKE 'test%'"))
    finally:
        await engine.dispose()

    # 2. 只删除测试期间新增的上传文件（快照之外的），真实文件永不触碰
    upload_dir = Path(settings.UPLOAD_DIR)
    if upload_dir.exists():
        for file in upload_dir.iterdir():
            if file.is_file() and file.name not in _baseline_uploads:
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
def _test_db():
    """会话开始创建独立测试库，结束整个 DROP——真实业务库自始至终零写入"""
    asyncio.run(_create_test_db())
    yield
    asyncio.run(_drop_test_db())


@pytest.fixture(scope="session")
def client(_test_db):
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
def _final_cleanup(client):
    """会话结束时兜底清理所有测试（即使个别测试异常也保证不残留）。

    显式依赖 client（间接依赖 _test_db）：保证终结顺序为
    先清理测试数据 → 再 DROP 测试库，避免清理打到已删除的库。
    """
    global _baseline_uploads
    # 测试开始前给 uploads 拍快照，之后清理只删快照之外的文件
    upload_dir = Path(settings.UPLOAD_DIR)
    if upload_dir.exists():
        _baseline_uploads = {f.name for f in upload_dir.iterdir() if f.is_file()}
    yield
    asyncio.run(_delete_test_data())
