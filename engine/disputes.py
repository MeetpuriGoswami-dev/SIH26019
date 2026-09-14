"""
BHUMI-NITI: Real-Time Land Dispute Telemetry Engine
Queries persistent dispute observations from SQLite/PostgreSQL data store.
Exposes telemetry from eCourts / NJDG public dashboards & state RCMMS portals.
Strictly redacts Personal Identifiable Information (PII).
"""

import json
import sqlite3
from typing import Dict, Any, Optional
from app.core.database import get_db_connection

def get_dispute_telemetry_for_district(district_name: str, taluka_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Fetches real persisted dispute observations for a district.
    If no telemetry exists in the database, returns an explicit `status: unavailable` payload
    without inventing fake numbers.
    """
    d_clean = district_name.strip().lower()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT active_pending_cases, civil_suits_count, revenue_appeals_count, clearance_rate, category_breakdown, source_dataset, reporting_period, retrieval_timestamp
    FROM dispute_observations
    WHERE district_key = ? OR district_key LIKE ?
    LIMIT 1
    """, (d_clean, f"%{d_clean}%"))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        categories = json.loads(row["category_breakdown"]) if row["category_breakdown"] else {}
        return {
            "status": "available",
            "active_pending_cases": row["active_pending_cases"],
            "civil_suits_count": row["civil_suits_count"],
            "revenue_appeals_count": row["revenue_appeals_count"],
            "quarterly_filing_trend": "Recorded in judicial portal",
            "clearance_rate": row["clearance_rate"],
            "source_dataset": row["source_dataset"],
            "reporting_period": row["reporting_period"],
            "retrieval_timestamp": row["retrieval_timestamp"],
            "category_breakdown": categories
        }
        
    return {
        "status": "unavailable",
        "message": f"Land dispute telemetry currently unavailable for '{district_name}'. No official judicial dashboard snapshot found for this district.",
        "active_pending_cases": 0,
        "civil_suits_count": 0,
        "revenue_appeals_count": 0,
        "quarterly_filing_trend": "No filing trend data",
        "clearance_rate": "N/A",
        "source_dataset": "None",
        "reporting_period": "N/A",
        "category_breakdown": {}
    }

# Backward compatibility alias
query_live_dispute_telemetry = get_dispute_telemetry_for_district
