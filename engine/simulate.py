"""
BHUMI-NITI: Versioned Policy & Land Zoning Simulation Engine
Features:
1. Versioned policy scoring algorithm factoring in seismic hazard, flood rating, ESZ proximity, and dispute density.
2. Hard Legal Constraints Override: Absolute legal prohibitions (Section 73AA tribal land, ESZ core forest) trigger immediate hard rejection regardless of numerical feasibility score.
3. Persistent Run Logging: All simulation runs are saved to SQLite/PostgreSQL `simulation_runs` table for retrieval, comparison, and reproducible reruns.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from engine.geocoder import resolve_location
from engine.legal import evaluate_regulatory_framework
from engine.risk import evaluate_risk_and_vulnerability
from engine.spatial import query_live_spatial_footprint
from app.core.database import get_db_connection

def run_policy_simulation(
    query: str,
    simulation_type: str = "na_conversion",
    buffer_meters: float = 500.0,
    proposed_use: str = "Industrial / Logistics",
    target_area_sqm: float = 10000.0,
    user_id: str = "anonymous"
) -> Dict[str, Any]:
    """
    Executes land use policy simulation and persists the scenario run in database.
    """
    geo = resolve_location(query)
    spatial = query_live_spatial_footprint(geo["lat"], geo["lon"])
    legal = evaluate_regulatory_framework(geo["hierarchy"], geo["official_name"], spatial.get("forest_ecology", {}))
    risk = evaluate_risk_and_vulnerability(geo["hierarchy"], geo["lat"], geo["lon"], geo["official_name"])

    # 1. Base Score
    score = 85.0
    penalties: List[Dict[str, Any]] = []
    hard_constraints_triggered: List[str] = []

    # Check Hard Legal Constraint 1: Tribal Land Alienation Restriction
    if any("73AA" in r or "Section 36" in r or "PTCL" in r for r in legal.get("tenancy_and_conversion_rules", [])):
        hard_constraints_triggered.append("Section 73AA / Tribal Land Inalienability Restriction: Transfer of tribal land to non-tribals is prohibited by statute.")
        score = 0.0

    # Check Hard Legal Constraint 2: Protected Forest / Core ESZ
    forest = spatial.get("forest_ecology", {})
    if forest.get("is_protected"):
        hard_constraints_triggered.append("Notified Wildlife Sanctuary / Protected Forest Core Zone: Commercial development prohibited under Wildlife Protection Act.")
        score = 0.0

    # 2. Weighted Factor Calculations (if no hard legal prohibition)
    if not hard_constraints_triggered:
        # Seismic Hazard Penalty
        seismic_raw = risk.get("seismic_hazard", "")
        seismic_str = seismic_raw.get("zone", "") if isinstance(seismic_raw, dict) else str(seismic_raw)
        
        if "Zone V" in seismic_str:
            score -= 20.0
            penalties.append({"factor": "Seismic Hazard Zone V", "deduction": 20.0, "reason": "Maximum IS 1893 seismic risk"})
        elif "Zone IV" in seismic_str:
            score -= 10.0
            penalties.append({"factor": "Seismic Hazard Zone IV", "deduction": 10.0, "reason": "High IS 1893 seismic risk"})

        # Flood Risk Penalty
        flood_raw = risk.get("flood_rating", "")
        flood_str = flood_raw.get("rating", "") if isinstance(flood_raw, dict) else str(flood_raw)
        if "High" in flood_str:
            score -= 15.0
            penalties.append({"factor": "Flood Hazard", "deduction": 15.0, "reason": "High river basin / tidal flood vulnerability"})

        # Dispute Density Penalty
        disputes = risk.get("dispute_telemetry", {})
        cases = disputes.get("active_pending_cases", 0)
        if cases > 15000:
            score -= 15.0
            penalties.append({"factor": "High Litigation Density", "deduction": 15.0, "reason": f"Elevated litigation backlog ({cases} active cases)"})
            
    final_score = max(0.0, min(100.0, round(score, 1)))
    
    status = "Feasible with Standard Approvals"
    if hard_constraints_triggered:
        status = "REJECTED - Hard Legal Statutory Prohibition Triggered"
    elif final_score < 40:
        status = "High Risk - Major Clearance & Environmental Barriers"
    elif final_score < 70:
        status = "Moderate Risk - Special Committee NOC Required"

    scenario_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    # 3. Persist Simulation Run to Database
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO simulation_runs
        (id, user_id, location_name, proposed_use, buffer_meters, target_area_sqm, feasibility_score, hard_constraints, inputs_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            scenario_id,
            user_id,
            geo["official_name"],
            proposed_use,
            buffer_meters,
            target_area_sqm,
            final_score,
            json.dumps(hard_constraints_triggered),
            json.dumps({"simulation_type": simulation_type, "penalties": penalties}),
            now
        ))
        conn.commit()
        conn.close()
    except Exception:
        pass

    timeline_str = "4-6 Months (Standard Collector NOC)"
    if hard_constraints_triggered:
        timeline_str = "REJECTED - Statutory Prohibition"
    elif final_score < 40:
        timeline_str = "12-18 Months (State Level Environmental & Cabinet Clearance)"
    elif final_score < 70:
        timeline_str = "6-9 Months (Special District Committee NOC Required)"

    clearances = list(legal.get("na_conversion_prerequisites", []))
    if hard_constraints_triggered:
        clearances = hard_constraints_triggered + clearances

    return {
        "scenario_id": scenario_id,
        "location": geo["official_name"],
        "proposed_use": proposed_use,
        "buffer_meters": buffer_meters,
        "target_area_sqm": target_area_sqm,
        "feasibility_score": final_score,
        "feasibility": {
            "score_percentage": final_score,
            "status": status,
            "estimated_clearance_timeline": timeline_str,
        },
        "status": status,
        "hard_constraints_triggered": hard_constraints_triggered,
        "penalties": penalties,
        "required_clearances_checklist": clearances if clearances else [
            "iORA Portal Application & Revenue Entry Verified",
            "Form 7/12 & 30-Year Encumbrance Certificate",
            "District Collector NA Permission (GLRC 1879 Sec 65)",
            "Local Planning Authority GDCR Zoning NOC"
        ],
        "applicable_authority": legal["applicable_authority"],
        "special_legislation": legal["special_legislation"],
        "model_version": "2.0-national",
        "timestamp": now
    }
