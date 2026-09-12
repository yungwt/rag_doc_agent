import logging
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
# 中文 .txt 大量是 GBK/GB2312 编码，gb18030 是它们的超集，放最后兜底
TEXT_ENCODINGS = ("utf-8", "gb18030")


def load_text(file_path: Path) -> str:
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        loader = PyPDFLoader(str(file_path))
        pages = loader.load()
        return "\n".join(p.page_content for p in pages)

    elif suffix in (".txt", ".md"):
        # TextLoader 解码失败时会抛 RuntimeError（原始 UnicodeDecodeError 挂在 __cause__）
        for encoding in TEXT_ENCODINGS:
            try:
                docs = TextLoader(str(file_path), encoding=encoding).load()
                return "\n".join(d.page_content for d in docs)
            except (UnicodeDecodeError, RuntimeError):
                continue
        raise ValueError("文本编码无法识别（已尝试 UTF-8 / GBK），请另存为 UTF-8 后重新上传")

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
        import traceback
        traceback.print_exc()            
        async with async_session() as db:
            doc = await db.get(Document, doc_id)
            if doc:
                doc.status = DocStatus.FAILED
                # 落库失败原因：只打日志的话前端永远只看到一个"失败"标签
                doc.error_message = f"{type(e).__name__}: {e}"[:500]
                # 释放 hash 槽位：失败记录不该挡住用户重传同一文件
                doc.file_hash = None
                await db.flush()
                await db.commit()

async def retrieve_chunks(user_id: int, question: str, k: int = 10) -> list[dict]:
    """
    纯检索：返回最相关的 k 个片段（相似度低于 RELEVANCE_MIN_SCORE 的丢弃）
    返回格式: [{"content": "...", "document_id": "1", "chunk_index": 0}, ...]
    """
    vector_store = Chroma(
        collection_name=f"user_{user_id}",
        embedding_function=embeddings,
        persist_directory=str(settings.CHROMA_PERSIST_DIR),
    )
    pairs = vector_store.similarity_search_with_score(question, k=k)

    results = []
    for doc, dist in pairs:
        # l2 距离换算余弦相似度：归一化向量满足 d² = 2 - 2·cosθ → cos = 1 - d²/2
        relevance = max(0.0, 1.0 - dist * dist / 2)
        if relevance < settings.RELEVANCE_MIN_SCORE:
            continue
        results.append(
            {
                "content": doc.page_content,
                "document_id": doc.metadata.get("document_id", ""),
                "chunk_index": doc.metadata.get("chunk_index", 0),
            }
        )
    return results

def delete_document_vectors(user_id: int, doc_id: int) -> None:
    """从 Chroma 删除某文档对应的所有向量。

    按元数据 ``document_id`` 过滤删除；集合不存在或删除失败时静默跳过，
    保证不阻塞文档本身的删除流程。
    """
    try:
        vector_store = Chroma(
            collection_name=f"user_{user_id}",
            embedding_function=embeddings,
            persist_directory=str(settings.CHROMA_PERSIST_DIR),
        )
        vector_store.delete(where={"document_id": str(doc_id)})
    except Exception as e:
        logging.warning(f"删除文档 {doc_id} 的向量失败: {e}")

async def generate_answer(question: str, chunks: list[dict], history: list[dict] = None) -> str:

    if not chunks:
        context = "（暂无相关文档片段）"
    else:
        # 拼接上下文
        context = "\n\n".join(
            f"[来源{i+1}]\n{chunk['content']}" for i, chunk in enumerate(chunks)
        )
    system_prompt = SystemMessagePromptTemplate.from_template(
        """你是一个中文助手，请严格按以下顺序处理用户的问题：

            第一步，判断问题与「对话历史」「检索信息」是否相关。
            第二步，如果两者都与问题不相关（例如寒暄、闲聊、常识性提问），直接用你自己的知识正常回答。
            第三步，如果相关，优先采用「对话历史」中的信息；历史中没有答案时，再采用「检索信息」。
            只有当问题确实需要依据资料、而「对话历史」和「检索信息」里都找不到依据时，
            才回答"根据已知信息无法回答"。

            保持答案简洁准确，不要编造资料中没有的内容。"""
        )
    human_prompt = HumanMessagePromptTemplate.from_template(
        """对话历史：
            {history}

            检索信息：
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


async def ask_question(db: AsyncSession, user_id: int, question: str, session_id: int = None, history_limit: int | None = None) -> dict:
    """
    组合：检索 → 生成 → 整理来源
    history_limit: 用户级记忆长度，未设置时跟随全局默认
    """
    if session_id:
        history_msgs = await get_session_history(db, session_id, limit=history_limit or settings.SESSION_HISTORY_LIMIT)
        # 最后一条就是刚存的当前问题（已在下方单独作为 {question} 传入），剔除避免重复
        if history_msgs and history_msgs[-1].role == "user" and history_msgs[-1].content == question:
            history_msgs = history_msgs[:-1]
        history = [
            f"{'用户' if msg.role == 'user' else '助手'}: {msg.content[:200]}"
            for msg in history_msgs
        ]
    else:
        history = ["无历史对话"]
    chunks = await retrieve_chunks(user_id, question, k=3)
    answer = await generate_answer(question, chunks, history)
    sources = await enrich_sources(db, user_id, chunks)

    return {"answer": answer, "sources": sources, "history": history}
    
