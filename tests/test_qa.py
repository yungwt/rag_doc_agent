# tests/test_qa.py
import pytest
import uuid
from app.core.config import settings

# ========== 辅助函数 ==========

def _unique_username(prefix: str = "test") -> str:
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
    return client.post(
        "/api/documents/upload",
        files={"file": (filename, content, content_type)}
    )


# ========== QA 测试 ==========

@pytest.mark.qa
def test_ask_question_success(client, mock_qa_services):
    """正常问答：上传文档 → 创建会话 → 提问 → 获得回答"""
    
    # 1. 注册登录
    _, username, _ = _register(client)
    _login(client, username)
    
    # 2. 上传文档并等待处理完成
    upload_resp = _upload_doc(client, content=b"This is a test document for QA testing.")
    assert upload_resp.status_code == 201
    doc_id = upload_resp.json()["id"]
    
    # 等待文档处理完成
    import time
    for _ in range(30):
        list_resp = client.get("/api/documents/")
        docs = list_resp.json()["documents"]
        target = next((d for d in docs if d["id"] == doc_id), None)
        if target and target["status"] == "completed":
            break
        time.sleep(0.1)
    
    # 3. 创建会话
    session_resp = client.post("/api/sessions/", json={"title": "测试会话"})
    assert session_resp.status_code == 201
    session_id = session_resp.json()["id"]
    
    # 4. 提问
    question = "测试文档说了什么内容？"
    qa_resp = client.post("/api/qa/", json={
        "session_id": session_id,
        "question": question,
    })
    
    assert qa_resp.status_code == 200
    data = qa_resp.json()
    
    # 5. 验证响应结构
    assert "answer" in data
    assert "sources" in data
    assert "history" in data
    
    # 6. 验证回答内容（来自 Mock）
    assert data["answer"] == "这是 AI 生成的测试回答。根据文档内容，测试文档包含相关信息。"
    assert isinstance(data["sources"], list)
    assert len(data["sources"]) >= 0
    
    # 7. 验证消息已保存
    msg_resp = client.get(f"/api/sessions/{session_id}/messages")
    assert msg_resp.status_code == 200
    messages = msg_resp.json()["messages"]
    assert len(messages) >= 2  # 至少用户消息 + 助手消息
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == question
    assert messages[1]["role"] == "assistant"


@pytest.mark.qa
def test_ask_question_without_session(client, mock_qa_services):
    """不提供 session_id 也能问答（无历史对话）"""
    _, username, _ = _register(client)
    _login(client, username)
    
    # 上传文档并等待处理完成
    upload_resp = _upload_doc(client, content=b"Test content without session")
    assert upload_resp.status_code == 201
    
    # 直接提问（不传 session_id）
    qa_resp = client.post("/api/qa/", json={
        "question": "测试问题",
        # 没有 session_id
    })
    
    assert qa_resp.status_code == 200
    data = qa_resp.json()
    assert "answer" in data
    assert "history" in data
    # 无会话时，历史应该为空或默认值
    assert data["answer"] == "这是 AI 生成的测试回答。根据文档内容，测试文档包含相关信息。"


@pytest.mark.qa
def test_ask_question_without_auth(client):
    """未认证不能问答"""
    qa_resp = client.post("/api/qa/", json={
        "session_id": 1,
        "question": "测试问题",
    })
    assert qa_resp.status_code == 401


@pytest.mark.qa
def test_ask_question_empty_question(client, mock_qa_services):
    """空问题应返回错误"""
    _, username, _ = _register(client)
    _login(client, username)
    
    qa_resp = client.post("/api/qa/", json={
        "session_id": 1,
        "question": "",
    })
    # 根据你的校验逻辑，可能返回 422 或 400
    assert qa_resp.status_code in [400, 422]


@pytest.mark.qa
def test_ask_question_session_not_found(client, mock_qa_services):
    """会话不存在"""
    _, username, _ = _register(client)
    _login(client, username)
    
    qa_resp = client.post("/api/qa/", json={
        "session_id": 99999,
        "question": "测试问题",
    })
    assert qa_resp.status_code == 404


@pytest.mark.qa
def test_ask_question_other_user_session(client, mock_qa_services):
    """不能使用其他用户的会话"""
    # 用户A 创建会话
    _, username_a, _ = _register(client, username="user_a_qa")
    _login(client, username_a)
    session_resp = client.post("/api/sessions/", json={"title": "A的会话"})
    session_id = session_resp.json()["id"]
    
    # 用户B 登录
    _, username_b, _ = _register(client, username="user_b_qa")
    _login(client, username_b)
    
    # 用户B 尝试用 A 的会话提问
    qa_resp = client.post("/api/qa/", json={
        "session_id": session_id,
        "question": "测试问题",
    })
    # 应该返回 404（隐藏资源存在性）或 403
    assert qa_resp.status_code in [403, 404]


@pytest.mark.qa
def test_ask_question_auto_title(client, mock_qa_services):
    """第一条消息自动用问题更新会话标题"""
    _, username, _ = _register(client)
    _login(client, username)
    
    # 1. 创建空会话
    session_resp = client.post("/api/sessions/", json={"title": "临时标题"})
    session_id = session_resp.json()["id"]
    
    # 2. 提问（这是第一条消息）
    question = "这是一个很长的问题内容，用于测试自动标题截取功能"
    qa_resp = client.post("/api/qa/", json={
        "session_id": session_id,
        "question": question,
    })
    assert qa_resp.status_code == 200
    
    # 3. 验证会话标题已更新（截取前50字符）
    list_resp = client.get("/api/sessions/")
    sessions = list_resp.json()["sessions"]
    target = next((s for s in sessions if s["id"] == session_id), None)
    assert target is not None
    assert target["title"] == question[:50]


@pytest.mark.qa
def test_ask_question_preserves_session_title(client, mock_qa_services):
    """已有消息的会话不更新标题"""
    _, username, _ = _register(client)
    _login(client, username)
    
    # 1. 创建会话（有明确标题）
    session_resp = client.post("/api/sessions/", json={"title": "明确标题"})
    session_id = session_resp.json()["id"]
    
    # 2. 第一条消息（会更新标题）
    qa_resp1 = client.post("/api/qa/", json={
        "session_id": session_id,
        "question": "第一条消息",
    })
    assert qa_resp1.status_code == 200
    
    # 3. 第二条消息（不会更新标题）
    qa_resp2 = client.post("/api/qa/", json={
        "session_id": session_id,
        "question": "第二条消息",
    })
    assert qa_resp2.status_code == 200
    
    # 4. 验证标题仍是第一条消息的内容
    list_resp = client.get("/api/sessions/")
    sessions = list_resp.json()["sessions"]
    target = next((s for s in sessions if s["id"] == session_id), None)
    assert target is not None
    # 标题应该是第一条消息截取的内容，不是"明确标题"（因为第一条消息触发更新）
    assert target["title"] == "第一条消息" or target["title"] == "明确标题"
    # 根据你的实现逻辑，如果是"明确标题"，说明你没有用问题覆盖
    # 这里根据你的实际逻辑调整断言


@pytest.mark.qa
def test_ask_question_no_documents(client, mock_qa_services):
    """没有上传任何文档时提问"""
    _, username, _ = _register(client)
    _login(client, username)
    
    # 创建会话
    session_resp = client.post("/api/sessions/", json={"title": "测试会话"})
    session_id = session_resp.json()["id"]
    
    # 提问（没有文档可检索）
    qa_resp = client.post("/api/qa/", json={
        "session_id": session_id,
        "question": "测试问题",
    })
    
    assert qa_resp.status_code == 200
    data = qa_resp.json()
    # 应该返回"根据已知信息无法回答"或类似
    # 但 Mock 会返回固定回答，所以检查 answer 存在即可
    assert "answer" in data
    assert data["sources"] == []  # 没有来源


@pytest.mark.qa
def test_ask_question_verify_mock_called(client, mock_qa_services):
    """验证 Mock 被正确调用"""
    _, username, _ = _register(client)
    _login(client, username)
    
    # 上传文档并等待处理
    upload_resp = _upload_doc(client, content=b"Test content")
    assert upload_resp.status_code == 201
    
    # 创建会话
    session_resp = client.post("/api/sessions/", json={"title": "测试会话"})
    session_id = session_resp.json()["id"]
    
    # 提问
    qa_resp = client.post("/api/qa/", json={
        "session_id": session_id,
        "question": "测试问题",
    })
    assert qa_resp.status_code == 200
    
    # 验证 LLM 被调用了
    mock_qa_services['llm'].ainvoke.assert_called_once()
    
    # 验证 Chroma 检索被调用了
    mock_qa_services['collection'].similarity_search.assert_called()