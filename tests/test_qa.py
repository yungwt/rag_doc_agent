# tests/test_qa.py
import time
import uuid

import pytest

# 注意：qa 是整个项目的最后一步，这里不再 mock 嵌入 / LLM 的响应，
# 而是真实走通 注册→登录→上传→向量化→建会话→提问→检索→生成 的完整链路。


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
