"""
Bhumi-Niti (भूमि-नीति): National Digital Platform for Evidence-Based Land Governance
FastAPI Dynamic Geospatial Engine & MapLibre GL JS Executive Dashboard | DoLR, MoRD

Architecture v2.1:
- Core auth, geospatial, simulation, and AI routes: inline (backward compatible)
- Extended routes (Workspaces, Innovation Hub, Analytics, Documents): app/api/routes/*
- Engine business logic: engine/*
- Database & Auth: app/core/*
- Services (OCR, Storage): app/services/*
"""

import os
from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime, timezone

from app.core.config import settings
from app.core.database import init_db, get_db_connection
from app.core.security import hash_password, verify_password, create_access_token
from app.core.permissions import (
    UserRole,
    CurrentUser,
    get_current_user_from_token_or_header,
    require_role,
)

from engine.geocoder import resolve_location, suggest_locations
from engine.spatial import query_live_spatial_footprint
from engine.legal import evaluate_regulatory_framework
from engine.risk import evaluate_risk_and_vulnerability
from engine.dossier import compile_intelligence_dossier
from engine.pipeline import run_intelligence_pipeline
from engine.simulate import run_policy_simulation
from engine.ai_query import query_grounded_ai
from engine.thematic import extract_thematic_gis_layers
from engine.knowledge_base import (
    get_all_documents,
    get_document_by_id,
    synthesize_policy_literature,
)
from engine.live_gov_kb import (
    get_live_gujarat_repository,
    synthesize_live_gujarat_document,
)
from engine.kb_view import render_knowledge_base_html
from engine.innovation_view import render_innovation_html
from engine.gov_portal_view import render_gov_portal_html

_default_allowed_origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
]
allowed_origins = os.getenv("ALLOWED_ORIGINS")
if allowed_origins:
    cors_origins = [origin.strip() for origin in allowed_origins.split(",") if origin.strip()]
elif settings.ENVIRONMENT.lower() == "production":
    cors_origins = []
else:
    cors_origins = _default_allowed_origins

app = FastAPI(
    title="Bhumi-Niti (भूमि-नीति) National Core API",
    description=(
        "National Digital Platform for Evidence-Based Land Governance — DoLR, Ministry of Rural Development. "
        "Covers all 36 Indian States & Union Territories with live GIS, statutory RAG, policy simulation, "
        "collaborative workspaces, and an innovation hub."
    ),
    version="2.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    """Initialize all database tables on server start."""
    init_db()


@app.get("/health/readiness", tags=["Operations"])
def readiness_check():
    """Report whether the configured database can serve application traffic."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1 AS ready")
        row = cursor.fetchone()
        if not row:
            raise RuntimeError("database did not return a readiness result")
        return {
            "status": "ready",
            "environment": settings.ENVIRONMENT,
            "database": "postgresql" if settings.DATABASE_URL.startswith(("postgres://", "postgresql://")) else "sqlite",
        }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database is not ready: {exc}") from exc
    finally:
        if conn is not None:
            conn.close()


# =============================================================================
# Pydantic Request / Response Models
# =============================================================================

class UserRegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str
    requested_role: Optional[str] = "Public"


class UserLoginRequest(BaseModel):
    email: str
    password: str


class QueryRequest(BaseModel):
    query: str
    radius_km: Optional[float] = 3.5


class SimulationRequest(BaseModel):
    query: str
    simulation_type: Optional[str] = "na_conversion"
    buffer_meters: Optional[float] = 500.0
    proposed_use: Optional[str] = "Industrial / Logistics"
    target_area_sqm: Optional[float] = 10000.0


class AIQueryRequest(BaseModel):
    query: str
    location: Optional[str] = "Gandhinagar"
    context: Optional[Dict[str, Any]] = None


class LiveSynthesisRequest(BaseModel):
    doc_id: Optional[str] = None
    document_url: Optional[str] = None
    topic: Optional[str] = None
    user_query: Optional[str] = None


# =============================================================================
# AUTHENTICATION & IDENTITY ENDPOINTS
# =============================================================================

@app.post("/api/v1/auth/register", tags=["Authentication"])
def register_user(payload: UserRegisterRequest):
    """
    Register a new user. Privileged roles (Government Official, Institution, Administrator)
    are created as pending and default to Public until an Administrator approves them.
    Role is always server-controlled — never from a client header.
    """
    import uuid

    PRIVILEGED_ROLES = {"Government Official", "Institution", "Administrator"}
    requested = payload.requested_role or "Public"

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM users WHERE email = ?", (payload.email.lower(),))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="Email already registered.")

    user_id = str(uuid.uuid4())
    pw_hash = hash_password(payload.password)
    now = datetime.now(timezone.utc).isoformat()
    is_approved = requested not in PRIVILEGED_ROLES
    assigned_role = requested if requested not in PRIVILEGED_ROLES else "Public"

    cursor.execute(
        "INSERT INTO users (id, email, password_hash, full_name, role, is_approved, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, payload.email.lower(), pw_hash, payload.full_name, assigned_role, is_approved, now),
    )
    conn.commit()
    conn.close()

    token = create_access_token({"sub": user_id, "email": payload.email, "role": assigned_role})
    return {
        "status": "success",
        "message": (
            "Registration successful. Role request pending admin approval."
            if requested in PRIVILEGED_ROLES
            else "User registered successfully."
        ),
        "user_id": user_id,
        "access_token": token,
        "token_type": "bearer",
        "role": assigned_role,
    }


@app.post("/api/v1/auth/login", tags=["Authentication"])
def login_user(payload: UserLoginRequest):
    """Login. Returns a signed JWT with role sourced from the database (server-controlled)."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, email, password_hash, full_name, role, is_approved FROM users WHERE email = ?",
        (payload.email.lower(),),
    )
    row = cursor.fetchone()
    conn.close()

    if not row or not verify_password(payload.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    if not row["is_approved"]:
        raise HTTPException(status_code=403, detail="Account pending administrator approval.")

    token = create_access_token({"sub": row["id"], "email": row["email"], "role": row["role"]})
    return {
        "status": "success",
        "access_token": token,
        "token_type": "bearer",
        "role": row["role"],
        "full_name": row["full_name"],
    }


@app.get("/api/v1/auth/me", tags=["Authentication"])
def get_current_user_profile(user: CurrentUser = Depends(get_current_user_from_token_or_header)):
    """Return authenticated identity. Role is sourced from the signed JWT — never from a request header."""
    return {
        "user_id": user.user_id,
        "email": user.email,
        "role": user.role.value,
        "organization_id": user.org_id,
    }


# =============================================================================
# NATIONAL GEOSPATIAL & DISCOVERY ENDPOINTS
# =============================================================================

@app.get("/api/v1/locations/suggest", tags=["Geospatial"])
def api_suggest_locations(q: str = Query(..., min_length=1)):
    """National location autocomplete — all 36 States & UTs via Nominatim (no bounding box)."""
    try:
        return suggest_locations(q, limit=5)
    except Exception:
        return []


@app.get("/api/v1/resolve", tags=["Geospatial"])
def api_resolve_location(query: str = Query(...)):
    """National location resolver. Returns GeoJSON boundary + EPSG:7755 exact area."""
    try:
        return resolve_location(query)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/spatial", tags=["Geospatial"])
def api_extract_spatial_footprint(
    lat: float = Query(...),
    lon: float = Query(...),
    radius_km: float = Query(3.5),
):
    """Live LULC & protected zone footprint via Overpass QL."""
    return query_live_spatial_footprint(lat, lon, radius_km)


@app.get("/api/v1/intel", tags=["Intelligence Dossier"])
def api_get_intelligence_dossier(
    query: str = Query(...),
    radius_km: float = Query(3.5),
):
    """Five-part land intelligence dossier: spatial, statutory, risk, dispute, and AI synthesis."""
    try:
        return run_intelligence_pipeline(query, radius_km=radius_km)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/intel", tags=["Intelligence Dossier"])
def api_post_intelligence_dossier(payload: QueryRequest):
    """POST variant of the intelligence dossier endpoint."""
    try:
        return run_intelligence_pipeline(payload.query, radius_km=payload.radius_km or 3.5)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# POLICY SIMULATION ENDPOINTS
# =============================================================================

@app.post("/api/v1/simulate", tags=["Policy Simulation"])
def api_post_policy_simulation(
    payload: SimulationRequest,
    user: CurrentUser = Depends(get_current_user_from_token_or_header),
):
    """Run a land-use policy simulation. Results persist to database with a UUID scenario_id."""
    try:
        return run_policy_simulation(
            query=payload.query,
            simulation_type=payload.simulation_type or "na_conversion",
            buffer_meters=payload.buffer_meters or 500.0,
            proposed_use=payload.proposed_use or "Industrial / Logistics",
            target_area_sqm=payload.target_area_sqm or 10000.0,
            user_id=user.user_id,
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/simulate", tags=["Policy Simulation"])
def api_get_policy_simulation(
    query: str = Query(...),
    simulation_type: str = Query("na_conversion"),
    buffer_meters: float = Query(500.0),
    proposed_use: str = Query("Industrial / Logistics"),
    target_area_sqm: float = Query(10000.0),
):
    """GET convenience endpoint for quick simulation queries."""
    try:
        return run_policy_simulation(
            query=query,
            simulation_type=simulation_type,
            buffer_meters=buffer_meters,
            proposed_use=proposed_use,
            target_area_sqm=target_area_sqm,
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# GROUNDED RAG AI QUERY ENDPOINTS
# =============================================================================

@app.post("/api/v1/ai/query", tags=["Grounded AI"])
def api_post_grounded_ai_query(
    payload: AIQueryRequest,
    user: CurrentUser = Depends(get_current_user_from_token_or_header),
):
    """Grounded statutory AI Q&A. Citations are jurisdiction-matched; returns insufficient_evidence fallback."""
    try:
        return query_grounded_ai(
            user_question=payload.query,
            location_query=payload.location or "Gandhinagar",
            context=payload.context,
            user_role=user.role.value,
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/ai/query", tags=["Grounded AI"])
def api_get_grounded_ai_query(query: str = Query(...), location: str = Query(...)):
    """GET grounded AI query endpoint."""
    try:
        return query_grounded_ai(user_question=query, location_query=location)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# EXTENDED API ROUTERS — Workspaces, Innovation, Analytics, Documents, Simulation
# =============================================================================

from app.api.routes.auth import router as auth_router
from app.api.routes.workspaces import router as workspaces_router
from app.api.routes.innovation import router as innovation_router
from app.api.routes.analytics import router as analytics_router
from app.api.routes.documents import router as documents_router
from app.api.routes.locations import router as locations_router
from app.api.routes.simulation import router as simulation_ext_router

app.include_router(auth_router)
app.include_router(workspaces_router)
app.include_router(innovation_router)
app.include_router(analytics_router)
app.include_router(documents_router)
app.include_router(locations_router)
app.include_router(simulation_ext_router)


# =============================================================================
# FRONTEND UI ROUTES
# =============================================================================

@app.get("/knowledge-base", response_class=HTMLResponse, tags=["Frontend"])
def knowledge_base_ui():
    """Land Governance Knowledge Base Portal UI."""
    return HTMLResponse(
        content=render_knowledge_base_html(),
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/innovation-hub", response_class=HTMLResponse, tags=["Frontend"])
@app.get("/innovation", response_class=HTMLResponse, tags=["Frontend"])
def innovation_ui():
    """DoLR Innovation Hub & Challenges Portal UI."""
    return HTMLResponse(
        content=render_innovation_html(),
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/map", response_class=HTMLResponse, tags=["Frontend"])
@app.get("/", response_class=HTMLResponse, tags=["Frontend"])
def index_ui():
    """GIGW 3.0 National Geoportal Executive Dashboard (MapLibre GL JS)."""
    return HTMLResponse(
        content=render_gov_portal_html(),
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
