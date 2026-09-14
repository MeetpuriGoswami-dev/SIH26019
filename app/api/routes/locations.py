"""
BHUMI-NITI: National Geospatial & Location Discovery Routes
Handles location autocomplete, national resolution, and spatial footprint extraction.
"""

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from typing import Optional

from app.core.permissions import CurrentUser, get_current_user_from_token_or_header
from engine.geocoder import resolve_location, suggest_locations
from engine.spatial import query_live_spatial_footprint
from engine.pipeline import run_intelligence_pipeline

router = APIRouter(prefix="/api/v1", tags=["Geospatial & Intelligence"])


class QueryRequest(BaseModel):
    query: str
    radius_km: Optional[float] = 3.5


# ---------------------------------------------------------------------------
# Location Discovery
# ---------------------------------------------------------------------------

@router.get("/locations/suggest", summary="National location autocomplete (all 36 States/UTs)")
def api_suggest_locations(
    q: str = Query(..., min_length=1, description="Prefix search term")
):
    """
    Returns up to 5 location suggestions from Nominatim covering all Indian
    states and union territories — no bounding-box restriction.
    """
    try:
        return suggest_locations(q, limit=5)
    except Exception:
        return []


@router.get("/resolve", summary="Resolve a place name to geographic entity + boundary")
def api_resolve_location(
    query: str = Query(..., description="Entity name, PIN code, village, taluka, or city in India")
):
    """
    National location resolver. Supports all 36 States/UTs.
    Returns GeoJSON boundary, EPSG:7755 exact area, and administrative hierarchy.
    """
    try:
        return resolve_location(query)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Spatial Footprint / LULC
# ---------------------------------------------------------------------------

@router.get("/spatial", summary="Live LULC & protected zone footprint via Overpass")
def api_extract_spatial_footprint(
    lat: float = Query(..., description="Latitude coordinate"),
    lon: float = Query(..., description="Longitude coordinate"),
    radius_km: float = Query(3.5, description="Search radius in kilometres"),
):
    """
    Queries OpenStreetMap Overpass for live land-use, forest, and protected zone
    footprints around the given coordinate. Falls back to structured payload on timeout.
    """
    return query_live_spatial_footprint(lat, lon, radius_km)


# ---------------------------------------------------------------------------
# Master Intelligence Dossier
# ---------------------------------------------------------------------------

@router.get("/intel", summary="End-to-end land intelligence dossier (GET)")
def api_get_intelligence_dossier(
    query: str = Query(..., description="Entity name, PIN code, village, or taluka in India"),
    radius_km: float = Query(3.5, description="Extraction radius in km"),
):
    """
    Synthesises spatial, statutory, risk, and dispute data into a five-part
    land intelligence dossier. Supports all 36 States/UTs.
    """
    try:
        return run_intelligence_pipeline(query, radius_km=radius_km)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/intel", summary="End-to-end land intelligence dossier (POST)")
def api_post_intelligence_dossier(payload: QueryRequest):
    """POST variant of the intelligence dossier endpoint."""
    try:
        return run_intelligence_pipeline(payload.query, radius_km=payload.radius_km or 3.5)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
