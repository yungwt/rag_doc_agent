import os
from urllib.parse import quote_plus
from dotenv import load_dotenv
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Settings:
    # ── 应用 ──
    APP_ENV: str = os.getenv("APP_ENV", "development")
    DEBUG: bool = APP_ENV == "development"
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # ── 数据库 ──
    MYSQL_HOST: str = os.getenv("MYSQL_HOST", "localhost")
    MYSQL_PORT: int = int(os.getenv("MYSQL_PORT", "3306"))
    MYSQL_USER: str = os.getenv("MYSQL_USER", "rag_user")
    MYSQL_PASSWORD: str = os.getenv("MYSQL_PASSWORD", "")
    MYSQL_DATABASE: str = os.getenv("MYSQL_DATABASE", "rag_doc_agent")

    # 由组件变量拼接，避免手写完整 URL 时 host 写错（本地 localhost / 容器 mysql）
    DATABASE_URL: str = (
        f"mysql+aiomysql://{quote_plus(MYSQL_USER)}:{quote_plus(MYSQL_PASSWORD)}"
        f"@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}"
    )

    # ── Redis ──
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # ── JWT ──
    SECRET_KEY: str = os.getenv("SECRET_KEY")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 30))
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", 7))

    # ── LLM ──
    LLM_MODEL: str = os.getenv("LLM_MODEL")
    LLM_API_KEY: str = os.getenv("LLM_API_KEY")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL")

    # ── Embedding ──
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL")
    EMBEDDING_API_KEY: str = os.getenv("EMBEDDING_API_KEY", os.getenv("LLM_API_KEY"))
    EMBEDDING_BASE_URL: str = os.getenv("EMBEDDING_BASE_URL", os.getenv("LLM_BASE_URL"))

    # ── 向量库 ──
    CHROMA_PERSIST_DIR: Path = Path(os.getenv("CHROMA_PERSIST_DIR", "chroma_data"))
    if not CHROMA_PERSIST_DIR.is_absolute():
        CHROMA_PERSIST_DIR = Path(__file__).resolve().parent.parent / CHROMA_PERSIST_DIR

    # ── 文档处理 ──
    MAX_UPLOAD_SIZE_MB: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", 20))
    CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", 500))
    CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", 50))

    # —— 会话历史记录限制 ──
    SESSION_HISTORY_LIMIT: int = int(os.getenv("SESSION_HISTORY_LIMIT", 10))
    
    # ── CORS (部署时改) ──
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]


settings = Settings()