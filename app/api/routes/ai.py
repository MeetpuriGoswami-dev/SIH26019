"""
BHUMI-NITI: Grounded RAG AI Query Routes
Strictly grounded to live spatial dossiers and state statutory codes.
Returns claim-linked citations and explicit insufficient-evidence fallback.
"""

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from typing import Optional, Dict, Any

from app.core.permissions import CurrentUser, get_current_user_from_token_or_header
from engine.ai_query import query_grounded_ai

router = APIRouter(prefix="/api/v1/ai", tags=["Grounded AI & RAG"])


class AIQueryRequest(BaseModel):
    query: str
    location: Optional[str] = "Gandhinagar"
    context: Optional[Dict[str, Any]] = None
    api_key: Optional[str] = None
    provider: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/query", summary="Grounded statutory AI query with jurisdiction-specific citations")
def api_post_grounded_ai_query(
    payload: AIQueryRequest,
    user: CurrentUser = Depends(get_current_user_from_token_or_header),
):
    """
    Answers natural language land governance queries grounded in:
    - Live spatial dossier (Overpass GIS footprint)
    - State-specific statutory codes (36 States/UTs)
    - Persisted dispute telemetry (eCourts / NJDG)

    Returns claim-linked statutory citations and `status: insufficient_evidence`
    when no relevant provision matches the query.
    """
    try:
        return query_grounded_ai(
            user_question=payload.query,
            location_query=payload.location or "Gandhinagar",
            context=payload.context,
            user_role=user.role.value,
            api_key=payload.api_key,
            provider=payload.provider,
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/query", summary="GET grounded statutory AI query")
def api_get_grounded_ai_query(
    query: str = Query(..., description="Natural language land governance question"),
    location: str = Query(..., description="Indian place name, village, or district"),
    api_key: Optional[str] = Query(None, description="Optional LLM API key (Gemini, Groq, OpenRouter)"),
    provider: Optional[str] = Query(None, description="Optional LLM provider (local_rag, groq, gemini, openrouter, ollama)"),
):
    """GET convenience endpoint for the grounded AI query engine."""
    try:
        return query_grounded_ai(user_question=query, location_query=location, api_key=api_key, provider=provider)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

