# tests/test_documents.py
import pytest
import uuid
import hashlib
pytestmark = pytest.mark.usefixtures("mock_embeddings_only")


# ========== 辅助函数（复用） ==========
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
    """辅助：上传文档"""
    return client.post(
        "/api/documents/upload",
        files={"file": (filename, content, content_type)}
    )

# ========== 上传测试 ==========

@pytest.mark.document
def test_upload_document_success(client):
    """正常上传文档"""
    _, username, _ = _register(client)
    _login(client, username)
    
    resp = _upload_doc(client)
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "test.txt"
    assert data["file_type"] == "txt"
    assert data["file_size"] == 12
    assert data["user_id"] > 0
    assert "id" in data
    assert data["status"] in ["uploading", "completed", "failed"]


@pytest.mark.document
def test_upload_document_without_auth(client):
    """未认证不能上传"""
    resp = _upload_doc(client)
    assert resp.status_code == 401


@pytest.mark.document
def test_upload_unsupported_file_type(client):
    """不支持的文件类型"""
    _, username, _ = _register(client)
    _login(client, username)
    
    resp = _upload_doc(client, filename="test.exe", content=b"fake exe", content_type="application/octet-stream")
    assert resp.status_code == 400
    assert "不支持的文件类型" in resp.json()["detail"]


@pytest.mark.document
def test_upload_duplicate_file(client):
    """重复上传相同文件"""
    _, username, _ = _register(client)
    _login(client, username)
    
    content = b"duplicate content"
    # 第一次上传
    resp1 = _upload_doc(client, content=content)
    assert resp1.status_code == 201
    
    # 第二次上传（相同内容）
    resp2 = _upload_doc(client, content=content)
    assert resp2.status_code == 409
    assert "文件已存在" in resp2.json()["detail"]


# monkeypatch:fixture，用于在测试期间临时修改对象、变量、函数等，测试结束后自动恢复原状。
@pytest.mark.document
def test_upload_file_too_large(client, monkeypatch):
    """文件过大"""
    _, username, _ = _register(client)
    _login(client, username)
    
    # 临时改小限制
    from app.core.config import settings
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 0.001)  # 1KB
    
    resp = _upload_doc(client, content=b"x" * 2000)  # 2KB
    assert resp.status_code == 413
    assert "超过" in resp.json()["detail"]


@pytest.mark.document
def test_upload_pdf_file(client):
    """上传 PDF 文件"""
    _, username, _ = _register(client)
    _login(client, username)
    
    resp = _upload_doc(client, filename="test.pdf", content=b"%PDF-1.4 fake", content_type="application/pdf")
    assert resp.status_code == 201
    data = resp.json()
    assert data["file_type"] == "pdf"


@pytest.mark.document
def test_upload_md_file(client):
    """上传 Markdown 文件"""
    _, username, _ = _register(client)
    _login(client, username)
    
    resp = _upload_doc(client, filename="test.md", content=b"# Hello", content_type="text/markdown")
    assert resp.status_code == 201
    data = resp.json()
    assert data["file_type"] == "md"


# ========== 列表测试 ==========

@pytest.mark.document
def test_list_documents_success(client):
    """正常列出文档"""
    _, username, _ = _register(client)
    _login(client, username)
    
    # 上传 3 个文档
    for i in range(3):
        _upload_doc(client, filename=f"test{i}.txt", content=f"content{i}".encode())
    
    resp = client.get("/api/documents/")
    assert resp.status_code == 200
    data = resp.json()
    assert "documents" in data
    assert "total" in data
    assert data["total"] >= 3


@pytest.mark.document
def test_list_documents_pagination(client):
    """分页列出文档"""
    _, username, _ = _register(client)
    _login(client, username)
    
    for i in range(5):
        _upload_doc(client, filename=f"test{i}.txt", content=f"content{i}".encode())
    
    resp = client.get("/api/documents/?skip=0&limit=2")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["documents"]) == 2
    assert data["total"] == 5


@pytest.mark.document
def test_list_documents_without_auth(client):
    """未认证不能列出"""
    resp = client.get("/api/documents/")
    assert resp.status_code == 401


@pytest.mark.document
def test_list_documents_other_user_not_visible(client):
    """用户只能看到自己的文档"""
    # 用户A 上传
    _, username_a, _ = _register(client)
    _login(client, username_a)
    _upload_doc(client, filename="A_doc.txt", content=b"A content")
    _upload_doc(client, filename="A_doc2.txt", content=b"A content2")
    
    # 用户B 登录
    _, username_b, _ = _register(client, username="test_user_b", email="test_b@example.com")
    _login(client, username_b)
    
    resp = client.get("/api/documents/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0


# ========== 删除测试 ==========

@pytest.mark.document
def test_delete_document_success(client):
    """正常删除文档"""
    _, username, _ = _register(client)
    _login(client, username)
    
    upload_resp = _upload_doc(client)
    doc_id = upload_resp.json()["id"]
    
    # 删除
    del_resp = client.delete(f"/api/documents/{doc_id}")
    assert del_resp.status_code == 204
    
    # 验证已删除
    list_resp = client.get("/api/documents/")
    assert all(d["id"] != doc_id for d in list_resp.json()["documents"])


@pytest.mark.document
def test_delete_document_removes_vectors(client):
    """删除文档时应同时删除向量库中对应的向量"""
    import time
    import chromadb
    from app.core.config import settings

    reg_resp, username, _ = _register(client)
    user_id = reg_resp.json()["id"]
    _login(client, username)

    upload_resp = _upload_doc(client, content=b"vector cleanup test content")
    assert upload_resp.status_code == 201
    doc_id = upload_resp.json()["id"]

    # 等待文档向量化完成
    for _ in range(100):
        docs = client.get("/api/documents/").json()["documents"]
        target = next((d for d in docs if d["id"] == doc_id), None)
        if target and target["status"] in ("completed", "failed"):
            break
        time.sleep(0.1)
    assert target["status"] == "completed", f"文档处理失败: {target['status']}"

    # 删除前：向量库中存在该文档的向量
    chroma_client = chromadb.PersistentClient(path=str(settings.CHROMA_PERSIST_DIR))
    collection = chroma_client.get_collection(f"user_{user_id}")
    assert len(collection.get(where={"document_id": str(doc_id)})["ids"]) > 0

    # 删除文档
    del_resp = client.delete(f"/api/documents/{doc_id}")
    assert del_resp.status_code == 204

    # 删除后：向量库中该文档的向量已被删除
    collection = chroma_client.get_collection(f"user_{user_id}")
    assert len(collection.get(where={"document_id": str(doc_id)})["ids"]) == 0


@pytest.mark.document
def test_delete_document_not_found(client):
    """删除不存在的文档"""
    _, username, _ = _register(client)
    _login(client, username)
    
    resp = client.delete("/api/documents/99999")
    assert resp.status_code == 404


@pytest.mark.document
def test_delete_document_other_user_fails(client):
    """用户不能删除他人的文档"""
    # 用户A 上传
    _, username_a, _ = _register(client)
    _login(client, username_a)
    upload_resp = _upload_doc(client, filename="A_doc.txt", content=b"A content")
    doc_id = upload_resp.json()["id"]
    
    # 用户B 登录
    _, username_b, _ = _register(client, username="test_user_b2", email="test_b2@example.com")
    _login(client, username_b)
    
    # 尝试删除 A 的文档
    resp = client.delete(f"/api/documents/{doc_id}")
    assert resp.status_code in [403, 404]  # 取决于实现


@pytest.mark.document
def test_delete_document_without_auth(client):
    """未认证不能删除"""
    resp = client.delete("/api/documents/1")
    assert resp.status_code == 401


# ========== 完整隔离测试 ==========

@pytest.mark.document
def test_document_ownership_isolation(client):
    """完整隔离验证：用户A的文档操作不影响用户B"""
    # 用户A 上传 3 个文档
    _, username_a, _ = _register(client)
    _login(client, username_a)
    doc_ids_a = []
    for i in range(3):
        resp = _upload_doc(client, filename=f"A_doc{i}.txt", content=f"A content{i}".encode())
        doc_ids_a.append(resp.json()["id"])
    
    list_resp_a = client.get("/api/documents/")
    total_a = list_resp_a.json()["total"]
    
    # 用户B 登录
    _, username_b, _ = _register(client, username="test_user_b3", email="test_b3@example.com")
    _login(client, username_b)
    
    # 用户B 看不到 A 的文档
    list_resp_b = client.get("/api/documents/")
    assert list_resp_b.json()["total"] == 0
    
    # 用户B 尝试删除 A 的文档
    resp = client.delete(f"/api/documents/{doc_ids_a[0]}")
    assert resp.status_code in [403, 404]
    
    # 用户A 的文档还在
    _login(client, username_a)
    list_resp_a2 = client.get("/api/documents/")
    assert list_resp_a2.json()["total"] == total_a

# ========== 状态测试 ==========

@pytest.mark.document
def test_document_status_flow(client):
    """文档状态流转：uploading → completed/failed"""
    _, username, _ = _register(client)
    _login(client, username)
    
    # 上传文档
    upload_resp = _upload_doc(client, content=b"This is a test document for status flow.")
    assert upload_resp.status_code == 201
    doc_id = upload_resp.json()["id"]
    
    # 上传后立即返回状态应为 uploading
    assert upload_resp.json()["status"] == "uploading"
    
    # ✅ 等待异步处理完成（最多10秒）
    import time
    max_wait = 10
    for _ in range(max_wait * 10):  # 100次 * 0.1秒 = 10秒
        list_resp = client.get("/api/documents/")
        assert list_resp.status_code == 200
        docs = list_resp.json()["documents"]
        
        target = next((d for d in docs if d["id"] == doc_id), None)
        if target and target["status"] in ["completed", "failed"]:
            break
        time.sleep(0.1)
    
    # 验证最终状态
    final_resp = client.get("/api/documents/")
    docs = final_resp.json()["documents"]
    target = next((d for d in docs if d["id"] == doc_id), None)
    assert target is not None, f"文档 {doc_id} 未找到"
    assert target["status"] in ["completed", "failed"], f"最终状态异常: {target['status']}"
    
    if target["status"] == "completed":
        assert target["chunk_count"] > 0


# ========== 边界测试 ==========

@pytest.mark.document
def test_upload_empty_file(client):
    """上传空文件"""
    _, username, _ = _register(client)
    _login(client, username)
    
    resp = _upload_doc(client, content=b"")
    assert resp.status_code == 201
    data = resp.json()
    assert data["file_size"] == 0


# ========== 删除幂等性测试 ==========

@pytest.mark.document
def test_delete_already_deleted(client):
    """重复删除已删除的文档返回404"""
    _, username, _ = _register(client)
    _login(client, username)
    
    # 上传并删除
    upload_resp = _upload_doc(client)
    doc_id = upload_resp.json()["id"]
    
    # 第一次删除成功
    del_resp = client.delete(f"/api/documents/{doc_id}")
    assert del_resp.status_code == 204
    
    # 第二次删除返回404
    del_resp2 = client.delete(f"/api/documents/{doc_id}")
    assert del_resp2.status_code == 404

# ========== 并发测试 ==========

@pytest.mark.document
def test_concurrent_upload_same_file(client):
    """并发上传相同文件，应该只成功1个"""
    _, username, _ = _register(client)
    _login(client, username)
    
    import concurrent.futures
    
    def upload():
        return _upload_doc(client, content=b"same content for concurrent test")
    
    # 同时发起3个上传请求
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(upload) for _ in range(3)]
        results = [f.result() for f in futures]
    
    # 验证：只有1个成功，其他2个返回409
    success_count = sum(1 for r in results if r.status_code == 201)
    conflict_count = sum(1 for r in results if r.status_code == 409)
    
    assert success_count == 1, f"期望1个成功，实际{success_count}个"
    assert conflict_count == 2, f"期望2个冲突，实际{conflict_count}个"