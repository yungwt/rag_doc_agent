# tests/test_qa.py
import time
import uuid

import pytest

# 注意：qa 是整个项目的最后一步。分两类用例：
#   1. @pytest.mark.llm —— 真实走通完整链路并验证模型输出（消耗 API 额度，
#      默认被 pytest.ini 的 -m "not llm" 跳过，用 python test.py -m llm 运行）
#   2. mock 链路用例 —— Mock 掉 LLM/Embeddings，只验证链路本身（消息落库、
#      来源返回、失败回滚、prompt 组装等），零 API 消耗，默认全跑


# ========== 辅助函数（复用） ==========
def _unique_username(prefix: str = "test") -> str:
    """生成 test 开头的唯一用户名，便于清理"""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _register(client, username=None, email=None, password="123456"):
    username = username or _unique_username()
    email = email or f"{username}@example.com"
    resp = client.post("/api/auth/register", json={
        "username": username,
        "email": email,
        "password": password,
    })
    return resp, username, email


def _login(client, username, password="123456"):
    return client.post("/api/auth/login", json={
        "username": username,
        "password": password,
    })


def _upload_doc(client, filename="test.txt", content=b"test content", content_type="text/plain"):
    """辅助：上传文档"""
    return client.post(
        "/api/documents/upload",
        files={"file": (filename, content, content_type)},
    )


def _wait_document_ready(client, doc_id: int, timeout: float = 60.0) -> dict:
    """等待文档异步处理完成（真实向量化，可能较慢），返回最终文档信息"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        docs = client.get("/api/documents/").json()["documents"]
        target = next((d for d in docs if d["id"] == doc_id), None)
        if target and target["status"] in ("completed", "failed"):
            return target
        time.sleep(0.2)
    raise TimeoutError(f"文档 {doc_id} 在 {timeout}s 内未处理完成")


def _setup_full_flow(client, content: bytes, filename: str = "test.txt") -> tuple[int, dict]:
    """完整前置链路：注册→登录→上传→等待处理完成→建会话。返回 (session_id, 文档信息)"""
    _, username, _ = _register(client)
    _login(client, username)

    upload_resp = _upload_doc(client, filename=filename, content=content)
    assert upload_resp.status_code == 201
    doc_id = upload_resp.json()["id"]

    doc = _wait_document_ready(client, doc_id)
    assert doc["status"] == "completed", f"文档处理失败: {doc['status']}"
    assert doc["chunk_count"] > 0, "文档处理完成但切片数为 0"

    create_resp = client.post("/api/sessions/", json={"title": "新对话"})
    assert create_resp.status_code == 201
    session_id = create_resp.json()["id"]

    return session_id, doc


# ========== 完整流程测试 ==========

@pytest.mark.qa
@pytest.mark.llm
def test_qa_full_flow(client):
    """完整链路：注册→上传→处理→建会话→提问→检索生成→验证答案/来源/消息/标题"""
    content = (
        "北京是中国的首都。\n"
        "Python 编程语言的创始人是 Guido van Rossum。\n"
        "珠穆朗玛峰是世界最高峰。\n"
    ).encode()

    session_id, _ = _setup_full_flow(client, content)

    question = "Python 的创始人是谁？"
    resp = client.post("/api/qa/", json={"question": question, "session_id": session_id})
    assert resp.status_code == 200
    data = resp.json()

    # 答案非空且基于检索内容作答
    assert "answer" in data and isinstance(data["answer"], str) and data["answer"]
    assert "guido" in data["answer"].lower() or "rossum" in data["answer"].lower(), \
        f"答案未命中检索内容: {data['answer']}"

    # 来源非空，且字段完整
    assert "sources" in data and len(data["sources"]) > 0, "RAG 未检索到任何来源"
    src = data["sources"][0]
    for key in ("document_id", "title", "chunk_index", "content"):
        assert key in src, f"来源缺少字段 {key}"
    assert src["title"] == "test.txt"

    # 用户消息 + 助手消息已持久化
    msgs = client.get(f"/api/sessions/{session_id}/messages").json()["messages"]
    assert len(msgs) == 2
    assert {m["role"] for m in msgs} == {"user", "assistant"}

    # 第一条消息自动用问题内容更新会话标题
    sessions = client.get("/api/sessions/").json()["sessions"]
    session = next(s for s in sessions if s["id"] == session_id)
    assert session["title"] == question


@pytest.mark.qa
@pytest.mark.llm
def test_qa_multi_turn_conversation(client):
    """多轮对话：历史被保留，标题仅在首条消息时更新"""
    content = (
        "Python 编程语言的创始人是 Guido van Rossum。\n"
        "珠穆朗玛峰是世界最高峰，海拔 8848 米。\n"
    ).encode()

    session_id, _ = _setup_full_flow(client, content)

    q1 = "Python 的创始人是谁？"
    r1 = client.post("/api/qa/", json={"question": q1, "session_id": session_id})
    assert r1.status_code == 200
    assert "guido" in r1.json()["answer"].lower() or "rossum" in r1.json()["answer"].lower()

    q2 = "世界最高峰是哪座山？"
    r2 = client.post("/api/qa/", json={"question": q2, "session_id": session_id})
    assert r2.status_code == 200
    assert "珠穆朗玛" in r2.json()["answer"] or "珠峰" in r2.json()["answer"], \
        f"第二问未命中检索内容: {r2.json()['answer']}"

    # 两条用户消息 + 两条助手消息
    msgs = client.get(f"/api/sessions/{session_id}/messages").json()["messages"]
    assert len(msgs) == 4

    # 标题保持首条问题不变
    sessions = client.get("/api/sessions/").json()["sessions"]
    session = next(s for s in sessions if s["id"] == session_id)
    assert session["title"] == q1


@pytest.mark.qa
@pytest.mark.llm
def test_qa_ask_without_documents(client):
    """未上传文档时提问：仍有回答，但来源为空"""
    _, username, _ = _register(client)
    _login(client, username)

    create_resp = client.post("/api/sessions/", json={"title": "新对话"})
    session_id = create_resp.json()["id"]

    resp = client.post("/api/qa/", json={"question": "今天天气怎么样？", "session_id": session_id})
    assert resp.status_code == 200
    data = resp.json()
    assert "answer" in data and data["answer"]
    assert data["sources"] == []


@pytest.mark.qa
@pytest.mark.llm
def test_qa_session_title_truncated(client):
    """超长问题：会话标题截取前 50 字"""
    _, username, _ = _register(client)
    _login(client, username)

    create_resp = client.post("/api/sessions/", json={"title": "新对话"})
    session_id = create_resp.json()["id"]

    long_question = "这是一个非常长的用于测试标题截断的问题" * 3  # 超过 50 字
    resp = client.post("/api/qa/", json={"question": long_question, "session_id": session_id})
    assert resp.status_code == 200

    sessions = client.get("/api/sessions/").json()["sessions"]
    session = next(s for s in sessions if s["id"] == session_id)
    assert session["title"] == long_question[:50]


# ========== 边界 / 异常测试 ==========

@pytest.mark.qa
def test_qa_without_auth(client):
    """未认证不能提问"""
    resp = client.post("/api/qa/", json={"question": "测试", "session_id": 1})
    assert resp.status_code == 401


@pytest.mark.qa
def test_qa_invalid_payload(client):
    """缺少必填字段返回 422"""
    _, username, _ = _register(client)
    _login(client, username)

    # 缺少 session_id
    resp = client.post("/api/qa/", json={"question": "测试"})
    assert resp.status_code == 422


# ========== 安全漏洞测试（当前会失败，用于暴露问题） ==========

@pytest.mark.qa
@pytest.mark.llm
def test_qa_cross_user_session_access(client):
    """
    跨用户会话访问 
    """
    # 用户A 准备
    _, username_a, _ = _register(client)
    _login(client, username_a)
    
    content = "用户A的敏感数据".encode('utf-8')
    upload_resp = _upload_doc(client, filename="A_data.txt", content=content)
    assert upload_resp.status_code == 201
    doc_id = upload_resp.json()["id"]
    _wait_document_ready(client, doc_id)
    
    create_resp = client.post("/api/sessions/", json={"title": "A的会话"})
    session_id = create_resp.json()["id"]
    
    # 用户A 提问
    client.post("/api/qa/", json={
        "session_id": session_id,
        "question": "用户A的内容是什么？",
    })
    
    # 用户B 登录
    _, username_b, _ = _register(client)
    _login(client, username_b)
    
    # 用户B 尝试访问 A 的会话（安全漏洞）
    resp = client.post("/api/qa/", json={
        "session_id": session_id,
        "question": "用户A的敏感数据是什么？",
    })
    
    # 安全预期：拒绝访问
    assert resp.status_code in [403, 404], \
        f"安全漏洞：跨用户会话访问成功，返回 {resp.status_code}"


@pytest.mark.qa
def test_qa_session_not_exists(client):
    """
    访问不存在的会话 
    """
    _, username, _ = _register(client)
    _login(client, username)
    
    resp = client.post("/api/qa/", json={
        "session_id": 99999,
        "question": "测试问题",
    })
    
    assert resp.status_code == 404, \
        f"不存在的会话应该返回404，实际返回 {resp.status_code}"


# ========== Mock 链路测试（零 API 消耗，验证链路本身而非模型输出） ==========

MOCK_ANSWER = "【模拟回答】这是测试环境的固定回复。"


@pytest.mark.qa
def test_qa_mock_full_pipeline(client, mock_models):
    """Mock 模型验证完整链路：上传→向量化→建会话→提问→消息落库→来源返回"""
    content = "机器学习是人工智能的一个分支。\n深度学习依赖多层神经网络。\n".encode()

    session_id, doc = _setup_full_flow(client, content)
    assert doc["status"] == "completed" and doc["chunk_count"] > 0

    resp = client.post("/api/qa/", json={"question": "什么是机器学习？", "session_id": session_id})
    assert resp.status_code == 200
    data = resp.json()

    # 答案来自 mock LLM → 说明 检索→prompt组装→LLM调用→响应 整条链路打通
    assert data["answer"] == MOCK_ANSWER
    # mock 向量全一致（相关性 1.0）→ 全部通过阈值，来源非空且字段完整
    assert len(data["sources"]) > 0
    for key in ("document_id", "title", "chunk_index", "content"):
        assert key in data["sources"][0]

    # 用户消息 + 助手消息已持久化，首问已覆盖标题
    msgs_resp = client.get(f"/api/sessions/{session_id}/messages?limit=1")
    # total 是会话消息总数（不受 limit 影响），limit=1 也应报 2 —— 回归：total 曾谎报为 len(messages)
    assert msgs_resp.json()["total"] == 2
    assert len(msgs_resp.json()["messages"]) == 1
    msgs = client.get(f"/api/sessions/{session_id}/messages").json()["messages"]
    assert len(msgs) == 2
    assert {m["role"] for m in msgs} == {"user", "assistant"}


@pytest.mark.qa
def test_qa_mock_ask_without_documents(client, mock_models):
    """Mock 模型：未上传文档时提问，回答正常、来源为空"""
    _, username, _ = _register(client)
    _login(client, username)
    session_id = client.post("/api/sessions/", json={"title": "新对话"}).json()["id"]

    resp = client.post("/api/qa/", json={"question": "今天天气怎么样？", "session_id": session_id})
    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"] == MOCK_ANSWER
    assert data["sources"] == []


@pytest.mark.qa
def test_qa_mock_failure_rolls_back_user_message(client, mock_embeddings_only):
    """生成失败（模型侧错误）返回 503，且刚落的用户消息被回滚——重试不会产生重复提问"""
    import httpx
    from unittest.mock import patch
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    from openai import APIError

    class _ExplodingLLM(FakeListChatModel):
        def __init__(self):
            super().__init__(responses=["不应被用到"])

        def _call(self, messages, stop=None, run_manager=None, **kwargs):
            raise APIError("模拟模型服务故障",
                           request=httpx.Request("POST", "http://mock"), body=None)

    session_id, _ = _setup_full_flow(client, "测试内容".encode())

    with patch("app.services.rag_service.llm", _ExplodingLLM()):
        resp = client.post("/api/qa/", json={"question": "会失败的问题", "session_id": session_id})
    assert resp.status_code == 503
    assert "模型服务" in resp.json()["detail"]

    # 失败后用户消息已回滚，历史里不会留下半截提问
    msgs = client.get(f"/api/sessions/{session_id}/messages").json()["messages"]
    assert len(msgs) == 0, f"失败后应回滚用户消息，实际残留 {len(msgs)} 条"


@pytest.mark.qa
def test_qa_mock_history_excludes_current_question(client, mock_embeddings_only, mock_llm):
    """组装历史时剔除刚存的当前问题（回归：发给 LLM 的历史不含刚问的这句话本身）"""
    session_id, _ = _setup_full_flow(client, "知识内容".encode())

    q1 = "第一个问题是什么？"
    q2 = "第二个问题是什么？"
    assert client.post("/api/qa/", json={"question": q1, "session_id": session_id}).status_code == 200
    assert client.post("/api/qa/", json={"question": q2, "session_id": session_id}).status_code == 200

    # 第二次调用收到的 prompt：当前问题只出现 1 次（问题行），历史里没有重复
    prompt_text = "\n".join(str(m.content) for m in mock_llm.prompts_seen[-1])
    assert prompt_text.count(q2) == 1, "当前问题在 prompt 中出现多次（历史未剔除）"
    assert q1 in prompt_text, "上一轮对话历史丢失"


@pytest.mark.qa
def test_retrieve_chunks_threshold_filter(monkeypatch):
    """低于 RELEVANCE_MIN_SCORE 的切片被丢弃（l2 距离按 cos = 1 - d²/2 换算）"""
    import asyncio
    from types import SimpleNamespace

    from app.services import rag_service

    def make_doc(i):
        return SimpleNamespace(
            page_content=f"chunk{i}",
            metadata={"document_id": "1", "chunk_index": i},
        )

    class FakeStore:
        def similarity_search_with_score(self, question, k):
            # d=0.6 → cos≈0.82 保留；d=1.4 → cos≈0.02 丢弃；d=1.0 → cos=0.5 保留
            return [(make_doc(0), 0.6), (make_doc(1), 1.4), (make_doc(2), 1.0)]

    monkeypatch.setattr(rag_service, "Chroma", lambda **kwargs: FakeStore())
    chunks = asyncio.run(rag_service.retrieve_chunks(1, "任意问题", k=3))

    assert [c["chunk_index"] for c in chunks] == [0, 2]
