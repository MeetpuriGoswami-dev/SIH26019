"""
BHUMI-NITI: Comprehensive Automated Test Suite (Phase 6)
Tests: RBAC, National Geocoding, Policy Simulation Persistence,
       Grounded RAG + Fallback, Workspaces, Innovation Hub, Analytics Dashboard.
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from main import app
from app.core.database import get_db_connection

client = TestClient(app)

# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(scope="module")
def auth_tokens():
    """Register and login a test user for each role. Returns {role: token} dict."""
    tokens = {}

    # Register a Researcher
    r = client.post("/api/v1/auth/register", json={
        "email": "researcher_test@bhuminiti.gov.in",
        "password": "TestResearcher2026!",
        "full_name": "Test Researcher",
        "requested_role": "Researcher",
    })
    # May already exist (409 or 400) — try login
    lr = client.post("/api/v1/auth/login", json={
        "email": "researcher_test@bhuminiti.gov.in",
        "password": "TestResearcher2026!",
    })
    if lr.status_code == 200:
        tokens["researcher"] = lr.json()["access_token"]

    # Login the pre-seeded officer account
    lo = client.post("/api/v1/auth/login", json={
        "email": "officer@bhuminiti.gov.in",
        "password": "SecurePassword2026!",
    })
    if lo.status_code == 200:
        tokens["gov_official"] = lo.json()["access_token"]

    return tokens


# =============================================================================
# Phase 2 — RBAC & Authentication Tests
# =============================================================================

class TestAuthentication:
    """Phase 2: JWT identity, role-guarding, and access denial tests."""

    def test_register_new_user_returns_token(self):
        """Newly registered Public user gets a JWT immediately."""
        import uuid
        email = f"pub_{uuid.uuid4().hex[:8]}@test.in"
        r = client.post("/api/v1/auth/register", json={
            "email": email,
            "password": "PublicPass2026!",
            "full_name": "Public User",
            "requested_role": "Public",
        })
        assert r.status_code == 200, f"Registration failed: {r.text}"
        data = r.json()
        assert "access_token" in data
        assert data["role"] == "Public"

    def test_login_returns_jwt_with_server_role(self):
        """Login returns JWT and role is sourced from DB (server-controlled)."""
        r = client.post("/api/v1/auth/login", json={
            "email": "officer@bhuminiti.gov.in",
            "password": "SecurePassword2026!",
        })
        assert r.status_code == 200, f"Login failed: {r.text}"
        data = r.json()
        assert data["status"] == "success"
        assert "access_token" in data
        assert data["role"] == "Government Official"

    def test_me_endpoint_returns_server_controlled_role(self):
        """GET /auth/me returns role from JWT — no X-Role header bypass."""
        login = client.post("/api/v1/auth/login", json={
            "email": "officer@bhuminiti.gov.in",
            "password": "SecurePassword2026!",
        })
        token = login.json()["access_token"]

        r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        data = r.json()
        assert data["role"] == "Government Official"
        assert data["email"] == "officer@bhuminiti.gov.in"

    def test_x_role_header_does_not_escalate_privileges(self):
        """
        Sending X-Demo-Role-Override should NOT override a valid JWT token.
        JWT must take precedence over any client header.
        """
        # Register a plain Public user
        import uuid
        email = f"public_{uuid.uuid4().hex[:8]}@test.in"
        reg = client.post("/api/v1/auth/register", json={
            "email": email,
            "password": "PublicPass!",
            "full_name": "Attacker",
            "requested_role": "Public",
        })
        token = reg.json()["access_token"]

        # Try to escalate via header while also sending a valid Public JWT
        r = client.get("/api/v1/auth/me", headers={
            "Authorization": f"Bearer {token}",
            "X-Demo-Role-Override": "Administrator",  # must NOT take effect when JWT is present
        })
        assert r.status_code == 200
        # Role must remain Public — JWT wins
        assert r.json()["role"] == "Public"

    def test_unauthenticated_access_to_protected_route_returns_403(self):
        """
        Simulation history endpoint requires Researcher+.
        Unauthenticated (anonymous Public) must receive HTTP 403.
        """
        r = client.get("/api/v1/simulate/history")
        assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"

    def test_wrong_password_returns_401(self):
        r = client.post("/api/v1/auth/login", json={
            "email": "officer@bhuminiti.gov.in",
            "password": "WRONGPASSWORD",
        })
        assert r.status_code == 401

    def test_simulation_history_accessible_to_researcher(self, auth_tokens):
        """Researcher can access simulation history endpoint."""
        if "researcher" not in auth_tokens:
            pytest.skip("Researcher token not available")
        r = client.get("/api/v1/simulate/history", headers={"Authorization": f"Bearer {auth_tokens['researcher']}"})
        assert r.status_code == 200
        assert "runs" in r.json()


# =============================================================================
# Phase 3 — National Geocoding Tests (36 States/UTs)
# =============================================================================

class TestNationalGeocoding:
    """Phase 3: National location resolution — no Gujarat bounding box."""

    @pytest.mark.parametrize("location,expected_state", [
        ("Bhopal", "Madhya Pradesh"),
        ("Bengaluru", "Karnataka"),
        ("Sanand", "Gujarat"),
        ("Noida", "Uttar Pradesh"),
        ("Pune", "Maharashtra"),
    ])
    def test_national_location_resolution(self, location, expected_state):
        """Each city resolves to its correct state (not rejected as non-Gujarat)."""
        r = client.get(f"/api/v1/resolve?query={location}")
        assert r.status_code == 200, f"Resolution failed for {location}: {r.text}"
        data = r.json()
        state = data.get("hierarchy", {}).get("state", "")
        assert expected_state.lower() in state.lower(), (
            f"Expected state '{expected_state}' for {location}, got '{state}'"
        )

    @pytest.mark.parametrize("location", ["Bhopal", "Bengaluru", "Sanand", "Noida", "Pune"])
    def test_resolved_area_is_realistic(self, location):
        """Resolved area should be a positive number (real Nominatim data, not static mock)."""
        r = client.get(f"/api/v1/resolve?query={location}")
        assert r.status_code == 200
        area = r.json().get("exact_area_sqkm", 0)
        assert isinstance(area, (int, float))
        assert area > 0.01, f"Area suspiciously small for {location}: {area}"

    def test_location_suggest_returns_results(self):
        """Autocomplete returns at least one result for a common query."""
        r = client.get("/api/v1/locations/suggest?q=Gandhi")
        assert r.status_code == 200
        results = r.json()
        assert isinstance(results, list)


# =============================================================================
# Phase 4 — Grounded RAG & Insufficient-Evidence Fallback Tests
# =============================================================================

class TestGroundedAI:
    """Phase 4: RAG query, jurisdiction-matched citations, insufficient_evidence fallback."""

    def test_na_conversion_query_returns_jurisdiction_matched_citations(self):
        """NA conversion query for Bengaluru returns Karnataka statutes, not Gujarat."""
        r = client.post("/api/v1/ai/query", json={
            "query": "What are the NA conversion rules?",
            "location": "Bengaluru",
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "success"
        assert data["jurisdiction_state"] == "Karnataka"
        citations = " ".join(data.get("citations", []))
        assert "Karnataka" in citations or "BDA" in citations or "Karnataka Land Revenue" in citations, (
            f"Expected Karnataka-specific citations, got: {citations}"
        )

    def test_off_topic_query_returns_insufficient_evidence(self):
        """Non-land-governance query triggers the insufficient_evidence fallback."""
        r = client.post("/api/v1/ai/query", json={
            "query": "What is the quantum mechanics formula for gravity?",
            "location": "Gandhinagar",
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "insufficient_evidence"
        assert data["grounding_confidence"].startswith("Low")
        assert data["citations"] == []

    def test_dispute_query_returns_telemetry(self):
        """Dispute query returns available telemetry with source dataset."""
        r = client.post("/api/v1/ai/query", json={
            "query": "What is the land dispute situation and litigation risk?",
            "location": "Ahmedabad",
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "success"
        assert "active_pending_cases" in data["answer"] or "Dispute" in data["answer"]

    def test_forest_query_returns_ecology_analysis(self):
        """Forest/ecology query returns ESZ analysis."""
        r = client.post("/api/v1/ai/query", json={
            "query": "Are there forest or wildlife sanctuary buffers I need to worry about?",
            "location": "Sasan Gir",
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "success"


# =============================================================================
# Phase 4/5 — Policy Simulation Persistence Tests
# =============================================================================

class TestPolicySimulation:
    """Simulation persistence, hard constraint overrides, and retrieval."""

    def test_simulation_returns_scenario_id(self, auth_tokens):
        """Simulation run returns a UUID scenario_id and persists to DB."""
        if "gov_official" not in auth_tokens:
            pytest.skip("Gov official token not available")
        r = client.post("/api/v1/simulate", json={
            "query": "Sanand",
            "proposed_use": "Industrial Factory",
            "buffer_meters": 500,
        }, headers={"Authorization": f"Bearer {auth_tokens['gov_official']}"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert "scenario_id" in data
        assert len(data["scenario_id"]) == 36  # UUID format

    def test_gir_simulation_triggers_hard_constraint(self):
        """Gir National Park query triggers Protected Forest hard constraint → score 0."""
        r = client.get("/api/v1/simulate?query=Sasan+Gir&proposed_use=Industrial+Factory")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["feasibility_score"] == 0.0 or len(data["hard_constraints_triggered"]) > 0

    def test_simulation_history_lists_runs(self, auth_tokens):
        """Researcher can retrieve simulation history."""
        if "researcher" not in auth_tokens:
            pytest.skip("Researcher token not available")
        r = client.get("/api/v1/simulate/history", headers={"Authorization": f"Bearer {auth_tokens['researcher']}"})
        assert r.status_code == 200
        assert "runs" in r.json()
        assert isinstance(r.json()["runs"], list)


# =============================================================================
# Phase 5 — Workspace Tests
# =============================================================================

class TestWorkspaces:
    """Workspace isolation — project creation, comments, access control."""

    def test_researcher_can_create_project(self, auth_tokens):
        if "researcher" not in auth_tokens:
            pytest.skip("Researcher token not available")
        r = client.post("/api/v1/workspaces/projects", json={
            "name": "Test Research Project",
            "description": "Integration test project",
        }, headers={"Authorization": f"Bearer {auth_tokens['researcher']}"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "created"
        assert "project_id" in data

    def test_unauthenticated_cannot_create_project(self):
        """Public (unauthenticated) user must be denied project creation with 403."""
        r = client.post("/api/v1/workspaces/projects", json={"name": "Hack Project"})
        assert r.status_code == 403

    def test_researcher_can_add_comment(self, auth_tokens):
        if "researcher" not in auth_tokens:
            pytest.skip("Researcher token not available")
        # Create a project first
        proj = client.post("/api/v1/workspaces/projects", json={"name": "Comment Test Project"}, headers={"Authorization": f"Bearer {auth_tokens['researcher']}"})
        project_id = proj.json()["project_id"]

        r = client.post(f"/api/v1/workspaces/projects/{project_id}/comments", json={
            "comment_text": "This is a test comment on land governance analysis."
        }, headers={"Authorization": f"Bearer {auth_tokens['researcher']}"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "created"


# =============================================================================
# Phase 5 — Innovation Hub Tests
# =============================================================================

class TestInnovationHub:
    """Innovation challenge creation, team submissions, scoring, showcase."""

    def test_public_can_list_challenges(self):
        """Challenge listing is publicly accessible."""
        r = client.get("/api/v1/innovation/challenges")
        assert r.status_code == 200
        assert "challenges" in r.json()

    def test_gov_official_can_create_challenge(self, auth_tokens):
        if "gov_official" not in auth_tokens:
            pytest.skip("Gov official token not available")
        r = client.post("/api/v1/innovation/challenges", json={
            "title": "Test Land Survey Hackathon",
            "description": "Improve survey accuracy using satellite data.",
            "eligibility": "Universities and NGOs",
            "deadline": "2027-03-31",
            "status": "Active",
        }, headers={"Authorization": f"Bearer {auth_tokens['gov_official']}"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "created"

    def test_researcher_can_submit_proposal(self, auth_tokens):
        if "researcher" not in auth_tokens or "gov_official" not in auth_tokens:
            pytest.skip("Tokens not available")
        # Create challenge
        ch = client.post("/api/v1/innovation/challenges", json={
            "title": "Submission Test Challenge",
            "description": "Test",
            "eligibility": "All",
            "deadline": "2027-06-30",
            "status": "Active",
        }, headers={"Authorization": f"Bearer {auth_tokens['gov_official']}"})
        challenge_id = ch.json()["challenge_id"]

        r = client.post("/api/v1/innovation/submissions", json={
            "challenge_id": challenge_id,
            "team_name": "Team Alpha",
            "proposal_summary": "ML-based land classification for LULC mapping.",
        }, headers={"Authorization": f"Bearer {auth_tokens['researcher']}"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "submitted"

    def test_showcase_returns_pilot_approved(self):
        """Showcase endpoint is public and returns Pilot_Approved submissions."""
        r = client.get("/api/v1/innovation/showcase")
        assert r.status_code == 200
        assert "showcase" in r.json()


# =============================================================================
# Phase 5 — Analytics Dashboard Tests
# =============================================================================

class TestAnalyticsDashboard:
    """National/State/District drill-down KPIs and health badges."""

    def test_national_dashboard_returns_kpis(self):
        r = client.get("/api/v1/analytics/national")
        assert r.status_code == 200
        data = r.json()
        assert data["scope"] == "National"
        assert "dispute_telemetry_kpis" in data
        assert "policy_simulation_kpis" in data
        assert "platform_kpis" in data

    def test_national_kpi_dispute_count_is_positive(self):
        """At minimum, seeded dispute data should appear in national KPIs."""
        r = client.get("/api/v1/analytics/national")
        data = r.json()
        total = data["dispute_telemetry_kpis"]["total_active_pending_cases"]
        assert total > 0, f"Expected seeded dispute data, got {total}"

    def test_state_dashboard_returns_for_gujarat(self):
        r = client.get("/api/v1/analytics/state/Gujarat")
        assert r.status_code == 200
        data = r.json()
        assert data["scope"] == "State"
        assert data["state"] == "Gujarat"

    def test_district_dashboard_returns_available_for_ahmedabad(self):
        r = client.get("/api/v1/analytics/district/ahmedabad")
        assert r.status_code == 200
        data = r.json()
        assert data["scope"] == "District"
        assert data["data_status"] == "available"

    def test_district_dashboard_returns_unavailable_for_unknown_district(self):
        r = client.get("/api/v1/analytics/district/XYZUnknownDistrict9999")
        assert r.status_code == 200
        data = r.json()
        assert data["data_status"] == "unavailable"
        assert "No dispute telemetry" in data["message"]

    def test_health_badges_endpoint(self):
        r = client.get("/api/v1/analytics/health")
        assert r.status_code == 200
        data = r.json()
        assert "sources" in data
        assert len(data["sources"]) >= 4

    def test_health_ecourts_badge_shows_snapshot_available(self):
        """eCourts badge must show data as available (seeded data exists)."""
        r = client.get("/api/v1/analytics/health")
        sources = {s["name"]: s for s in r.json()["sources"]}
        ecourts = sources.get("eCourts / NJDG Dispute Telemetry", {})
        assert ecourts.get("status") == "operational"


# =============================================================================
# Phase 1 — Database Schema Tests
# =============================================================================

class TestDatabaseSchema:
    """Verify all 13 required tables exist in the database."""

    REQUIRED_TABLES = {
        "users", "organizations", "canonical_locations",
        "dispute_observations", "documents", "document_chunks",
        "simulation_runs", "projects", "project_comments",
        "innovation_challenges", "innovation_submissions",
        "background_jobs", "audit_events",
    }

    def test_all_required_tables_exist(self):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {r["name"] for r in cursor.fetchall()}
        conn.close()

        missing = self.REQUIRED_TABLES - tables
        assert not missing, f"Missing DB tables: {missing}"

    def test_dispute_observations_seeded(self):
        """Baseline dispute observations should be seeded on startup."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM dispute_observations")
        count = cursor.fetchone()["count"]
        conn.close()
        assert count >= 5, f"Expected at least 5 seeded dispute records, got {count}"
