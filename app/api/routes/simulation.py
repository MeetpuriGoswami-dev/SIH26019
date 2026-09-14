"""
BHUMI-NITI: Policy Simulation API Routes
Versioned land-use policy simulation with hard statutory constraint overrides
and persistent run logging to the database.
"""

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from typing import Optional, List

from app.core.permissions import (
    CurrentUser,
    UserRole,
    get_current_user_from_token_or_header,
    require_role,
)
from app.core.database import get_db_connection
from engine.simulate import run_policy_simulation

router = APIRouter(prefix="/api/v1", tags=["Policy Simulation"])


class SimulationRequest(BaseModel):
    query: str
    simulation_type: Optional[str] = "na_conversion"
    buffer_meters: Optional[float] = 500.0
    proposed_use: Optional[str] = "Industrial / Logistics"
    target_area_sqm: Optional[float] = 10000.0


# ---------------------------------------------------------------------------
# Run & Persist
# ---------------------------------------------------------------------------

@router.post("/simulate", summary="Run a land-use policy simulation scenario")
def api_post_policy_simulation(
    payload: SimulationRequest,
    user: CurrentUser = Depends(get_current_user_from_token_or_header),
):
    """
    Simulates land-use policy feasibility with hard statutory constraint overrides.
    Simulation runs are persisted to the database with a unique scenario_id.
    Requires at minimum Public authentication; results vary by role data access.
    """
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


@router.get("/simulate", summary="Quick GET simulation (no auth required for public queries)")
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


# ---------------------------------------------------------------------------
# Retrieve Persisted Runs
# ---------------------------------------------------------------------------

@router.get("/simulate/history", summary="Retrieve past simulation runs [Researcher+ role]")
def api_get_simulation_history(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(require_role(UserRole.RESEARCHER)),
):
    """
    Returns paginated list of persisted simulation runs.
    Researcher, Institution, Government Official, and Administrator roles can access.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, user_id, location_name, proposed_use, feasibility_score,
               hard_constraints, created_at
        FROM simulation_runs
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    )
    rows = cursor.fetchall()
    conn.close()

    return {
        "runs": [
            {
                "scenario_id": r["id"],
                "location": r["location_name"],
                "proposed_use": r["proposed_use"],
                "feasibility_score": r["feasibility_score"],
                "hard_constraints_triggered": r["hard_constraints"],
                "created_at": r["created_at"],
            }
            for r in rows
        ],
        "limit": limit,
        "offset": offset,
    }


@router.get("/simulate/{scenario_id}", summary="Retrieve a specific simulation run by ID")
def api_get_simulation_by_id(
    scenario_id: str,
    user: CurrentUser = Depends(require_role(UserRole.RESEARCHER)),
):
    """Fetch a specific persisted simulation run by its UUID scenario_id."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM simulation_runs WHERE id = ?",
        (scenario_id,),
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail=f"Simulation scenario '{scenario_id}' not found.")

    return dict(row)
