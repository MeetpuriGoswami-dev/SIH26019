"""
BHUMI-NITI: Native PostgreSQL + PostGIS + pgvector Database Adapter
Direct connection engine using psycopg2 to PostgreSQL (Supabase / AWS RDS / Self-hosted)
"""

import os
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

logger = logging.getLogger("bhumi_niti.postgres")

POSTGRES_URL = os.environ.get("POSTGRES_URL", os.environ.get("DATABASE_URL", os.environ.get("SUPABASE_DB_URL", "")))


def is_postgres_configured() -> bool:
    """Check if direct PostgreSQL connection URL is configured in environment."""
    return bool(POSTGRES_URL and POSTGRES_URL.startswith(("postgres://", "postgresql://")))


def get_pg_connection():
    """Get a raw psycopg2 database connection to PostgreSQL."""
    try:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(POSTGRES_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        return conn
    except Exception as e:
        logger.error(f"Failed to connect to PostgreSQL: {e}")
        raise e


def init_postgres_db():
    """Initialize PostGIS, pgvector extensions and the core Bhumi-Niti production schema in PostgreSQL."""
    if not is_postgres_configured():
        return False

    try:
        conn = get_pg_connection()
        cursor = conn.cursor()

        # Extensions
        cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cursor.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')

        # Core identity and organization model
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'Public',
            is_approved BOOLEAN DEFAULT TRUE,
            org_id UUID,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS organizations (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS role_requests (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id UUID NOT NULL,
            requested_role TEXT NOT NULL,
            justification TEXT,
            status TEXT NOT NULL DEFAULT 'Pending',
            reviewer_user_id UUID,
            reviewed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            decision_note TEXT
        );
        """)

        # Canonical geography and provenance
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS canonical_locations (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            lgd_code TEXT,
            name TEXT NOT NULL,
            state_ut TEXT NOT NULL,
            district TEXT,
            subdistrict TEXT,
            village_ward TEXT,
            level TEXT NOT NULL,
            bbox JSONB,
            geojson JSONB,
            geom GEOMETRY(Geometry, 4326),
            area_sqkm DOUBLE PRECISION,
            source_name TEXT,
            source_id TEXT,
            source_url TEXT,
            source_classification TEXT DEFAULT 'authoritative',
            canonical_parent_id UUID,
            aliases_json JSONB DEFAULT '[]'::jsonb,
            metadata_json JSONB DEFAULT '{}'::jsonb,
            is_authoritative BOOLEAN DEFAULT TRUE,
            verified_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """)

        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_canonical_locations_geom ON canonical_locations USING GIST (geom);
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS dispute_observations (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            location_id UUID,
            district_key TEXT NOT NULL,
            reporting_period TEXT NOT NULL,
            source_dataset TEXT NOT NULL,
            active_pending_cases INT NOT NULL,
            civil_suits_count INT NOT NULL,
            revenue_appeals_count INT NOT NULL,
            clearance_rate TEXT NOT NULL,
            category_breakdown JSONB NOT NULL,
            retrieval_timestamp TIMESTAMPTZ DEFAULT NOW()
        );
        """)

        # Documents + vector search
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            doc_id TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            jurisdiction TEXT NOT NULL,
            issuing_authority TEXT NOT NULL,
            doc_type TEXT NOT NULL,
            publication_year TEXT,
            source_url TEXT,
            file_path TEXT,
            checksum TEXT,
            owner_user_id UUID REFERENCES users(id),
            is_public BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS document_chunks (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
            chunk_index INT NOT NULL,
            section_title TEXT,
            page_number INT,
            content_text TEXT NOT NULL,
            embedding VECTOR(1536)
        );
        """)

        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding ON document_chunks USING hnsw (embedding vector_cosine_ops);
        """)

        # Simulation and workspace model
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            org_id UUID,
            name TEXT NOT NULL,
            description TEXT,
            created_by UUID NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS project_comments (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            user_id UUID NOT NULL,
            user_name TEXT NOT NULL,
            comment_text TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS simulation_runs (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id UUID,
            location_name TEXT NOT NULL,
            proposed_use TEXT NOT NULL,
            buffer_meters DOUBLE PRECISION NOT NULL,
            target_area_sqm DOUBLE PRECISION NOT NULL,
            feasibility_score DOUBLE PRECISION NOT NULL,
            hard_constraints JSONB NOT NULL,
            inputs_json JSONB NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS innovation_challenges (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            eligibility TEXT NOT NULL,
            deadline TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Active'
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS innovation_submissions (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            challenge_id UUID NOT NULL REFERENCES innovation_challenges(id) ON DELETE CASCADE,
            team_name TEXT NOT NULL,
            lead_user TEXT NOT NULL,
            proposal_summary TEXT NOT NULL,
            score DOUBLE PRECISION DEFAULT 0.0,
            status TEXT NOT NULL DEFAULT 'Submitted',
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS background_jobs (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            job_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            progress_pct DOUBLE PRECISION DEFAULT 0.0,
            error_log TEXT,
            owner_user_id UUID REFERENCES users(id),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
        """)

        cursor.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS owner_user_id UUID REFERENCES users(id);")
        cursor.execute("ALTER TABLE background_jobs ADD COLUMN IF NOT EXISTS owner_user_id UUID REFERENCES users(id);")

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_events (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id TEXT NOT NULL,
            action TEXT NOT NULL,
            resource TEXT NOT NULL,
            ip_address TEXT,
            timestamp TIMESTAMPTZ DEFAULT NOW()
        );
        """)

        # Blueprint entities that support versioning, provenance, collaboration,
        # innovation review, exports, and indicator-driven simulations.
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS organization_members (
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            membership_role TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (organization_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS project_members (
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            membership_role TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (project_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS sources (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            name TEXT NOT NULL,
            source_type TEXT NOT NULL,
            authority TEXT,
            base_url TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS source_snapshots (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            source_id UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
            retrieved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            source_url TEXT NOT NULL,
            checksum TEXT NOT NULL,
            content_type TEXT,
            storage_uri TEXT,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            UNIQUE (source_id, checksum)
        );
        CREATE TABLE IF NOT EXISTS boundary_versions (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            location_id UUID NOT NULL REFERENCES canonical_locations(id) ON DELETE CASCADE,
            source_snapshot_id UUID REFERENCES source_snapshots(id),
            version_number INT NOT NULL,
            valid_from DATE,
            valid_to DATE,
            geom GEOMETRY(Geometry, 4326) NOT NULL,
            area_sqkm DOUBLE PRECISION,
            checksum TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (location_id, version_number)
        );
        CREATE TABLE IF NOT EXISTS document_versions (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            version_number INT NOT NULL,
            source_snapshot_id UUID REFERENCES source_snapshots(id),
            checksum TEXT NOT NULL,
            storage_uri TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (document_id, version_number)
        );
        CREATE TABLE IF NOT EXISTS datasets (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            name TEXT NOT NULL,
            description TEXT,
            source_id UUID REFERENCES sources(id),
            owner_user_id UUID REFERENCES users(id),
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS dataset_versions (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            dataset_id UUID NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
            version_number INT NOT NULL,
            source_snapshot_id UUID REFERENCES source_snapshots(id),
            schema_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            checksum TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (dataset_id, version_number)
        );
        CREATE TABLE IF NOT EXISTS gis_layers (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            name TEXT NOT NULL,
            layer_type TEXT NOT NULL,
            owner_user_id UUID REFERENCES users(id),
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS gis_layer_versions (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            layer_id UUID NOT NULL REFERENCES gis_layers(id) ON DELETE CASCADE,
            version_number INT NOT NULL,
            dataset_version_id UUID REFERENCES dataset_versions(id),
            source_snapshot_id UUID REFERENCES source_snapshots(id),
            style_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (layer_id, version_number)
        );
        CREATE TABLE IF NOT EXISTS indicator_definitions (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            unit TEXT,
            methodology TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS indicator_observations (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            indicator_id UUID NOT NULL REFERENCES indicator_definitions(id) ON DELETE CASCADE,
            location_id UUID REFERENCES canonical_locations(id),
            dataset_version_id UUID REFERENCES dataset_versions(id),
            observed_at TIMESTAMPTZ NOT NULL,
            value DOUBLE PRECISION NOT NULL,
            quality_status TEXT NOT NULL DEFAULT 'unverified',
            UNIQUE (indicator_id, location_id, observed_at)
        );
        CREATE TABLE IF NOT EXISTS simulation_model_versions (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            model_name TEXT NOT NULL,
            version TEXT NOT NULL,
            parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
            published_at TIMESTAMPTZ,
            UNIQUE (model_name, version)
        );
        CREATE TABLE IF NOT EXISTS annotations (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES users(id),
            location_id UUID REFERENCES canonical_locations(id),
            body TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            assignee_user_id UUID REFERENCES users(id),
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            due_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS project_milestones (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'planned',
            due_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS collections (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (user_id, name)
        );
        CREATE TABLE IF NOT EXISTS saved_maps (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            collection_id UUID REFERENCES collections(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            map_state JSONB NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS innovation_teams (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            challenge_id UUID NOT NULL REFERENCES innovation_challenges(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            lead_user_id UUID REFERENCES users(id),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (challenge_id, name)
        );
        CREATE TABLE IF NOT EXISTS innovation_team_members (
            team_id UUID NOT NULL REFERENCES innovation_teams(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            member_role TEXT NOT NULL DEFAULT 'member',
            PRIMARY KEY (team_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS submission_versions (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            submission_id UUID NOT NULL REFERENCES innovation_submissions(id) ON DELETE CASCADE,
            version_number INT NOT NULL,
            proposal_summary TEXT NOT NULL,
            submitted_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (submission_id, version_number)
        );
        CREATE TABLE IF NOT EXISTS innovation_reviews (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            submission_id UUID NOT NULL REFERENCES innovation_submissions(id) ON DELETE CASCADE,
            reviewer_user_id UUID NOT NULL REFERENCES users(id),
            score DOUBLE PRECISION NOT NULL CHECK (score >= 0 AND score <= 100),
            decision TEXT NOT NULL,
            notes TEXT,
            reviewed_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (submission_id, reviewer_user_id)
        );
        CREATE TABLE IF NOT EXISTS pilots (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            submission_id UUID NOT NULL REFERENCES innovation_submissions(id),
            sponsor_org_id UUID REFERENCES organizations(id),
            status TEXT NOT NULL DEFAULT 'planned',
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ
        );
        CREATE TABLE IF NOT EXISTS pilot_milestones (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            pilot_id UUID NOT NULL REFERENCES pilots(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'planned',
            due_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ
        );
        CREATE TABLE IF NOT EXISTS exports (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            requested_by UUID NOT NULL REFERENCES users(id),
            export_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            storage_uri TEXT,
            checksum TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            completed_at TIMESTAMPTZ
        );
        CREATE INDEX IF NOT EXISTS idx_boundary_versions_geom ON boundary_versions USING GIST (geom);
        CREATE INDEX IF NOT EXISTS idx_indicator_observations_location ON indicator_observations (location_id, observed_at);
        CREATE INDEX IF NOT EXISTS idx_audit_events_resource ON audit_events (resource, timestamp);
        """)

        conn.commit()
        conn.close()
        logger.info("Successfully initialized PostgreSQL database with PostGIS and pgvector extensions and the production schema!")
        return True
    except Exception as e:
        logger.warning(f"PostgreSQL initialization warning: {e}")
        return False
