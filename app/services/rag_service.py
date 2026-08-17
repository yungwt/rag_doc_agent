from pathlib import Path
from langchain_core.prompts import ChatPromptTemplate, HumanMessagePromptTemplate, SystemMessagePromptTemplate
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_chroma import Chroma
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import async_session
from app.core.config import settings
from app.core.model_factory import embeddings, llm
from app.models.document import Document, DocStatus
from app.models.chunk import DocumentChunk
from app.services.session_service import get_history as get_session_history

# ─── 文本提取 ────────────────────────────────────────────
def load_text(file_path: Path) -> str:
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        loader = PyPDFLoader(str(file_path))
        pages = loader.load()
        return "\n".join(p.page_content for p in pages)

    elif suffix in (".txt", ".md"):
        loader = TextLoader(str(file_path), encoding="utf-8")
        docs = loader.load()
        return "\n".join(d.page_content for d in docs)

    else:
        raise ValueError(f"不支持的文件类型: {suffix}")


# ─── 切片 ────────────────────────────────────────────────
def split_text(text: str) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
        separators=["\n\n", "\n", "。", ".", " ", ""],
    )
    return splitter.split_text(text)


# ─── 向量化 & 入库 ───────────────────────────────────────
async def process_document(doc_id: int, file_path: Path):
    try:
        async with async_session() as db:
            doc = await db.get(Document, doc_id)
            
            doc.status = DocStatus.PROCESSING
            await db.flush()

            text = load_text(file_path)
            chunks = split_text(text)
            if not chunks:
                raise ValueError("文档无可提取的文本内容")

            vector_store = Chroma(
                collection_name=f"user_{doc.user_id}",
                embedding_function=embeddings,
                persist_directory=str(settings.CHROMA_PERSIST_DIR),
            )

            chunk_ids = [f"doc_{doc.id}_chunk_{i}" for i in range(len(chunks))]
            vector_store.add_texts(
                texts=chunks,
                ids=chunk_ids,
                metadatas=[{"document_id": str(doc.id), "chunk_index": i} for i in range(len(chunks))],
            )

            for i, chunk_text in enumerate(chunks):
                db.add(DocumentChunk(
                    document_id=doc.id,
                    chunk_index=i,
                    content=chunk_text,
                    vector_id=chunk_ids[i],
                ))

            doc.status = DocStatus.COMPLETED
            doc.chunk_count = len(chunks)
            await db.flush()
            await db.commit()

    except Exception as e:
        print(f"❌ 文档处理失败 doc_id={doc_id}: {e}")  # ← 加这行
        import traceback
        traceback.print_exc()            
        async with async_session() as db:
            doc = await db.get(Document, doc_id)
            if doc:
                doc.status = DocStatus.FAILED
                await db.flush()
                await db.commit()

async def retrieve_chunks(user_id: int, question: str, k: int = 10) -> list[dict]:
    """
    纯检索：返回最相关的 k 个片段
    返回格式: [{"content": "...", "document_id": "1", "chunk_index": 0}, ...]
    """
    vector_store = Chroma(
        collection_name=f"user_{user_id}",
        embedding_function=embeddings,
        persist_directory=str(settings.CHROMA_PERSIST_DIR),
    )
    docs = vector_store.similarity_search(question, k=k)

    return [
        {
            "content": doc.page_content,
            "document_id": doc.metadata.get("document_id", ""),
            "chunk_index": doc.metadata.get("chunk_index", 0),
        }
        for doc in docs
    ]

async def generate_answer(question: str, chunks: list[dict], history: list[dict] = None) -> str:

    if not chunks:
        context = "无一张信息"
    else:
        # 拼接上下文
        context = "\n\n".join(
            f"[来源{i+1}]\n{chunk['content']}" for i, chunk in enumerate(chunks)
        )
    system_prompt = SystemMessagePromptTemplate.from_template(
        """你是一个基于对话历史和已知信息回答问题的助手。
            如果答案在历史对话中已明确，直接使用历史信息回答。
            如果历史中无答案，再根据已知信息回答。
            如果都没有，说"根据已知信息无法回答"。
            保持答案简洁准确。"""
        )
    human_prompt = HumanMessagePromptTemplate.from_template(
        """对话历史：
            {history}

            已知信息：
            {context}

            问题：{question}
            回答："""
    )
    prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

    print("=" * 40)
    print("📜 传给 LLM 的历史对话：")
    for line in history:
        print(f"  {line}")
    print("=" * 40)
    chain = prompt | llm
    response = await chain.ainvoke({
        "context": context,
        "question": question,
        "history":history
    })

    return response.content


async def enrich_sources(db: AsyncSession, user_id: int, chunks: list[dict]) -> list[dict]:
    """
    从数据库补充片段的来源信息（文档标题等）
    """
    sources = []
    for chunk in chunks:
        chunk_result = await db.execute(
            select(DocumentChunk).where(
                DocumentChunk.vector_id == f"doc_{chunk['document_id']}_chunk_{chunk['chunk_index']}"
            )
        )
        db_chunk = chunk_result.scalar_one_or_none()
        if db_chunk:
            doc_result = await db.get(Document, db_chunk.document_id)
            if doc_result and doc_result.user_id == user_id:
                sources.append({
                    "document_id": db_chunk.document_id,
                    "title": doc_result.title,
                    "chunk_index": db_chunk.chunk_index,
                    "content": db_chunk.content[:200],
                })
    return sources


async def ask_question(db: AsyncSession, user_id: int, question: str, session_id: int = None) -> dict:
    """
    组合：检索 → 生成 → 整理来源
    """
    if session_id:
        history = await get_session_history(db, session_id, limit=settings.SESSION_HISTORY_LIMIT)
        history = [
            f"{'用户' if msg.role == 'user' else '助手'}: {msg.content[:200]}"
            for msg in history
        ]
    else:
        history = ["无历史对话"]
    chunks = await retrieve_chunks(user_id, question, k=3)
    answer = await generate_answer(question, chunks, history)
    sources = await enrich_sources(db, user_id, chunks)

    return {"answer": answer, "sources": sources, "history": history}
    
