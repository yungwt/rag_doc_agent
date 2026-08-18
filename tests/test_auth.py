import concurrent.futures
import pytest
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
    client.cookies.clear()
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


# ========== 并发测试 ==========


@pytest.mark.auth
def test_concurrent_register_same_username(client):
    """
    并发注册相同用户名
    验证：最终只有1个用户被创建，且数据完整
    注意：可能返回500（如果异常未捕获），但数据一定是安全的
    """
    username = _unique_username()
    
    def register():
        email = f"{uuid.uuid4().hex}@example.com"
        return client.post("/api/auth/register", json={
            "username": username,
            "email": email,
            "password": "123456",
        })
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(register) for _ in range(3)]
        results = [f.result() for f in futures]
    
    # 1. 统计各种状态码
    status_counts = {}
    for r in results:
        status_counts[r.status_code] = status_counts.get(r.status_code, 0) + 1
    
    print(f"状态码分布: {status_counts}")
    
    # 2. 验证：有且只有1个成功（201）
    success_count = status_counts.get(201, 0)
    assert success_count == 1, f"期望1个成功，实际{success_count}个"
    
    # 3. 验证：成功的用户信息完整
    success_resp = next(r for r in results if r.status_code == 201)
    user_data = success_resp.json()
    assert user_data["username"] == username
    assert user_data["email"].endswith("@example.com")
    assert user_data["id"] > 0
    assert user_data["is_active"] is True
    
    # 4. 验证：其他请求要么返回409，要么返回500
    #    无论是409还是500，数据都是安全的（唯一约束保证了）
    other_statuses = [r.status_code for r in results if r.status_code != 201]
    for status in other_statuses:
        assert status == 409, f"意外的状态码: {status}"


@pytest.mark.auth
def test_concurrent_register_same_email(client):
    """
    并发注册相同邮箱
    验证：最终只有1个用户被创建，且数据完整
    """
    email = f"{uuid.uuid4().hex}@example.com"
    
    def register():
        username = _unique_username()
        return client.post("/api/auth/register", json={
            "username": username,
            "email": email,
            "password": "123456",
        })
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(register) for _ in range(3)]
        results = [f.result() for f in futures]
    
    # 统计状态码
    status_counts = {}
    for r in results:
        status_counts[r.status_code] = status_counts.get(r.status_code, 0) + 1
    
    print(f"状态码分布: {status_counts}")
    
    # 验证：有且只有1个成功
    success_count = status_counts.get(201, 0)
    assert success_count == 1, f"期望1个成功，实际{success_count}个"
    
    # 验证成功用户信息
    success_resp = next(r for r in results if r.status_code == 201)
    user_data = success_resp.json()
    assert user_data["email"] == email
    assert user_data["id"] > 0
    assert user_data["is_active"] is True
    
    # 其他请求应该返回409或500
    other_statuses = [r.status_code for r in results if r.status_code != 201]
    for status in other_statuses:
        assert status ==409, f"意外的状态码: {status}"


@pytest.mark.auth
def test_concurrent_login_same_user(client):
    """同一用户并发登录 → 所有登录都成功（多设备场景）"""
    _, username, _ = _register(client)
    
    def login():
        return _login(client, username)
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(login) for _ in range(3)]
        results = [f.result() for f in futures]
    
    # 所有登录都成功
    for r in results:
        assert r.status_code == 200
        assert "access_token" in r.cookies
        assert "refresh_token" in r.cookies


@pytest.mark.auth
def test_concurrent_logout_same_user(client):
    """同一用户并发登出 → 所有登出都成功（幂等操作）"""
    _, username, _ = _register(client)
    _login(client, username)
    
    def logout():
        return client.post("/api/auth/logout")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(logout) for _ in range(3)]
        results = [f.result() for f in futures]
    
    # 所有登出都成功
    for r in results:
        assert r.status_code == 200
        assert r.json()["msg"] == "已登出"
    
    # 登出后 token 失效
    resp = client.get("/api/sessions/")
    assert resp.status_code == 401


@pytest.mark.auth
def test_concurrent_register_and_login(client):
    """注册后并发登录 → 所有登录都成功"""
    username = _unique_username()
    email = f"{username}@example.com"
    
    # 注册
    reg_resp = client.post("/api/auth/register", json={
        "username": username,
        "email": email,
        "password": "123456",
    })
    assert reg_resp.status_code == 201
    
    def login():
        return _login(client, username)
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(login) for _ in range(3)]
        results = [f.result() for f in futures]
    
    # 所有登录都成功
    for r in results:
        assert r.status_code == 200
        assert "access_token" in r.cookies


@pytest.mark.auth
def test_concurrent_refresh_same_session(client):
    """同一会话并发刷新 → 至少1个成功（token是无状态的）"""
    _, username, _ = _register(client)
    _login(client, username)
    
    def refresh():
        return client.post("/api/auth/refresh")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(refresh) for _ in range(3)]
        results = [f.result() for f in futures]
    
    # 至少1个刷新成功
    success_count = sum(1 for r in results if r.status_code == 200)
    assert success_count >= 1, f"至少应该有1个刷新成功，实际{success_count}个"
    
    # 验证：成功响应都有新token
    for r in results:
        if r.status_code == 200:
            assert "access_token" in r.cookies