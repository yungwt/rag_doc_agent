import uuid

import pytest


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


@pytest.mark.auth
def test_register_success(client):
    resp, username, email = _register(client)
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == username
    assert data["email"] == email
    assert data["id"] > 0
    assert data["is_active"] is True


@pytest.mark.auth
def test_register_duplicate_username(client):
    _, username, _ = _register(client)
    resp, _, _ = _register(client, username=username)  # 同名注册
    assert resp.status_code == 409
    

@pytest.mark.auth
def test_register_duplicate_email(client):
    _, _, email = _register(client)
    resp = client.post("/api/auth/register", json={
        "username": _unique_username(),  # 不同用户名
        "email": email,                  # 同邮箱
        "password": "123456",
    })
    assert resp.status_code == 409


@pytest.mark.auth
def test_login_success(client):
    _, username, _ = _register(client)
    resp = _login(client, username)
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == username
    # token 只写入 httpOnly Cookie，不应出现在响应体
    assert "access_token" not in data
    assert "refresh_token" not in data
    assert "access_token" in resp.cookies
    assert "refresh_token" in resp.cookies


@pytest.mark.auth
def test_login_wrong_password(client):
    _, username, _ = _register(client)
    resp = _login(client, username, password="wrong")
    assert resp.status_code == 401


@pytest.mark.auth
def test_login_nonexistent_user(client):
    resp = _login(client, _unique_username())
    assert resp.status_code == 401


@pytest.mark.auth
def test_authenticated_route_with_cookie(client):
    """登录后 Cookie 自动携带，访问受保护接口成功"""
    _, username, _ = _register(client)
    _login(client, username)
    resp = client.get("/api/sessions/")
    assert resp.status_code == 200

@pytest.mark.auth
def test_authenticated_route_without_cookie(client):
    resp = client.get("/api/sessions/")
    assert resp.status_code == 401


@pytest.mark.auth
def test_logout(client):
    _, username, _ = _register(client)
    _login(client, username)
    resp = client.post("/api/auth/logout")
    assert resp.status_code == 200
    assert resp.json()["msg"] == "已登出"
    resp = client.get("/api/sessions/")
    assert resp.status_code == 401


@pytest.mark.auth
def test_refresh_success(client):
    _, username, _ = _register(client)
    _login(client, username)
    resp = client.post("/api/auth/refresh")
    assert resp.status_code == 200
    assert resp.json()["msg"] == "已刷新"
    assert "access_token" in resp.cookies
    resp = client.get("/api/sessions/")
    assert resp.status_code == 200  # 刷新后新 access_token 生效，访问受保护资源成功
        

@pytest.mark.auth
def test_refresh_without_token(client):
    resp = client.post("/api/auth/refresh")
    assert resp.status_code == 401,'无token拒绝刷新token'


@pytest.mark.auth
def test_refresh_after_logout_fails(client):
    _, username, _ = _register(client)
    _login(client, username)
    client.post("/api/auth/logout")
    resp = client.post("/api/auth/refresh")
    assert resp.status_code == 401,'登出后拒绝刷新token'

@pytest.mark.auth
def test_refresh_with_access_token_fails(client):
    """用 access_token 刷新应失败"""
    _, username, _ = _register(client)
    login_resp = _login(client, username)
    access_token = login_resp.cookies.get("access_token")
    
    # 手动构造请求，用 access_token 当 refresh_token
    resp = client.post("/api/auth/refresh", json={"refresh_token": access_token})
    assert resp.status_code == 401
    assert "无效的刷新令牌" in resp.json()["detail"]

@pytest.mark.auth
def test_refresh_with_random_token_fails(client):
    """用随机字符串刷新应失败"""
    resp = client.post("/api/auth/refresh", json={"refresh_token": "random_string"})
    assert resp.status_code == 401

@pytest.mark.auth
def test_blacklisted_token_cannot_access(client):
    """登出后旧 token 不能访问"""
    _, username, _ = _register(client)
    _login(client, username)
    client.post("/api/auth/logout")
    resp = client.get("/api/sessions/")
    assert resp.status_code == 401
