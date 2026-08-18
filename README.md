# rag_doc_agent — 智能知识库助手（RAG）

基于 FastAPI + LangChain + Chroma + MySQL + Redis 的多租户 RAG 知识库问答系统。

上传文档后自动切片并向量化入库；提问时检索最相关片段、拼接多轮对话上下文，由 LLM 生成带来源引用的答案。

## 功能特性

- **多租户认证**：JWT 双 token（access + refresh）存于 httpOnly Cookie，Redis 黑名单支持主动登出与 refresh 续期。
- **文档管理**：支持 PDF / TXT / MD 上传，MD5 去重，后台异步切片 + 向量化，状态可追踪。
- **RAG 问答**：向量检索 top-3 相关片段 → 拼接多轮历史 → LLM 生成 → 返回来源引用。
- **多轮对话**：会话与消息持久化，首条消息自动更新会话标题，历史上下文参与生成。
- **用户隔离**：每个用户独立 Chroma Collection，接口层校验资源归属。
- **容器化部署**：Dockerfile + docker-compose（MySQL + Redis + App）。

## 技术栈

| 组件 | 技术 | 用途 |
|------|------|------|
| Web 框架 | FastAPI | 异步接口 |
| ORM | SQLAlchemy 2.0 (async) | 数据模型 |
| 数据库 | MySQL 8.0 | 用户 / 文档 / 会话 / 消息 / 切片 |
| 缓存 | Redis 7 | JWT 黑名单 |
| 向量库 | Chroma（langchain-chroma） | 切片向量持久化 + 相似度检索 |
| LLM | OpenAI 兼容接口（默认通义千问） | 答案生成 |
| Embedding | DashScope Embeddings | 文本向量化 |
| 文档解析 | LangChain PyPDFLoader / TextLoader | PDF / TXT / MD 文本提取 |

## 项目结构

```
rag_doc_agent/
├── app/
│   ├── main.py                   # FastAPI 入口，挂载路由，启动建表
│   ├── api/                      # 路由层
│   │   ├── auth.py               # 注册 / 登录 / 登出 / 刷新
│   │   ├── documents.py          # 文档上传 / 列表 / 删除
│   │   ├── session.py            # 会话创建 / 列表 / 删除 / 历史消息
│   │   └── qa.py                 # 问答
│   ├── core/                     # 核心组件
│   │   ├── config.py             # 环境变量读取 + 全局配置
│   │   ├── database.py           # MySQL 异步连接 + 依赖注入
│   │   ├── security.py           # JWT 签发/校验、密码哈希、Redis 黑名单
│   │   └── model_factory.py      # LLM / Embedding 单例
│   ├── models/                   # ORM 模型
│   │   ├── base.py               # DeclarativeBase + 公共时间字段
│   │   ├── user.py               # 用户表
│   │   ├── document.py           # 文档表 + 状态枚举
│   │   ├── chunk.py              # 切片表
│   │   ├── session.py            # 会话表
│   │   └── message.py            # 消息表
│   ├── schemas/                  # Pydantic 请求 / 响应结构
│   │   ├── user.py
│   │   ├── document.py
│   │   ├── qa.py
│   │   └── session.py
│   └── services/                 # 业务逻辑层
│       ├── auth_service.py       # 注册、登录
│       ├── doc_service.py        # 上传、列表、删除、MD5 去重
│       ├── rag_service.py        # 文本提取、切片、向量化、检索、生成
│       └── session_service.py    # 会话 CRUD、消息存储、历史查询
├── tests/                        # 测试
│   ├── conftest.py               # 夹具与数据清理
│   ├── test_auth.py              # 认证
│   ├── test_documents.py         # 文档
│   ├── test_session.py           # 会话
│   └── test_qa.py                # 问答（端到端，真实调用 LLM / Embedding）
├── pyproject.toml                # 依赖（uv 管理）
├── uv.lock
├── Dockerfile
├── docker-compose.yml
├── pytest.ini
├── .env                          # 环境变量（需自行创建）
└── README.md
```

## 快速开始

### 方式一：Docker Compose（推荐）

1. 创建 `.env`（参考下方「环境变量」章节）。
2. 启动整套服务（MySQL + Redis + App）：

```bash
docker compose up -d
```

启动后访问接口文档：http://127.0.0.1:8000/docs

### 方式二：本地开发

#### 1. 环境要求

| 软件 | 版本 |
|------|------|
| Python | 3.11+ |
| MySQL | 8.0+ |
| Redis | 6.0+ |
| uv | 最新 |

#### 2. 安装依赖

```bash
uv sync
```

#### 3. 配置环境变量

在项目根目录创建 `.env` 文件：

```env
# ── 应用 ──
APP_ENV=development
LOG_LEVEL=INFO

# ── MySQL（组件式拼接；docker 内会自动覆盖 MYSQL_HOST=mysql）──
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=rag_user
MYSQL_PASSWORD=你的数据库密码
MYSQL_DATABASE=rag_doc_agent
# 仅 docker-compose 初始化 root 用
MYSQL_ROOT_PASSWORD=root密码

# ── Redis ──
REDIS_URL=redis://localhost:6379/0

# ── JWT（生成方式：python -c "import secrets; print(secrets.token_hex(32))"）──
SECRET_KEY=你的随机字符串
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# ── Cookie ──
COOKIE_SECURE=false        # 生产走 HTTPS 时置 true
COOKIE_SAMESITE=lax

# ── LLM（OpenAI 兼容接口，示例为通义千问）──
LLM_MODEL=qwen3.7-max
LLM_API_KEY=你的API_KEY
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# ── Embedding（不填 API_KEY 则自动复用 LLM_API_KEY）──
EMBEDDING_MODEL=qwen3.7-text-embedding

# ── 文档处理 ──
MAX_UPLOAD_SIZE_MB=20
CHUNK_SIZE=500
CHUNK_OVERLAP=50

# ── 会话历史条数 ──
SESSION_HISTORY_LIMIT=10
```

#### 4. 启动 MySQL / Redis

```bash
docker compose up -d mysql redis
```

#### 5. 启动 FastAPI

```bash
uv run uvicorn app.main:app --reload
```

> 数据表会在启动时自动创建，无需手动建表。

## 接口列表

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/register` | 注册 |
| POST | `/api/auth/login` | 登录（token 写入 httpOnly Cookie） |
| POST | `/api/auth/logout` | 登出（token 加入黑名单） |
| POST | `/api/auth/refresh` | 刷新 access token |
| POST | `/api/documents/upload` | 上传文档（PDF/TXT/MD） |
| GET | `/api/documents/` | 文档列表（分页） |
| DELETE | `/api/documents/{id}` | 删除文档（含文件 + 向量） |
| POST | `/api/sessions/` | 创建会话 |
| GET | `/api/sessions/` | 会话列表（分页） |
| GET | `/api/sessions/{id}/messages` | 会话历史消息 |
| DELETE | `/api/sessions/{id}` | 删除会话 |
| POST | `/api/qa/` | 提问 |
| GET | `/health` | 健康检查 |

## 使用流程

1. **注册登录**：`POST /api/auth/register` → `POST /api/auth/login`。登录后 token 存在 httpOnly Cookie，浏览器后续请求自动携带；Swagger / 非浏览器客户端可用 `Authorization: Bearer <access_token>`。
2. **上传文档**：`POST /api/documents/upload`。文档状态流转 `uploading → processing → completed / failed`，可轮询 `GET /api/documents/` 查看状态。
3. **创建会话**：`POST /api/sessions/`。
4. **提问**：`POST /api/qa/`，请求体：

```json
{
  "question": "这份文档讲了什么？",
  "session_id": 1
}
```

响应含 `answer` 与 `sources`（来源文档标题、片段内容、位置索引）。首条消息会自动用问题内容更新会话标题。

5. **查看历史**：`GET /api/sessions/{session_id}/messages`。
6. **登出**：`POST /api/auth/logout`，token 立即失效。

## 测试

项目使用 pytest，测试覆盖认证 / 文档 / 会话 / 问答四层，共 66 个用例。其中 `test_qa.py` 为端到端测试，**真实调用 LLM 与 Embedding**，需要 `.env` 里配置好可用的 API Key。

```bash
# 运行全部测试
uv run pytest

# 按标记运行
uv run pytest -m auth
uv run pytest -m document
uv run pytest -m session
uv run pytest -m qa

# 运行单个文件
uv run pytest tests/test_qa.py
```

测试标记定义在 [pytest.ini](pytest.ini)：`auth` / `document` / `session` / `qa` / `smoke`。
