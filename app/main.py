from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.models.base import Base
from app.core.database import engine
from app.api import auth
from app.api import documents
from app.api import qa,session


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时建表，关闭时释放连接"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(
    title="rag_doc_agent",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS 跨域（Cookie 认证需要 allow_credentials=True，且 origin 不能是 *）
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(qa.router)
app.include_router(session.router)


@app.get("/health")
async def health():
    return {"status": "ok"}