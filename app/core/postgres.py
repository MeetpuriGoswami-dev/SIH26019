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
    """Initialize PostGIS, pgvector extensions and core Bhumi-Niti schema in PostgreSQL."""
    if not is_postgres_configured():
        return False
        
    try:
        conn = get_pg_connection()
        cursor = conn.cursor()
        
        # Extensions
        cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cursor.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')
        
        # Core Tables
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
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """)
        
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_canonical_locations_geom ON canonical_locations USING GIST (geom);
        """)
        
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
        
        conn.commit()
        conn.close()
        logger.info("Successfully initialized PostgreSQL database with PostGIS and pgvector extensions!")
        return True
    except Exception as e:
        logger.warning(f"PostgreSQL initialization warning: {e}")
        return False
