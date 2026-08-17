# tests/test_sessions.py
import pytest
from app.core.config import settings
import uuid

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

@pytest.mark.session
def test_create_session_success(client):
    """正常创建会话"""
    _, username, _ = _register(client)
    _login(client, username)
    
    resp = client.post("/api/sessions/", json={"title": "测试会话"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "测试会话"
    assert data["user_id"] > 0
    assert "id" in data
    assert "creat_time" in data


@pytest.mark.session
def test_create_session_without_auth(client):
    """未认证不能创建会话"""
    resp = client.post("/api/sessions/", json={"title": "测试会话"})
    assert resp.status_code == 401


@pytest.mark.session
def test_create_session_empty_title(client):
    """空标题创建会话（根据业务逻辑，可能允许空标题或报错）"""
    _, username, _ = _register(client)
    _login(client, username)
    
    resp = client.post("/api/sessions/", json={"title": ""})
    # 根据你的业务逻辑，可能返回 201（允许空标题）或 422（校验失败）
    # 这里假设允许空标题
    assert resp.status_code in [201, 422]


@pytest.mark.session
def test_list_sessions_success(client):
    """正常列出会话"""
    _, username, _ = _register(client)
    _login(client, username)
    
    # 创建几个会话
    for i in range(3):
        client.post("/api/sessions/", json={"title": f"会话{i}"})
    
    resp = client.get("/api/sessions/")
    assert resp.status_code == 200
    data = resp.json()
    assert "sessions" in data
    assert "total" in data
    assert data["total"] >= 3
    assert len(data["sessions"]) >= 3


@pytest.mark.session
def test_list_sessions_pagination(client):
    """分页列出会话"""
    _, username, _ = _register(client)
    _login(client, username)
    
    for i in range(5):
        client.post("/api/sessions/", json={"title": f"会话{i}"})
    
    resp = client.get("/api/sessions/?skip=0&limit=2")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["sessions"]) == 2
    assert data["total"] == 5


@pytest.mark.session
def test_list_sessions_without_auth(client):
    """未认证不能列出会话"""
    resp = client.get("/api/sessions/")
    assert resp.status_code == 401


@pytest.mark.session
def test_list_sessions_other_user_not_visible(client):
    """用户只能看到自己的会话"""
    # 用户A 创建会话
    _, username_a, _ = _register(client)
    _login(client, username_a)
    client.post("/api/sessions/", json={"title": "A的会话"})
    client.post("/api/sessions/", json={"title": "A的会话2"})
    
    # 用户B 登录
    _, username_b, _ = _register(client, username="test_user_b", email="test_b@example.com")
    _login(client, username_b)
    
    resp = client.get("/api/sessions/")
    assert resp.status_code == 200
    data = resp.json()
    # 用户B 看不到 A 的会话
    assert data["total"] == 0


@pytest.mark.session
def test_list_messages_success(client):
    """正常列出消息"""
    _, username, _ = _register(client)
    _login(client, username)
    
    # 创建会话
    create_resp = client.post("/api/sessions/", json={"title": "测试会话"})
    session_id = create_resp.json()["id"]
    
    # 发送消息（假设有发消息接口，如果没有，直接测试空消息列表）
    resp = client.get(f"/api/sessions/{session_id}/messages")
    assert resp.status_code == 200
    data = resp.json()
    assert "messages" in data
    assert "total" in data


@pytest.mark.session
def test_list_messages_session_not_found(client):
    """消息所属会话不存在"""
    _, username, _ = _register(client)
    _login(client, username)
    
    resp = client.get("/api/sessions/99999/messages")
    assert resp.status_code == 404


@pytest.mark.session
def test_list_messages_other_user_session(client):
    """用户不能查看其他用户的会话消息"""
    # 用户A 创建会话
    _, username_a, _ = _register(client)
    _login(client, username_a)
    create_resp = client.post("/api/sessions/", json={"title": "A的会话"})
    session_id = create_resp.json()["id"]
    
    # 用户B 尝试查看
    _, username_b, _ = _register(client, username="test_user_b2", email="test_b2@example.com")
    _login(client, username_b)
    
    resp = client.get(f"/api/sessions/{session_id}/messages")
    assert resp.status_code == 404  # 或 404，取决于你的实现
    # 如果返回 404 也是合理的（隐藏资源存在性）


@pytest.mark.session
def test_list_messages_without_auth(client):
    """未认证不能查看消息"""
    resp = client.get("/api/sessions/1/messages")
    assert resp.status_code == 401


@pytest.mark.session
def test_delete_session_success(client):
    """正常删除会话"""
    _, username, _ = _register(client)
    _login(client, username)
    
    create_resp = client.post("/api/sessions/", json={"title": "待删除会话"})
    session_id = create_resp.json()["id"]
    
    resp = client.delete(f"/api/sessions/{session_id}")
    assert resp.status_code == 204
    
    # 验证会话已删除（通过列表查询）
    list_resp = client.get("/api/sessions/")
    assert list_resp.status_code == 200
    sessions = list_resp.json()["sessions"]
    assert all(s["id"] != session_id for s in sessions)


@pytest.mark.session
def test_delete_session_not_found(client):
    """删除不存在的会话"""
    _, username, _ = _register(client)
    _login(client, username)
    
    resp = client.delete("/api/sessions/99999")
    assert resp.status_code == 404


@pytest.mark.session
def test_delete_session_other_user(client):
    """用户不能删除其他用户的会话"""
    # 用户A 创建会话
    _, username_a, _ = _register(client)
    _login(client, username_a)
    create_resp = client.post("/api/sessions/", json={"title": "A的会话"})
    session_id = create_resp.json()["id"]
    
    # 用户B 尝试删除
    _, username_b, _ = _register(client, username="test_user_b3", email="test_b3@example.com")
    _login(client, username_b)
    
    resp = client.delete(f"/api/sessions/{session_id}")
    assert resp.status_code == 404  # 或 404


@pytest.mark.session
def test_delete_session_without_auth(client):
    """未认证不能删除会话"""
    resp = client.delete("/api/sessions/1")
    assert resp.status_code == 401


@pytest.mark.session
def test_session_ownership_isolation(client):
    """完整隔离测试：用户A的会话操作不影响用户B"""
    # 用户A 创建3个会话
    _, username_a, _ = _register(client)
    _login(client, username_a)
    for i in range(3):
        client.post("/api/sessions/", json={"title": f"A的会话{i}"})
    list_resp_a = client.get("/api/sessions/")
    total_a = list_resp_a.json()["total"]
    session_ids_a = [s["id"] for s in list_resp_a.json()["sessions"]]
    
    # 用户B 登录
    _, username_b, _ = _register(client, username="test_user_b4", email="test_b4@example.com")
    _login(client, username_b)
    
    # 用户B 只能看到自己的会话（0个）
    list_resp_b = client.get("/api/sessions/")
    assert list_resp_b.json()["total"] == 0
    
    # 用户B 尝试访问A的会话消息 → 失败
    resp = client.get(f"/api/sessions/{session_ids_a[0]}/messages")
    assert resp.status_code == 404
    
    # 用户B 尝试删除A的会话 → 失败
    resp = client.delete(f"/api/sessions/{session_ids_a[0]}")
    assert resp.status_code == 404
    
    # 用户A 的会话依然存在
    _login(client, username_a)
    resp = client.get("/api/sessions/")
    assert resp.json()["total"] == total_a