"""
BHUMI-NITI: OCR & Text Extraction Service
Extracts structured text chunks from uploaded PDF, plain-text, and HTML documents.
Uses pypdf for PDF extraction with page-level chunking and section detection.
Falls back to raw text splitting for non-PDF formats.
"""

import re
from typing import List, Dict, Any


def extract_text_from_file(file_bytes: bytes, content_type: str) -> List[Dict[str, Any]]:
    """
    Extract structured text chunks from a document.

    Returns a list of chunk dicts:
        {
            "text": str,            # chunk content
            "section_title": str,   # detected section heading or None
            "page_number": int,     # 1-indexed page (PDF) or None
            "chunk_index": int
        }
    """
    if content_type == "application/pdf":
        return _extract_from_pdf(file_bytes)
    elif content_type in ("text/plain", "text/html"):
        return _extract_from_text(file_bytes.decode("utf-8", errors="replace"))
    else:
        # Generic fallback: treat as raw text
        return _extract_from_text(file_bytes.decode("utf-8", errors="replace"))


def _extract_from_pdf(file_bytes: bytes) -> List[Dict[str, Any]]:
    """Extract text from PDF using pypdf. Chunks by page."""
    try:
        import io
        try:
            from pypdf import PdfReader
        except ImportError:
            try:
                from PyPDF2 import PdfReader
            except ImportError:
                return _fallback_chunk(file_bytes.decode("utf-8", errors="replace"))

        reader = PdfReader(io.BytesIO(file_bytes))
        chunks = []

        for page_num, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""

            text = text.strip()
            if not text:
                continue

            # Split long pages into ~800-char sub-chunks
            sub_chunks = _split_into_chunks(text, max_chars=800)
            for sub_idx, sub_text in enumerate(sub_chunks):
                section_title = _detect_section_heading(sub_text)
                chunks.append({
                    "text": sub_text,
                    "section_title": section_title,
                    "page_number": page_num,
                    "chunk_index": len(chunks),
                })

        return chunks if chunks else _fallback_chunk("PDF extraction produced no text content.")

    except Exception as e:
        return _fallback_chunk(f"PDF extraction error: {str(e)}")


def _extract_from_text(raw_text: str) -> List[Dict[str, Any]]:
    """Extract chunks from plain text or HTML by splitting on blank lines and sections."""
    # Strip HTML tags if present
    clean_text = re.sub(r"<[^>]+>", " ", raw_text)
    clean_text = re.sub(r"\s+", " ", clean_text).strip()

    sub_chunks = _split_into_chunks(clean_text, max_chars=800)
    return [
        {
            "text": chunk,
            "section_title": _detect_section_heading(chunk),
            "page_number": None,
            "chunk_index": idx,
        }
        for idx, chunk in enumerate(sub_chunks)
        if chunk.strip()
    ]


def _split_into_chunks(text: str, max_chars: int = 800) -> List[str]:
    """Split text into chunks of at most max_chars, preferring sentence boundaries."""
    if len(text) <= max_chars:
        return [text]

    chunks = []
    # Try to split on paragraph breaks first
    paragraphs = re.split(r"\n\s*\n", text)
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(current) + len(para) + 1 <= max_chars:
            current = (current + " " + para).strip()
        else:
            if current:
                chunks.append(current)
            # If single paragraph exceeds max, split by sentence
            if len(para) > max_chars:
                sentences = re.split(r"(?<=[.!?])\s+", para)
                current = ""
                for sent in sentences:
                    if len(current) + len(sent) + 1 <= max_chars:
                        current = (current + " " + sent).strip()
                    else:
                        if current:
                            chunks.append(current)
                        current = sent[:max_chars]
            else:
                current = para

    if current:
        chunks.append(current)

    return [c for c in chunks if c.strip()]


def _detect_section_heading(text: str) -> str:
    """Heuristically detect a section heading from the first line of a chunk."""
    first_line = text.strip().split("\n")[0][:120]
    # Section patterns: "Section 63", "CHAPTER III", "Article 14", numbered headings
    if re.match(r"^(Section|SECTION|Chapter|CHAPTER|Article|ARTICLE|Part|PART|\d+[\.\)])", first_line):
        return first_line
    if first_line.isupper() and len(first_line) < 100:
        return first_line
    return None


def _fallback_chunk(text: str) -> List[Dict[str, Any]]:
    return [{"text": text[:2000], "section_title": None, "page_number": None, "chunk_index": 0}]
