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

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://zmdecwnywqfnpkmltoft.supabase.co").rstrip("/")
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
    Enables PostGIS & pgvector extensions and creates all 13 Bhumi-Niti schema tables.
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
    created_at TIMESTAMPTZ DEFAULT NOW()
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
