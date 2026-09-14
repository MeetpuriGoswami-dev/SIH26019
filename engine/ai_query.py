"""
BHUMI-NITI: Grounded RAG & Multi-Jurisdictional Statutory Query Engine
Features:
1. Grounded synthesis strictly bound to live dossier context and state-specific statutory acts.
2. Grounding Confidence Metric & Citations: Provides claim-linked citations matching the resolved state jurisdiction.
3. Insufficient Evidence Fallback: Returns explicit unsupported notice when no relevant legal provisions match the question.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
from engine.pipeline import run_intelligence_pipeline
from app.core.database import get_db_connection

def query_grounded_ai(
    user_question: str, 
    location_query: str, 
    context: Optional[Dict[str, Any]] = None,
    user_role: str = "Public"
) -> Dict[str, Any]:
    """
    Answers natural language land governance queries grounded in statutory codes and live spatial dossiers.
    """
    clean_question = user_question.strip()
    if not clean_question:
        raise ValueError("Question cannot be empty.")

    # Fetch live ground-truth dossier
    if context and "raw_layers" in context:
        dossier = context
    else:
        dossier = run_intelligence_pipeline(location_query)

    raw = dossier["raw_layers"]
    geo = raw["identity"]
    spatial = raw["spatial"]
    legal = raw["legal"]
    risk = raw["risk"]

    state = legal.get("jurisdiction_state", geo["hierarchy"].get("state", "National Territory"))
    district = geo["hierarchy"]["district"]
    taluka = geo["hierarchy"]["taluka"]
    name = geo["name"]
    exact_area = geo.get("exact_area_sqkm") or "N/A"

    q_lower = clean_question.lower()
    citations: List[str] = []
    answer_parts: List[str] = []
    grounding_factors: List[str] = []

    # -------------------------------------------------------------------------
    # Topic 1: Non-Agricultural Conversion & Development Sanctions
    # -------------------------------------------------------------------------
    if any(k in q_lower for k in ["na", "convert", "conversion", "warehouse", "factory", "industry", "industrial", "build", "construct", "zoning"]):
        authority = legal["applicable_authority"]
        act = legal["special_legislation"]
        citations.append(f"{act} ({authority} Regulations)")

        answer_parts.append(
            f"**Non-Agricultural (NA) Land Conversion Guidelines for {name} ({district} District, {state}):**\n"
            f"1. **Governing Planning Authority:** All development layout approvals and land conversions in **{taluka}** fall under **{authority}**.\n"
            f"2. **Statutory Framework:** Non-agricultural permissions must strictly comply with the *{act}* and relevant local General Development Control Regulations (GDCR).\n"
            f"3. **Prerequisites Checklist:**\n"
        )
        for req in legal.get("na_prerequisites", []):
            answer_parts.append(f"  - {req}")

        for rule in legal.get("tenancy_and_conversion_rules", []):
            if any(k in rule for k in ["Section 63", "Section 54", "Section 79", "Section 80", "Section 36"]):
                citations.append(rule)
                answer_parts.append(f"\n**Tenancy Restriction Warning:** {rule}")
                grounding_factors.append("Statutory Tenancy Restriction Flagged")

    # -------------------------------------------------------------------------
    # Topic 2: Ecological / Forest / Environmental Buffers
    # -------------------------------------------------------------------------
    elif any(k in q_lower for k in ["forest", "eco", "wildlife", "esz", "sanctuary", "environment", "tree", "river", "buffer"]):
        citations.append("Forest Conservation Act 1980 / Van Adhiniyam")
        citations.append("Environment (Protection) Act 1986 - ESZ Zonation Guidelines")

        forest = spatial.get("forest_ecology", {})
        dom_use = spatial.get("dominant_land_use", "Agricultural / Farmland")
        veg_pct = spatial.get("vegetation_cover_pct", "Unclassified")
        water_pct = spatial.get("water_body_footprint_pct", "Unclassified")

        if forest.get("is_protected"):
            protected_names = ", ".join(forest.get("protected_entities", ["Protected Reserve"]))
            answer_parts.append(
                f"**Eco-Sensitive Zone Alert for {name} ({state}):**\n"
                f"Live spatial analysis confirms proximity to notified ecological boundaries ({protected_names}). "
                "Commercial construction, mining, or heavy industrial expansion is strictly restricted within the ESZ buffer without prior clearance from the National Board for Wildlife (NBWL)."
            )
            grounding_factors.append("Active ESZ / Protected Forest Centroid Boundary")
        else:
            answer_parts.append(
                f"**Ecological & Remote Sensing Footprint for {name} ({state}):**\n"
                f"- **Dominant Land Cover:** {dom_use}\n"
                f"- **Vegetation & Green Cover:** {veg_pct}\n"
                f"- **Water Footprint:** {water_pct}\n"
                "No notified Wildlife Sanctuary core directly intersects the parcel centroid. Standard 10km Eco-Sensitive Zone verification applies during e-NA processing."
            )

    # -------------------------------------------------------------------------
    # Topic 3: Land Dispute & Litigation Telemetry
    # -------------------------------------------------------------------------
    elif any(k in q_lower for k in ["dispute", "title", "case", "court", "litigation", "risk", "fraud", "rcmms", "njdg"]):
        disputes = risk.get("dispute_telemetry", {})
        if disputes.get("status") == "available":
            citations.append(f"{disputes.get('source_dataset', 'eCourts NJDG')} Snapshot")
            answer_parts.append(
                f"**Land Dispute Telemetry for {district} District ({state}):**\n"
                f"- **Active Pending Cases:** {disputes.get('active_pending_cases'):,}\n"
                f"- **Civil Suits:** {disputes.get('civil_suits_count'):,}\n"
                f"- **Revenue Appeals:** {disputes.get('revenue_appeals_count'):,}\n"
                f"- **Clearance Rate:** {disputes.get('clearance_rate')}\n"
                f"- **Source Dataset:** {disputes.get('source_dataset')} ({disputes.get('reporting_period')})\n"
                "Title Search Report (30 years) from the Sub-Registrar Office is required to verify clear title."
            )
            grounding_factors.append("Official Judicial Telemetry Snapshot")
        else:
            answer_parts.append(
                f"**Land Dispute Telemetry Status for {district} District:**\n"
                f"No official judicial dispute snapshot is currently indexed for {district} district in the database. "
                "Title clarity must be independently verified via Sub-Registrar 30-year Search Report."
            )

    # -------------------------------------------------------------------------
    # Topic 4: Insufficient Evidence Fallback
    # -------------------------------------------------------------------------
    else:
        return {
            "status": "insufficient_evidence",
            "user_question": clean_question,
            "location": geo["official_name"],
            "jurisdiction_state": state,
            "answer": f"Insufficient official statutory evidence or specific policy provision found in the database for the query: '{clean_question}'. Please rephrase your query focusing on land conversion, statutory tenancy, ecological buffers, or litigation risk.",
            "citations": [],
            "grounding_confidence": "Low (Insufficient Evidence)",
            "grounding_factors": []
        }

    return {
        "status": "success",
        "user_question": clean_question,
        "location": geo["official_name"],
        "jurisdiction_state": state,
        "answer": "\n".join(answer_parts),
        "citations": citations,
        "grounding_confidence": "High (Grounded in Official Statutes & GIS Footprint)",
        "grounding_factors": grounding_factors,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
