from fastapi import APIRouter, Depends, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.document import DocumentResponse, DocumentListResponse
from app.services import doc_service

router = APIRouter(prefix="/api/documents", tags=["文档"])


@router.post("/upload", response_model=DocumentResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = await doc_service.upload_document(db, current_user.id, file)
    return doc


@router.get("/", response_model=DocumentListResponse)
async def list_documents(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    docs, total = await doc_service.list_documents(db, current_user.id, skip, limit)
    return DocumentListResponse(documents=docs, total=total)

# app/api/documents.py
@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await doc_service.delete_document(db, document_id, current_user.id)