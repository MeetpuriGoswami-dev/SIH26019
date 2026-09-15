"""
BHUMI-NITI: Document Repository & Statutory Knowledge API Routes
Handles document metadata, upload tracking, statutory KB queries,
and document ingestion job lifecycle management.
"""

import uuid
import os
import hashlib
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Depends, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.core.permissions import (
    CurrentUser,
    UserRole,
    get_current_user_from_token_or_header,
    require_role,
)
from app.core.database import get_db_connection
from engine.live_gov_kb import get_live_gujarat_repository, synthesize_live_gujarat_document
from app.services.storage_service import save_uploaded_document, compute_checksum
from app.services.ocr_service import extract_text_from_file

router = APIRouter(prefix="/api/v1", tags=["Document Repository"])

STORAGE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "storage", "documents")


class LiveSynthesisRequest(BaseModel):
    doc_id: Optional[str] = None
    document_url: Optional[str] = None
    topic: Optional[str] = None
    user_query: Optional[str] = None


# ---------------------------------------------------------------------------
# India Code / OGD Live Statutory Repository
# ---------------------------------------------------------------------------

@router.get("/kb/documents", summary="Search India Code & OGD statutory document repository")
def api_kb_get_documents(
    q: Optional[str] = Query(None, description="Free-text search term"),
    type: Optional[str] = Query(None, description="Document type filter (Act, Rules, Circular)"),
    theme: Optional[str] = Query(None, description="Theme filter (land, tenancy, forest)"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """
    Queries India Code (indiacode.gov.in) DSpace REST API + data.gov.in OGD portal.
    Results include provenance, issuing authority, and source URL.
    """
    try:
        return get_live_gujarat_repository(q=q, theme=theme, doc_type=type, limit=limit, offset=offset)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/kb/live-synthesize", summary="RAG synthesis over statutory documents")
def api_kb_live_synthesize(
    payload: LiveSynthesisRequest,
    user: CurrentUser = Depends(get_current_user_from_token_or_header),
):
    """Synthesise a statutory policy analysis from a live India Code document URL or topic."""
    try:
        return synthesize_live_gujarat_document(
            doc_id=payload.doc_id,
            document_url=payload.document_url,
            topic=payload.topic,
            user_query=payload.user_query,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Internal Document Upload & Ingestion [Researcher+ role]
# ---------------------------------------------------------------------------

@router.post("/documents/upload", summary="Upload a statutory document for ingestion [Researcher+]")
async def api_upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    jurisdiction: str = Form(..., description="State/UT name or 'National'"),
    doc_type: str = Form("Act", description="Act | Rules | Circular | Gazette | Court_Order"),
    issuing_authority: str = Form(...),
    publication_year: Optional[str] = Form(None),
    source_url: Optional[str] = Form(None),
    user: CurrentUser = Depends(require_role(UserRole.RESEARCHER)),
):
    """
    Upload a PDF or text statutory document for OCR, chunking, and vector indexing.
    Requires Researcher or higher role. Returns document_id and job_id for tracking.
    """
    ALLOWED_TYPES = {"application/pdf", "text/plain", "text/html"}
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file.content_type}. Allowed: PDF, TXT, HTML.")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded document is empty.")
    if len(file_bytes) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Document exceeds the 25 MB upload limit.")
    doc_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # Save file to storage
    file_path = save_uploaded_document(doc_id, file.filename or "document.pdf", file_bytes)

    # Persist document metadata
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO documents (id, doc_id, title, jurisdiction, issuing_authority, doc_type,
                               publication_year, source_url, file_path, checksum, owner_user_id, is_public, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        """,
        (doc_id, doc_id, title, jurisdiction, issuing_authority, doc_type,
         publication_year, source_url, file_path, compute_checksum(file_bytes), user.user_id, now),
    )

    # Create background ingestion job
    cursor.execute(
        """
        INSERT INTO background_jobs (id, job_type, status, progress_pct, error_log, owner_user_id, created_at, updated_at)
        VALUES (?, 'Doc_Ingestion', 'Pending', 0.0, ?, ?, ?, ?)
        """,
        (job_id, f"doc_id:{doc_id}", user.user_id, now, now),
    )
    conn.commit()
    conn.close()

    # Kick off OCR extraction synchronously for small files (< 5MB)
    if len(file_bytes) < 5 * 1024 * 1024:
        _ingest_document_sync(doc_id, job_id, file_path, file_bytes, file.content_type)

    return {
        "status": "accepted",
        "document_id": doc_id,
        "job_id": job_id,
        "message": "Document queued for OCR extraction and vector indexing.",
        "checksum": compute_checksum(file_bytes),
    }


def _ingest_document_sync(doc_id: str, job_id: str, file_path: str, file_bytes: bytes, content_type: str):
    """Perform synchronous OCR + chunk extraction for small documents."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()

    try:
        cursor.execute(
            "UPDATE background_jobs SET status='Processing', progress_pct=10.0, updated_at=? WHERE id=?",
            (now, job_id),
        )
        conn.commit()

        chunks = extract_text_from_file(file_bytes, content_type)
        if not chunks:
            raise ValueError("No text could be extracted from the uploaded document.")

        for idx, chunk in enumerate(chunks):
            text = (chunk.get("text") or "").strip()
            if not text:
                continue
            chunk_id = str(uuid.uuid4())
            cursor.execute(
                """
                INSERT INTO document_chunks (id, document_id, chunk_index, section_title, page_number, content_text)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (chunk_id, doc_id, idx, chunk.get("section_title"), chunk.get("page_number"), text),
            )

        cursor.execute(
            "UPDATE background_jobs SET status='Completed', progress_pct=100.0, updated_at=? WHERE id=?",
            (now, job_id),
        )
        conn.commit()
    except Exception as e:
        cursor.execute(
            "UPDATE background_jobs SET status='Failed', error_log=?, updated_at=? WHERE id=?",
            (str(e), now, job_id),
        )
        conn.commit()
    finally:
        conn.close()


@router.get("/documents", summary="List indexed statutory documents in the repository")
def api_list_documents(
    jurisdiction: Optional[str] = Query(None),
    doc_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(get_current_user_from_token_or_header),
):
    """
    List documents in the internal repository.
    Public users see only public documents (is_public=1).
    Researcher+ users see all documents.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    from app.core.permissions import ROLE_HIERARCHY, UserRole
    is_privileged = ROLE_HIERARCHY.get(user.role, 1) >= ROLE_HIERARCHY.get(UserRole.RESEARCHER, 2)

    conditions = []
    params = []
    if not is_privileged:
        conditions.append("is_public = 1")
    if jurisdiction:
        conditions.append("jurisdiction = ?")
        params.append(jurisdiction)
    if doc_type:
        conditions.append("doc_type = ?")
        params.append(doc_type)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    cursor.execute(
        f"SELECT id, doc_id, title, jurisdiction, issuing_authority, doc_type, publication_year, source_url, created_at FROM documents {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    )
    rows = cursor.fetchall()
    conn.close()

    return {"documents": [dict(r) for r in rows], "limit": limit, "offset": offset}


@router.get("/documents/{doc_id}/download", summary="Download an authorized document")
def api_download_document(
    doc_id: str,
    user: CurrentUser = Depends(get_current_user_from_token_or_header),
):
    """Stream a stored document only to its owner or a privileged reviewer."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT file_path, title, owner_user_id, is_public FROM documents WHERE doc_id = ?",
        (doc_id,),
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Document not found.")

    file_path = row["file_path"]
    owner_user_id = row["owner_user_id"]
    is_privileged = user.role in {UserRole.GOV_OFFICIAL, UserRole.ADMINISTRATOR}
    if not is_privileged and owner_user_id != user.user_id and not row["is_public"]:
        raise HTTPException(status_code=403, detail="Access denied for this document.")
    if not file_path or not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Document file is unavailable.")

    return FileResponse(file_path, filename=f"{row['title']}.bin", media_type="application/octet-stream")


@router.get("/documents/jobs/{job_id}", summary="Check document ingestion job status")
def api_get_ingestion_job(
    job_id: str,
    user: CurrentUser = Depends(get_current_user_from_token_or_header),
):
    """Check the status and progress of a background document ingestion job."""
    conn = get_db_connection()
    cursor = conn.cursor()
    is_privileged = user.role in {UserRole.GOV_OFFICIAL, UserRole.ADMINISTRATOR}
    owner_filter = "" if is_privileged else " AND owner_user_id = ?"
    params = [job_id] if is_privileged else [job_id, user.user_id]
    cursor.execute(f"SELECT * FROM background_jobs WHERE id = ?{owner_filter}", params)
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return dict(row)
