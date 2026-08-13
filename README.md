# 测试一下，待会就删掉
# rag_doc_agent — 智能知识库助手

基于 FastAPI + JWT + Redis + MySQL + RAG 的多租户智能知识库系统。  
上传文档 → 自动切片向量化 → 多轮对话改写 → 检索召回 → Reranker 重排序 → 生成答案，支持来源追溯。

## 技术栈

| 组件 | 技术 | 用途 |
|------|------|------|
| Web 框架 | FastAPI | 高性能异步接口 |
| 认证 | JWT + Redis 黑名单 | 多租户登录、登出、token 失效 |
| 数据库 | MySQL + SQLAlchemy 2.0 async | 用户、文档、会话、消息、切片记录 |
| 缓存/黑名单 | Redis | Token 黑名单，支持主动登出 |
| 向量库 | Chroma | 文档切片向量持久化 & 相似度检索 |
| LLM | 通义千问 / OpenAI 兼容接口 | 问答生成、多轮对话改写 |
| Embedding | DashScope text-embedding-v2 | 文本向量化 |
| Reranker | BAAI/bge-reranker-base | 检索结果重排序，提升答案质量 |
| 文档解析 | LangChain PyPDFLoader / TextLoader | PDF、TXT、MD 文本提取 |

## 项目结构

```
rag_doc_agent/
├── .env                          # 环境变量（密钥、数据库地址等）
├── .gitignore
├── requirements.txt
├── README.md
│
├── app/
│   ├── __init__.py
│   ├── main.py                   # FastAPI 入口，挂路由，启动事件
│   │
│   ├── api/                      # 路由层
│   │   ├── auth.py               # 注册、登录、登出
│   │   ├── documents.py          # 文档上传、列表
│   │   ├── qa.py                 # 问答接口
│   │   └── session.py            # 会话管理（创建/列表/删除/历史消息）
│   │
│   ├── core/                     # 核心组件
│   │   ├── config.py             # 环境变量读取 + 全局配置
│   │   ├── database.py           # MySQL 异步连接 + 依赖注入
│   │   ├── security.py           # JWT 签发/校验、密码哈希、Redis 黑名单
│   │   └── model_factory.py      # LLM / Embedding / Reranker 模型单例
│   │
│   ├── models/                   # ORM 模型
│   │   ├── base.py               # DeclarativeBase + 公共时间字段
│   │   ├── user.py               # User 表
│   │   ├── document.py           # Document 表 + DocStatus 枚举
│   │   ├── chunk.py              # DocumentChunk 表
│   │   ├── session.py            # Session 表（多轮对话）
│   │   └── message.py            # Message 表（对话历史）
│   │
│   ├── schemas/                  # Pydantic 请求/响应结构
│   │   ├── user.py
│   │   ├── document.py
│   │   ├── qa.py
│   │   └── session.py
│   │
│   └── services/                 # 业务逻辑层
│       ├── auth_service.py       # 注册、登录
│       ├── doc_service.py        # 上传、列表、MD5 去重
│       ├── rag_service.py        # 文本提取、切片、向量化、检索、改写、重排序、生成
│       └── session_service.py    # 会话 CRUD、消息存储、历史查询
│
├── uploads/                      # 上传文件存储（自动创建）
└── chroma_data/                  # 向量库持久化（自动创建）
```

## 完整启动流程（从零开始）

### 1. 环境要求

| 软件 | 版本 | 如何检查 |
|------|------|------|
| Python | 3.10+ | `python --version` |
| MySQL | 8.0+ | `mysql --version` |
| Redis | 6.0+ | `redis-cli --version` |

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

下载 Reranker 模型（约 1.1GB），存放在 `~/.cache/huggingface/` (可选，决定有无重排)

### 3. 配置环境变量

在项目根目录创建 `.env` 文件：

```env
# 数据库
DATABASE_URL=mysql+aiomysql://root:你的密码@localhost:3306/database_name

# Redis
REDIS_URL=redis://localhost:6379/0

# JWT（用 python -c "import secrets; print(secrets.token_hex(32))" 生成）
SECRET_KEY=你生成的随机字符串
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# 大语言模型（以阿里云通义千问为例）
LLM_MODEL=qwen-max
LLM_API_KEY=你的API_KEY
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# Embedding 模型
EMBEDDING_MODEL=text-embedding-v2
# EMBEDDING_API_KEY 如不填，自动复用 LLM_API_KEY

# reranker 模型 (可选，决定有无重排)
RERANKER_MODEL_PATH =本地缓存路径的完整 snapshot 地址 

# 文档处理
MAX_UPLOAD_SIZE_MB=20
CHUNK_SIZE=500
CHUNK_OVERLAP=50

# ── Session 历史记录 ──
SESSION_HISTORY_LIMIT = 10
```


### 4. 创建数据库

```bash
mysql -u root -p
```

输入密码后：

```sql
CREATE DATABASE database_name;
EXIT;
```

> 表会在 FastAPI 启动时自动创建，无需手动建表。

### 5. 启动 Redis

**Windows：**
```bash
# 如果安装了 Redis，在终端直接运行
redis-server

**验证 Redis 是否启动：**
```bash
redis-cli ping
# 返回 PONG 说明正常
```

### 6. 启动 FastAPI

```bash
uvicorn app.main:app --reload
```

看到以下输出说明启动成功：
```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Started reloader process
```

### 10. 打开接口文档

浏览器访问 **http://127.0.0.1:8000/docs**

右上角点 🔒，粘贴登录获取的 `access_token`，即可测试所有接口。

---

## 接口使用流程

### 第一步：注册 & 登录

```
POST /api/auth/register  → 注册
POST /api/auth/login     → 拿到 access_token 和 refresh_token(可以用于测试/api/auth/login/refresh)
```

### 第二步：创建会话

```
POST /api/sessions       → 返回 session_id
```

### 第三步：上传文档

```
POST /api/documents/upload  → 上传 PDF/TXT/MD 文件
GET  /api/documents/        → 查看文档列表和状态
```

文档状态流转：`uploading` → `processing` → `completed`（或 `failed`）

### 第四步：提问

```
POST /api/qa/
{
  "question": "这份文档讲了什么？",
  "session_id": 1
}
```

系统自动执行：多轮对话改写 → 向量检索召回 10 条 → Reranker 精选 3 条 → LLM 生成答案

### 第五步：查看对话历史

```
GET /api/sessions/{session_id}/messages
```

### 第六步：登出

```
POST /api/auth/logout     → token 加入 Redis 黑名单，立即失效
```

---

## 核心功能

| 功能 | 说明 |
|------|------|
| 多租户认证 | JWT + Redis 黑名单，支持主动登出、token 失效 |
| 文档管理 | PDF/TXT/MD 上传，MD5 去重，后台异步切片向量化 |
| 状态追踪 | uploading → processing → completed / failed，前端可轮询 |
| 多轮对话 | 会话管理 + 问题改写，自动补全代词和延续性指令 |
| Reranker 重排序 | 检索 10 条 → 精选 3 条，答案质量显著提升 |
| 来源追溯 | 每个答案附带文档标题、片段内容、位置索引 |
| 用户隔离 | 每个用户独立 Chroma Collection，检索天然安全 |
