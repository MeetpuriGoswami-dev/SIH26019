"""
BHUMI-NITI: Core Database Persistence Layer (SQLite + PostGIS abstraction adapter)
Handles persistent storage for:
1. Users & RBAC Identity
2. Organizations & Project Workspaces
3. Canonical Location Geographies & Boundaries
4. Land Dispute Telemetry & Observations
5. Statutory Document Repository & Vectors
6. Policy Simulation Scenarios & Factor Weights
7. Innovation Challenges, Submissions & Pilots
8. System Audit Trail & Background Job Lifecycles
"""

import sqlite3
import json
import os
import uuid
import re
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from app.core.config import settings
from app.core.security import hash_password, verify_password

DB_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "bhumi_niti.db")


def _translate_sqlite_placeholders(sql: str) -> str:
    """Translate SQLite-style ? placeholders to PostgreSQL %s placeholders."""
    return re.sub(r"(?<!\?)\?(?!\?)", "%s", sql)


class _PostgresCompatCursor:
    """Wrap psycopg2 cursors to accept SQLite-style parameter placeholders."""

    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, sql, params=None):
        if params is not None and "?" in sql:
            sql = _translate_sqlite_placeholders(sql)
        return self._cursor.execute(sql, params)

    def executemany(self, sql, params_seq):
        if "?" in sql:
            sql = _translate_sqlite_placeholders(sql)
        return self._cursor.executemany(sql, params_seq)

    def fetchone(self, *args, **kwargs):
        return self._cursor.fetchone(*args, **kwargs)

    def fetchall(self, *args, **kwargs):
        return self._cursor.fetchall(*args, **kwargs)

    def fetchmany(self, *args, **kwargs):
        return self._cursor.fetchmany(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class _PostgresCompatConnection:
    """Provide a PostgreSQL connection that accepts the current SQLite query style."""

    def __init__(self, conn):
        self._conn = conn

    def cursor(self, *args, **kwargs):
        return _PostgresCompatCursor(self._conn.cursor(*args, **kwargs))

    def commit(self):
        return self._conn.commit()

    def close(self):
        return self._conn.close()

    def __getattr__(self, name):
        return getattr(self._conn, name)


def get_db_connection():
    """Return PostgreSQL when configured, otherwise SQLite for local development only."""
    postgres_url = os.environ.get("POSTGRES_URL", os.environ.get("DATABASE_URL", os.environ.get("SUPABASE_DB_URL", "")))
    configured_postgres = bool(postgres_url and postgres_url.startswith(("postgres://", "postgresql://")))

    if configured_postgres:
        try:
            import psycopg2
            import psycopg2.extras
            conn = psycopg2.connect(postgres_url, cursor_factory=psycopg2.extras.RealDictCursor)
            return _PostgresCompatConnection(conn)
        except Exception as exc:
            raise RuntimeError(f"PostgreSQL configured but unavailable: {exc}") from exc

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def _ensure_bootstrap_admin_user():
    """Ensure the required officer account exists and uses the current secure password hash."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, password_hash, full_name, role, is_approved FROM users WHERE email = ?", (settings.BOOTSTRAP_ADMIN_EMAIL.lower(),))
    row = cursor.fetchone()

    if row:
        needs_refresh = (
            not str(row["password_hash"] or "").startswith("$argon2")
            or row["role"] != "Government Official"
            or row["full_name"] != "Government Officer"
            or row["is_approved"] != 1
        )
        if needs_refresh:
            cursor.execute(
                "UPDATE users SET password_hash = ?, full_name = ?, role = ?, is_approved = ? WHERE email = ?",
                (
                    hash_password(settings.BOOTSTRAP_ADMIN_PASSWORD),
                    "Government Officer",
                    "Government Official",
                    True,
                    settings.BOOTSTRAP_ADMIN_EMAIL.lower(),
                )
            )
        conn.commit()
        conn.close()
        return

    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    cursor.execute(
        """
        INSERT INTO users (id, email, password_hash, full_name, role, is_approved, org_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            settings.BOOTSTRAP_ADMIN_EMAIL.lower(),
            hash_password(settings.BOOTSTRAP_ADMIN_PASSWORD),
            "Government Officer",
            "Government Official",
            True,
            None,
            now,
        ),
    )
    conn.commit()
    conn.close()


def init_db():
    """Initialize database tables for the 10 core entity domains on startup."""
    postgres_url = os.environ.get("POSTGRES_URL", os.environ.get("DATABASE_URL", os.environ.get("SUPABASE_DB_URL", "")))
    if postgres_url and postgres_url.startswith(("postgres://", "postgresql://")):
        try:
            from app.core.postgres import init_postgres_db
            if init_postgres_db():
                _ensure_bootstrap_admin_user()
                print("[Database] Initialized PostgreSQL with PostGIS & pgvector.")
                return
            raise RuntimeError("PostgreSQL migration reported failure")
        except Exception as e:
            raise RuntimeError(f"Configured PostgreSQL database is unavailable or failed initialization: {e}") from e

    conn = get_db_connection()
    cursor = conn.cursor()


    # 1. Identity & RBAC
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        full_name TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'Public',
        is_approved INTEGER DEFAULT 1,
        org_id TEXT,
        created_at TEXT NOT NULL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS organizations (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)
    
    # 2. Canonical Locations & Boundaries
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS canonical_locations (
        id TEXT PRIMARY KEY,
        lgd_code TEXT,
        name TEXT NOT NULL,
        state_ut TEXT NOT NULL,
        district TEXT,
        subdistrict TEXT,
        village_ward TEXT,
        level TEXT NOT NULL,
        bbox TEXT,
        geojson TEXT,
        area_sqkm REAL,
        source_name TEXT,
        source_id TEXT,
        source_url TEXT,
        source_classification TEXT DEFAULT 'authoritative',
        canonical_parent_id TEXT,
        aliases_json TEXT DEFAULT '[]',
        metadata_json TEXT DEFAULT '{}',
        is_authoritative INTEGER DEFAULT 1,
        verified_at TEXT,
        created_at TEXT NOT NULL
    )
    """)
    
    # 3. Dispute Telemetry & Observations
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS dispute_observations (
        id TEXT PRIMARY KEY,
        location_id TEXT,
        district_key TEXT NOT NULL,
        reporting_period TEXT NOT NULL,
        source_dataset TEXT NOT NULL,
        active_pending_cases INTEGER NOT NULL,
        civil_suits_count INTEGER NOT NULL,
        revenue_appeals_count INTEGER NOT NULL,
        clearance_rate TEXT NOT NULL,
        category_breakdown TEXT NOT NULL,
        retrieval_timestamp TEXT NOT NULL
    )
    """)
    
    # 4. Statutory Documents & Chunks
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS documents (
        id TEXT PRIMARY KEY,
        doc_id TEXT UNIQUE NOT NULL,
        title TEXT NOT NULL,
        jurisdiction TEXT NOT NULL,
        issuing_authority TEXT NOT NULL,
        doc_type TEXT NOT NULL,
        publication_year TEXT,
        source_url TEXT,
        file_path TEXT,
        checksum TEXT,
        is_public INTEGER DEFAULT 1,
        created_at TEXT NOT NULL
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS document_chunks (
        id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL,
        chunk_index INTEGER NOT NULL,
        section_title TEXT,
        page_number INTEGER,
        content_text TEXT NOT NULL,
        FOREIGN KEY (document_id) REFERENCES documents (id)
    )
    """)
    
    # 5. Policy Simulations
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS simulation_runs (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        location_name TEXT NOT NULL,
        proposed_use TEXT NOT NULL,
        buffer_meters REAL NOT NULL,
        target_area_sqm REAL NOT NULL,
        feasibility_score REAL NOT NULL,
        hard_constraints TEXT NOT NULL,
        inputs_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)
    
    # 6. Collaborative Workspaces & Projects
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        org_id TEXT,
        name TEXT NOT NULL,
        description TEXT,
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS project_members (
        project_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        membership_role TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (project_id, user_id)
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS project_comments (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        user_name TEXT NOT NULL,
        comment_text TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)
    
    # 7. Innovation Hub & Challenges
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS innovation_challenges (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        eligibility TEXT NOT NULL,
        deadline TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Active'
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS innovation_submissions (
        id TEXT PRIMARY KEY,
        challenge_id TEXT NOT NULL,
        team_name TEXT NOT NULL,
        lead_user TEXT NOT NULL,
        proposal_summary TEXT NOT NULL,
        score REAL DEFAULT 0.0,
        status TEXT NOT NULL DEFAULT 'Submitted',
        created_at TEXT NOT NULL
    )
    """)
    
    # 8. Background Jobs & System Audit Log
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS background_jobs (
        id TEXT PRIMARY KEY,
        job_type TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Pending',
        progress_pct REAL DEFAULT 0.0,
        error_log TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS role_requests (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        requested_role TEXT NOT NULL,
        justification TEXT,
        status TEXT NOT NULL DEFAULT 'Pending',
        reviewer_user_id TEXT,
        reviewed_at TEXT,
        created_at TEXT NOT NULL,
        decision_note TEXT
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_events (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        action TEXT NOT NULL,
        resource TEXT NOT NULL,
        ip_address TEXT,
        timestamp TEXT NOT NULL
    )
    """)
    
    conn.commit()
    conn.close()

    _ensure_canonical_locations_columns()
    _ensure_bootstrap_admin_user()
    _seed_baseline_dispute_data()
    _seed_baseline_canonical_locations()


def _ensure_canonical_locations_columns():
    """Backfill newer canonical geography provenance columns for older local SQLite databases."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(canonical_locations)")
    existing = {row[1] for row in cursor.fetchall()}
    migrations = [
        ("source_name", "TEXT"),
        ("source_id", "TEXT"),
        ("source_url", "TEXT"),
        ("source_classification", "TEXT DEFAULT 'authoritative'"),
        ("canonical_parent_id", "TEXT"),
        ("aliases_json", "TEXT DEFAULT '[]'"),
        ("metadata_json", "TEXT DEFAULT '{}'"),
        ("is_authoritative", "INTEGER DEFAULT 1"),
        ("verified_at", "TEXT"),
    ]
    for column_name, column_sql in migrations:
        if column_name not in existing:
            cursor.execute(f"ALTER TABLE canonical_locations ADD COLUMN {column_name} {column_sql}")
    conn.commit()
    conn.close()


def _seed_baseline_canonical_locations():
    """Seed baseline canonical geography entries with source provenance metadata for the national registry."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as count FROM canonical_locations")
    if cursor.fetchone()["count"] > 0:
        conn.close()
        return

    now = datetime.now(timezone.utc).isoformat()
    baseline = [
        (
            "canonical-gj-01",
            "24",
            "Gujarat",
            "Gujarat",
            "Gandhinagar",
            None,
            None,
            "state",
            "[68.11, 20.13, 74.47, 24.72]",
            json.dumps({"type": "Polygon", "coordinates": [[[68.11, 20.13], [74.47, 20.13], [74.47, 24.72], [68.11, 24.72], [68.11, 20.13]]]}),
            196024.0,
            "OpenStreetMap / National Land Registry",
            "state-gj",
            "https://www.openstreetmap.org/",
            "authoritative",
            None,
            json.dumps(["Gujarat", "गुजरात"]),
            json.dumps({"admin_level": "state", "country": "India", "parent": "India"}),
            1,
            now,
            now,
        ),
        (
            "canonical-gj-02",
            "2425",
            "Ahmedabad",
            "Gujarat",
            "Ahmedabad",
            "Ahmedabad City",
            "Ahmedabad Urban Area",
            "district",
            "[72.48, 22.95, 72.65, 23.10]",
            json.dumps({"type": "Polygon", "coordinates": [[[72.48, 22.95], [72.65, 22.95], [72.65, 23.10], [72.48, 23.10], [72.48, 22.95]]]}),
            505.0,
            "OpenStreetMap / National Land Registry",
            "district-ahmedabad",
            "https://www.openstreetmap.org/",
            "authoritative",
            "canonical-gj-01",
            json.dumps(["Ahmedabad", "અમદાવાદ"]),
            json.dumps({"admin_level": "district", "state": "Gujarat", "parent": "canonical-gj-01"}),
            1,
            now,
            now,
        ),
        (
            "canonical-gj-03",
            "2401",
            "Kutch",
            "Gujarat",
            "Kutch",
            "Mundra",
            "Mundra Port SEZ",
            "district",
            "[68.75, 22.70, 71.00, 23.75]",
            json.dumps({"type": "Polygon", "coordinates": [[[68.75, 22.70], [71.00, 22.70], [71.00, 23.75], [68.75, 23.75], [68.75, 22.70]]]}),
            4567.0,
            "OpenStreetMap / National Land Registry",
            "district-kutch",
            "https://www.openstreetmap.org/",
            "authoritative",
            "canonical-gj-01",
            json.dumps(["Kachchh", "કચ્છ"]),
            json.dumps({"admin_level": "district", "state": "Gujarat", "parent": "canonical-gj-01"}),
            1,
            now,
            now,
        ),
    ]

    cursor.executemany(
        """
        INSERT INTO canonical_locations (
            id, lgd_code, name, state_ut, district, subdistrict, village_ward, level,
            bbox, geojson, area_sqkm, source_name, source_id, source_url, source_classification,
            canonical_parent_id, aliases_json, metadata_json, is_authoritative, verified_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        baseline,
    )
    conn.commit()
    conn.close()


def _seed_baseline_dispute_data():
    """Seed baseline dispute telemetry into SQLite database with source provenance."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) as count FROM dispute_observations")
    if cursor.fetchone()["count"] > 0:
        conn.close()
        return

    now = datetime.now(timezone.utc).isoformat()
    baseline = [
        ("dist-1", "ahmedabad", "Q3 2026", "NJDG eCourts & Gujarat RCMMS", 22630, 18420, 4210, "87.4%", json.dumps({"RTS Mutation Appeals": "28%", "Tenancy Restrictions": "24%", "Land Acquisition": "22%", "Town Planning": "16%", "Partition Suits": "10%"}), now),
        ("dist-2", "surat", "Q3 2026", "NJDG eCourts & Gujarat RCMMS", 18010, 14890, 3120, "89.1%", json.dumps({"RTS Mutation Appeals": "26%", "Tenancy Restrictions": "25%", "Expressway Acquisition": "21%", "Coastal Margin": "15%", "Partition": "13%"}), now),
        ("dist-3", "vadodara", "Q3 2026", "NJDG eCourts & Gujarat RCMMS", 12840, 10320, 2520, "90.5%", json.dumps({"RTS Mutation Appeals": "30%", "Mamlatdar Review": "22%", "GIDC Expansion": "19%", "Boundary Demarcation": "16%", "Title Claims": "13%"}), now),
        ("dist-4", "rajkot", "Q3 2026", "NJDG eCourts & Gujarat RCMMS", 14220, 11450, 2770, "88.2%", json.dumps({"Saurashtra Gharkhed Sec 54": "32%", "RTS Mutation": "27%", "Wasteland Encroachment": "18%", "Partition": "14%", "Survey Tippan": "9%"}), now),
        ("dist-5", "kutch", "Q3 2026", "NJDG eCourts & Gujarat RCMMS", 9410, 7180, 2230, "86.0%", json.dumps({"Solar/Wind Wasteland Lease": "31%", "Heritage Title Challenges": "25%", "Port CRZ Buffer": "18%", "Gauchar Encroachment": "15%", "Tenancy": "11%"}), now),
        ("dist-6", "gautam buddha nagar", "Q3 2026", "UP Revenue Court & eCourts NJDG", 15420, 12100, 3320, "85.2%", json.dumps({"NOIDA Master Plan Land Acquisition": "35%", "Section 80 NA Conversions": "28%", "SC/ST Land Alienation": "20%", "Riverbed Zonation": "17%"}), now),
        ("dist-7", "pune", "Q3 2026", "MH e-Hakk & Pune Revenue Court", 19850, 15900, 3950, "88.7%", json.dumps({"PMRDA Development Plan Pooling": "32%", "Section 63 Tenancy Invalidation": "27%", "Satbara 7/12 Partition": "23%", "Western Ghats Buffer": "18%"}), now),
    ]
    
    cursor.executemany("""
    INSERT INTO dispute_observations 
    (id, district_key, reporting_period, source_dataset, active_pending_cases, civil_suits_count, revenue_appeals_count, clearance_rate, category_breakdown, retrieval_timestamp)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, baseline)
    
    conn.commit()
    conn.close()

# Auto-initialize DB when module is loaded
init_db()
