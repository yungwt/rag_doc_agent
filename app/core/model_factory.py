from langchain_openai import ChatOpenAI
from langchain_community.embeddings import DashScopeEmbeddings
from app.core.config import settings

embeddings = DashScopeEmbeddings(
    model=settings.EMBEDDING_MODEL,
    dashscope_api_key=settings.EMBEDDING_API_KEY
)

llm = ChatOpenAI(
    model=settings.LLM_MODEL,
    api_key=settings.LLM_API_KEY,
    base_url=settings.LLM_BASE_URL,
    temperature=0.3,
)
