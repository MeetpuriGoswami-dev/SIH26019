"""
BHUMI-NITI: Document Blob Storage Service
Manages persistent storage for uploaded statutory documents.
Local filesystem adapter with S3/MinIO-compatible abstraction layer.
"""

import os
import hashlib
from datetime import datetime, timezone

# Base storage directory — relative to project root
_BASE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "storage", "documents"
)


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def save_uploaded_document(doc_id: str, original_filename: str, file_bytes: bytes) -> str:
    """
    Persist an uploaded document to local storage.

    Layout: storage/documents/<doc_id>/<original_filename>

    Returns the absolute file path.
    """
    safe_name = _sanitise_filename(original_filename)
    doc_dir = os.path.join(_BASE_DIR, doc_id)
    _ensure_dir(doc_dir)

    file_path = os.path.join(doc_dir, safe_name)
    with open(file_path, "wb") as f:
        f.write(file_bytes)

    return os.path.abspath(file_path)


def get_document_path(doc_id: str, filename: str) -> str:
    """Return the full path to a stored document, or raise FileNotFoundError."""
    safe_name = _sanitise_filename(filename)
    file_path = os.path.join(_BASE_DIR, doc_id, safe_name)
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Document file not found: {file_path}")
    return os.path.abspath(file_path)


def compute_checksum(file_bytes: bytes) -> str:
    """Compute SHA-256 hex digest for integrity verification."""
    return hashlib.sha256(file_bytes).hexdigest()


def delete_document(doc_id: str) -> bool:
    """Delete all stored files for a document_id. Returns True if any files were removed."""
    doc_dir = os.path.join(_BASE_DIR, doc_id)
    if not os.path.isdir(doc_dir):
        return False

    removed = False
    for fname in os.listdir(doc_dir):
        fpath = os.path.join(doc_dir, fname)
        if os.path.isfile(fpath):
            os.remove(fpath)
            removed = True

    try:
        os.rmdir(doc_dir)
    except OSError:
        pass  # Directory not empty — leave it

    return removed


def list_stored_documents() -> list:
    """List all document IDs currently stored on disk."""
    _ensure_dir(_BASE_DIR)
    return [
        d for d in os.listdir(_BASE_DIR)
        if os.path.isdir(os.path.join(_BASE_DIR, d))
    ]


def _sanitise_filename(filename: str) -> str:
    """Strip path separators and dangerous characters from a filename."""
    import re
    basename = os.path.basename(filename)
    # Allow alphanumeric, dash, underscore, dot
    safe = re.sub(r"[^\w\-\.]", "_", basename)
    return safe or "document.pdf"
