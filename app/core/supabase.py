"""
BHUMI-NITI: Supabase Cloud Database, PostGIS, pgvector & Storage Adapter
Project ID: zmdecwnywqfnpkmltoft
URL: https://zmdecwnywqfnpkmltoft.supabase.co
"""

import os
import json
import urllib.request
import urllib.parse
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", os.environ.get("SUPABASE_ANON_KEY", ""))
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def is_supabase_configured() -> bool:
    """Check if Supabase credentials are configured in environment."""
    return bool(SUPABASE_URL and (SUPABASE_KEY or SUPABASE_SERVICE_ROLE_KEY))


def get_supabase_headers(use_service_role: bool = False) -> Dict[str, str]:
    """Get HTTP headers for Supabase REST / Auth / RPC API requests."""
    key = (SUPABASE_SERVICE_ROLE_KEY if use_service_role and SUPABASE_SERVICE_ROLE_KEY else SUPABASE_KEY) or ""
    return {
        "Content-Type": "application/json",
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Prefer": "return=representation"
    }


def supabase_postgis_migration_sql() -> str:
    """
    SQL migration DDL for Supabase PostgreSQL:
    Enables PostGIS & pgvector extensions and creates the complete blueprint schema.
    """
    return """
-- ============================================================================
-- BHUMI-NITI: National Land Governance Supabase Schema & Extensions
-- ============================================================================

-- 1. Enable Required Extensions
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 2. Identity & RBAC
CREATE TABLE IF NOT EXISTS public.users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'Public',
    is_approved BOOLEAN DEFAULT TRUE,
    org_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.organizations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.role_requests (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    requested_role TEXT NOT NULL,
    justification TEXT,
    status TEXT NOT NULL DEFAULT 'Pending',
    reviewer_user_id UUID REFERENCES public.users(id),
    reviewed_at TIMESTAMPTZ,
    decision_note TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.organization_members (
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    membership_role TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (organization_id, user_id)
);

-- 3. Canonical Locations & PostGIS Boundaries
CREATE TABLE IF NOT EXISTS public.canonical_locations (
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

CREATE TABLE IF NOT EXISTS public.sources (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    authority TEXT,
    base_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.source_snapshots (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id UUID NOT NULL REFERENCES public.sources(id) ON DELETE CASCADE,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_url TEXT NOT NULL,
    checksum TEXT NOT NULL,
    content_type TEXT,
    storage_uri TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (source_id, checksum)
);

CREATE TABLE IF NOT EXISTS public.boundary_versions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    location_id UUID NOT NULL REFERENCES public.canonical_locations(id) ON DELETE CASCADE,
    source_snapshot_id UUID REFERENCES public.source_snapshots(id),
    version_number INT NOT NULL,
    valid_from DATE,
    valid_to DATE,
    geom GEOMETRY(Geometry, 4326) NOT NULL,
    area_sqkm DOUBLE PRECISION,
    checksum TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (location_id, version_number)
);

-- Spatial index for PostGIS queries
CREATE INDEX IF NOT EXISTS idx_canonical_locations_geom ON public.canonical_locations USING GIST (geom);

-- 4. Dispute Telemetry & Observations
CREATE TABLE IF NOT EXISTS public.dispute_observations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    location_id UUID REFERENCES public.canonical_locations(id),
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

-- 5. Statutory Documents & pgvector Embeddings for RAG
CREATE TABLE IF NOT EXISTS public.documents (
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
    is_public BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.document_chunks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID REFERENCES public.documents(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    section_title TEXT,
    page_number INT,
    content_text TEXT NOT NULL,
    embedding VECTOR(1536)
);

CREATE TABLE IF NOT EXISTS public.document_versions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES public.documents(id) ON DELETE CASCADE,
    version_number INT NOT NULL,
    source_snapshot_id UUID REFERENCES public.source_snapshots(id),
    checksum TEXT NOT NULL,
    storage_uri TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (document_id, version_number)
);

-- Vector HNSW Index for ultra-fast semantic similarity search
CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding ON public.document_chunks USING hnsw (embedding vector_cosine_ops);

-- 6. Policy Simulation Scenarios
CREATE TABLE IF NOT EXISTS public.simulation_runs (
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

-- 7. Collaborative Workspaces & Projects
CREATE TABLE IF NOT EXISTS public.projects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID,
    name TEXT NOT NULL,
    description TEXT,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.project_members (
    project_id UUID NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    membership_role TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (project_id, user_id)
);

CREATE TABLE IF NOT EXISTS public.annotations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES public.users(id),
    location_id UUID REFERENCES public.canonical_locations(id),
    body TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    assignee_user_id UUID REFERENCES public.users(id),
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    due_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.project_milestones (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned',
    due_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.collections (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, name)
);

CREATE TABLE IF NOT EXISTS public.saved_maps (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    collection_id UUID REFERENCES public.collections(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    map_state JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.project_comments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID REFERENCES public.projects(id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    user_name TEXT NOT NULL,
    comment_text TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 8. Innovation Hub & Challenges
CREATE TABLE IF NOT EXISTS public.innovation_challenges (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    eligibility TEXT NOT NULL,
    deadline TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Active'
);

CREATE TABLE IF NOT EXISTS public.innovation_submissions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    challenge_id UUID REFERENCES public.innovation_challenges(id) ON DELETE CASCADE,
    team_name TEXT NOT NULL,
    lead_user TEXT NOT NULL,
    proposal_summary TEXT NOT NULL,
    score DOUBLE PRECISION DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'Submitted',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.innovation_teams (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    challenge_id UUID NOT NULL REFERENCES public.innovation_challenges(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    lead_user_id UUID REFERENCES public.users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (challenge_id, name)
);

CREATE TABLE IF NOT EXISTS public.innovation_team_members (
    team_id UUID NOT NULL REFERENCES public.innovation_teams(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    member_role TEXT NOT NULL DEFAULT 'member',
    PRIMARY KEY (team_id, user_id)
);

CREATE TABLE IF NOT EXISTS public.submission_versions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    submission_id UUID NOT NULL REFERENCES public.innovation_submissions(id) ON DELETE CASCADE,
    version_number INT NOT NULL,
    proposal_summary TEXT NOT NULL,
    submitted_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (submission_id, version_number)
);

CREATE TABLE IF NOT EXISTS public.innovation_reviews (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    submission_id UUID NOT NULL REFERENCES public.innovation_submissions(id) ON DELETE CASCADE,
    reviewer_user_id UUID NOT NULL REFERENCES public.users(id),
    score DOUBLE PRECISION NOT NULL CHECK (score >= 0 AND score <= 100),
    decision TEXT NOT NULL,
    notes TEXT,
    reviewed_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (submission_id, reviewer_user_id)
);

CREATE TABLE IF NOT EXISTS public.pilots (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    submission_id UUID NOT NULL REFERENCES public.innovation_submissions(id),
    sponsor_org_id UUID REFERENCES public.organizations(id),
    status TEXT NOT NULL DEFAULT 'planned',
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS public.pilot_milestones (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    pilot_id UUID NOT NULL REFERENCES public.pilots(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned',
    due_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS public.datasets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    description TEXT,
    source_id UUID REFERENCES public.sources(id),
    owner_user_id UUID REFERENCES public.users(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.dataset_versions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dataset_id UUID NOT NULL REFERENCES public.datasets(id) ON DELETE CASCADE,
    version_number INT NOT NULL,
    source_snapshot_id UUID REFERENCES public.source_snapshots(id),
    schema_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    checksum TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (dataset_id, version_number)
);

CREATE TABLE IF NOT EXISTS public.gis_layers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    layer_type TEXT NOT NULL,
    owner_user_id UUID REFERENCES public.users(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.gis_layer_versions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    layer_id UUID NOT NULL REFERENCES public.gis_layers(id) ON DELETE CASCADE,
    version_number INT NOT NULL,
    dataset_version_id UUID REFERENCES public.dataset_versions(id),
    source_snapshot_id UUID REFERENCES public.source_snapshots(id),
    style_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (layer_id, version_number)
);

CREATE TABLE IF NOT EXISTS public.indicator_definitions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    unit TEXT,
    methodology TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.indicator_observations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    indicator_id UUID NOT NULL REFERENCES public.indicator_definitions(id) ON DELETE CASCADE,
    location_id UUID REFERENCES public.canonical_locations(id),
    dataset_version_id UUID REFERENCES public.dataset_versions(id),
    observed_at TIMESTAMPTZ NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    quality_status TEXT NOT NULL DEFAULT 'unverified',
    UNIQUE (indicator_id, location_id, observed_at)
);

CREATE TABLE IF NOT EXISTS public.simulation_model_versions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    model_name TEXT NOT NULL,
    version TEXT NOT NULL,
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    published_at TIMESTAMPTZ,
    UNIQUE (model_name, version)
);

CREATE TABLE IF NOT EXISTS public.exports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    requested_by UUID NOT NULL REFERENCES public.users(id),
    export_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    storage_uri TEXT,
    checksum TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- 9. Background Jobs & System Audit Trail
CREATE TABLE IF NOT EXISTS public.background_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Pending',
    progress_pct DOUBLE PRECISION DEFAULT 0.0,
    error_log TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.audit_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id TEXT NOT NULL,
    action TEXT NOT NULL,
    resource TEXT NOT NULL,
    ip_address TEXT,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_boundary_versions_geom ON public.boundary_versions USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_indicator_observations_location ON public.indicator_observations (location_id, observed_at);
CREATE INDEX IF NOT EXISTS idx_audit_events_resource ON public.audit_events (resource, timestamp);

-- 10. Vector Similarity Search Function for RAG
CREATE OR REPLACE FUNCTION match_document_chunks (
  query_embedding VECTOR(1536),
  match_threshold FLOAT,
  match_count INT
)
RETURNS TABLE (
  id UUID,
  document_id UUID,
  chunk_index INT,
  section_title TEXT,
  content_text TEXT,
  similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    document_chunks.id,
    document_chunks.document_id,
    document_chunks.chunk_index,
    document_chunks.section_title,
    document_chunks.content_text,
    1 - (document_chunks.embedding <=> query_embedding) AS similarity
  FROM document_chunks
  WHERE 1 - (document_chunks.embedding <=> query_embedding) > match_threshold
  ORDER BY document_chunks.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;
"""
