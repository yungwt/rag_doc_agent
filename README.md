# rag_doc_agent — 智能知识库助手（RAG）

基于 FastAPI + LangChain + Chroma + MySQL + Redis 的多租户 RAG 知识库问答系统，内置 Vue3 前端。

上传文档后自动切片并向量化入库；提问时检索最相关片段、拼接多轮对话上下文，由 LLM 生成带来源引用的答案。检索结果按相似度阈值过滤——无关问题（闲聊、常识）不会挂出假的检索来源，由模型直接回答。

## 功能特性

- **前端界面**：Vue3 + Element Plus 单页应用（顶栏导航 / 对话 / 文档管理 / 设置），由 FastAPI 静态托管，登录后即可使用。
- **多租户认证**：JWT 双 token（access + refresh）存于 httpOnly Cookie；refresh Cookie 收窄到 `/api/auth` 路径；refresh 轮换 + 旧令牌立即拉黑；令牌带 `jti` 防同秒签名碰撞；前端 401 自动单飞续期并重放请求。
- **文档管理**：PDF / TXT / MD 上传，MD5 按用户去重（失败记录不占坑，可重传），后台异步切片向量化，状态可追踪，失败原因（`error_message`）透传到界面；TXT 自动兼容 UTF-8 / GBK 编码。
- **服务端分页与筛选**：文档列表支持 `skip/limit/status`（处理中 = uploading + processing），筛选与分页都在数据库层完成。
- **RAG 问答**：向量检索 top-3 → 余弦相似度低于 `RELEVANCE_MIN_SCORE` 的切片丢弃 → 拼接多轮历史 → LLM 生成 → 返回来源引用。模型故障返回 503 且自动回滚本次提问，不产生重复历史。
- **多轮对话**：会话与消息持久化，首条消息自动更新会话标题；历史按消息 id 排序（不受秒级时间精度影响）；消息列表返回真实总数，超过 100 条时前端提供"加载更早消息"入口。
- **用户隔离**：每个用户独立 Chroma Collection，接口层校验资源归属。
- **容器化部署**：Dockerfile + docker-compose（MySQL + Redis + App，前端随镜像构建）。

## 技术栈

| 组件 | 技术 | 用途 |
|------|------|------|
| 前端 | Vue3 + Element Plus + Vite | 单页应用界面 |
| Web 框架 | FastAPI | 异步接口 + 前端静态托管 |
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
│   ├── main.py                   # FastAPI 入口：挂载路由、启动建表、托管前端产物
│   ├── api/                      # 路由层
│   │   ├── auth.py               # 注册 / 登录 / 登出 / 刷新（轮换 + 拉黑）
│   │   ├── documents.py          # 文档上传 / 列表（分页 + 状态筛选）/ 删除
│   │   ├── session.py            # 会话创建 / 列表 / 删除 / 历史消息（真实 total）
│   │   ├── qa.py                 # 问答（失败回滚本次提问）
│   │   └── settings.py           # 用户偏好（历史条数）
│   ├── core/                     # 核心组件
│   │   ├── config.py             # 环境变量读取 + 全局配置
│   │   ├── database.py           # MySQL 异步连接 + 依赖注入
│   │   ├── security.py           # JWT 签发/校验、密码哈希、Redis 黑名单
│   │   └── model_factory.py      # LLM / Embedding 单例
│   ├── models/                   # ORM 模型（user / document / chunk / session / message）
│   ├── schemas/                  # Pydantic 请求 / 响应结构
│   └── services/                 # 业务逻辑层
│       ├── auth_service.py       # 注册、登录、启用/禁用
│       ├── doc_service.py        # 上传、列表、删除、MD5 去重
│       ├── rag_service.py        # 文本提取（含 GBK）、切片、向量化、阈值检索、生成
│       └── session_service.py    # 会话 CRUD、消息存储、历史查询
├── frontend/                     # Vue3 前端（构建产物 dist/ 由 app 托管）
│   ├── src/
│   │   ├── App.vue               # 顶栏导航布局
│   │   ├── api.js                # axios 封装 + 401 自动续期拦截器
│   │   ├── views/                # 登录 / 对话 / 文档管理 / 设置
│   │   ├── components/           # PageHeader 等公共组件
│   │   ├── styles/theme.css      # 设计 token（色板 / 玻璃面板 / 渐变）
│   │   └── utils/format.js       # 服务端时间解析与格式化
│   └── dist/                     # 构建产物（docker build 内自动生成）
├── tests/                        # 测试（独立测试库 + 隔离目录，不碰真实数据）
│   ├── conftest.py               # 环境隔离 + mock 模型夹具
│   ├── test_auth.py              # 认证（含双 token 回归）
│   ├── test_documents.py         # 文档（含 GBK / 失败透传 / 筛选）
│   ├── test_session.py           # 会话
│   └── test_qa.py                # 问答链路（默认 mock，`-m llm` 跑真模型）
├── pyproject.toml                # 依赖（uv 管理）
├── Dockerfile / docker-compose.yml
├── pytest.ini
└── README.md
```

## 快速开始

### 方式一：Docker Compose（推荐）

1. 创建 `.env`（参考下方「环境变量」章节）。
2. 启动整套服务（MySQL + Redis + App，首次会构建前端）：

```bash
docker compose up -d
```

启动后访问 **http://localhost:8000** 即前端界面；接口文档在 http://127.0.0.1:8000/docs 。

> 前端或后端代码改动后需要重建镜像：`docker compose build app && docker compose up -d app`。

### 方式二：本地开发

| 软件 | 版本 |
|------|------|
| Python | 3.11+ |
| Node.js | 20+ |
| MySQL | 8.0+ |
| Redis | 6.0+ |
| uv | 最新 |

```bash
uv sync                          # 后端依赖
cd frontend && npm install       # 前端依赖
```

创建 `.env` 后只启动中间件，再分别起前后端：

```bash
docker compose up -d mysql redis
uv run uvicorn app.main:app --reload     # 后端 http://localhost:8000
cd frontend && npm run dev               # 前端开发服务器（Vite）
```

> 数据表会在启动时自动创建，无需手动建表。

## 环境变量

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

# ── Embedding（不填 API_KEY / BASE_URL 则复用 LLM 的配置）──
EMBEDDING_MODEL=qwen3.7-text-embedding

# ── 存储 ──
UPLOAD_DIR=uploads                  # 上传文件目录（相对路径基于项目根）
CHROMA_PERSIST_DIR=chroma_data      # 向量库持久化目录

# ── 文档处理 ──
MAX_UPLOAD_SIZE_MB=20
CHUNK_SIZE=500
CHUNK_OVERLAP=50

# ── 检索相关性阈值（余弦相似度 0~1）──
# 低于该值的切片丢弃；实测相关问题 ≥0.54、无关问题 ≤0.12，默认 0.4 位于鸿沟正中
RELEVANCE_MIN_SCORE=0.4

# ── 会话历史条数（拼入 prompt 的最大轮数）──
SESSION_HISTORY_LIMIT=10
```

## 接口列表

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/register` | 注册 |
| POST | `/api/auth/login` | 登录（token 写入 httpOnly Cookie） |
| POST | `/api/auth/logout` | 登出（access + refresh 均拉黑） |
| POST | `/api/auth/refresh` | 刷新 access token（轮换，旧 refresh 立即失效） |
| POST | `/api/documents/upload` | 上传文档（PDF/TXT/MD） |
| GET | `/api/documents/` | 文档列表（`skip/limit/status`，total 按筛选条件计） |
| DELETE | `/api/documents/{id}` | 删除文档（含文件 + 向量） |
| POST | `/api/sessions/` | 创建会话 |
| GET | `/api/sessions/` | 会话列表（分页） |
| GET | `/api/sessions/{id}/messages` | 历史消息（`limit ≤ 1000`；total 为会话消息总数） |
| DELETE | `/api/sessions/{id}` | 删除会话 |
| PUT | `/api/settings/history-limit` | 修改拼入 prompt 的历史条数 |
| POST | `/api/qa/` | 提问 |
| GET | `/health` | 健康检查 |

## 使用流程

1. **注册登录**：浏览器直接访问前端页面注册登录；Swagger / 非浏览器客户端可用 `Authorization: Bearer <access_token>`。
2. **上传文档**：在"文档管理"页拖拽或选择文件。状态流转 `uploading → processing → completed / failed`，页面自动轮询；失败时显示具体原因。
3. **提问**：在"对话"页选择会话提问。无关问题（寒暄、常识）直接由模型回答；命中知识库时回答下方展示来源（文档标题 + 片段内容）。
4. **查看历史**：默认加载最近 100 条，更早的消息点击"加载全部"获取。
5. **登出**：顶栏头像菜单退出，token 立即失效。

## 测试

在项目根目录执行（`uv run` 会自动按 `uv.lock` 同步依赖；需 MySQL / Redis 可达——Docker Compose 方式已映射 3306 / 6379 端口）：

```bash
uv run pytest             # 全量（默认 mock 模型，零 API 消耗）
uv run pytest -m auth     # 只跑认证
uv run pytest -m llm      # 真实调用 LLM / Embedding 的端到端用例
```

- **数据隔离**：测试使用独立 MySQL 库（`rag_doc_agent_test`，结束自动删除）、Redis db1、独立向量库与上传目录——真实数据零触碰。
- 覆盖 81 个用例（认证 26 / 文档 23 / 会话 16 / 问答链路 16），含双 token、编码兼容、失败回滚、分页筛选等回归；另有 5 个 `llm` 标记的端到端用例默认跳过。
