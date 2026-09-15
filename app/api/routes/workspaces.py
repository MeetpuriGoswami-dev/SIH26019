"""
BHUMI-NITI: Collaborative Workspace & Project Management Routes
Multi-tenant workspaces for research teams, government bodies, and institutions.
Supports project creation, membership management, comment threads, and collections.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel

from app.core.permissions import (
    CurrentUser,
    UserRole,
    get_current_user_from_token_or_header,
    require_role,
    ROLE_HIERARCHY,
)
from app.core.database import get_db_connection

router = APIRouter(prefix="/api/v1/workspaces", tags=["Collaborative Workspaces"])


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------

class CreateProjectRequest(BaseModel):
    name: str
    description: Optional[str] = None
    org_id: Optional[str] = None


class AddCommentRequest(BaseModel):
    comment_text: str
    entity_type: Optional[str] = "project"


class CreateOrganisationRequest(BaseModel):
    name: str
    type: str  # Ministry | Department | University | NGO | Enterprise


def _ensure_project_access(cursor, project_id: str, user: CurrentUser) -> None:
    """Allow project members and privileged reviewers to access a project."""
    cursor.execute("SELECT created_by FROM projects WHERE id = ?", (project_id,))
    project = cursor.fetchone()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    is_privileged = ROLE_HIERARCHY.get(user.role, 1) >= ROLE_HIERARCHY.get(UserRole.GOV_OFFICIAL, 4)
    if is_privileged:
        return

    created_by = project["created_by"] if isinstance(project, dict) else project[0]
    if created_by == user.user_id:
        return

    cursor.execute(
        "SELECT 1 FROM project_members WHERE project_id = ? AND user_id = ? LIMIT 1",
        (project_id, user.user_id),
    )
    if not cursor.fetchone():
        raise HTTPException(status_code=403, detail="Access denied: you are not a member of this project.")


# ---------------------------------------------------------------------------
# Organisations
# ---------------------------------------------------------------------------

@router.get("/organisations", summary="List all registered organisations")
def list_organisations(
    user: CurrentUser = Depends(require_role(UserRole.RESEARCHER)),
):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, type, created_at FROM organizations ORDER BY name ASC")
    rows = cursor.fetchall()
    conn.close()
    return {"organisations": [dict(r) for r in rows]}


@router.post("/organisations", summary="Register a new organisation [Institution+]")
def create_organisation(
    payload: CreateOrganisationRequest,
    user: CurrentUser = Depends(require_role(UserRole.INSTITUTION)),
):
    """Create an organisation. Requires Institution or higher role."""
    valid_types = {"Ministry", "Department", "University", "NGO", "Enterprise"}
    if payload.type not in valid_types:
        raise HTTPException(status_code=400, detail=f"Invalid type. Allowed: {valid_types}")

    org_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO organizations (id, name, type, created_at) VALUES (?, ?, ?, ?)",
        (org_id, payload.name, payload.type, now),
    )
    conn.commit()
    conn.close()
    return {"status": "created", "organisation_id": org_id, "name": payload.name, "type": payload.type}


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

@router.get("/projects", summary="List projects accessible to the authenticated user")
def list_projects(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(require_role(UserRole.RESEARCHER)),
):
    """
    Returns all projects. Administrators and Gov Officials see all projects.
    Researcher/Institution users see public projects and their own.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    is_privileged = ROLE_HIERARCHY.get(user.role, 1) >= ROLE_HIERARCHY.get(UserRole.GOV_OFFICIAL, 4)
    if is_privileged:
        cursor.execute(
            "SELECT id, org_id, name, description, created_by, created_at FROM projects ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
    else:
        cursor.execute(
            "SELECT id, org_id, name, description, created_by, created_at FROM projects WHERE created_by = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (user.user_id, limit, offset),
        )
    rows = cursor.fetchall()
    conn.close()
    return {"projects": [dict(r) for r in rows], "limit": limit, "offset": offset}


@router.post("/projects", summary="Create a new research project [Researcher+]")
def create_project(
    payload: CreateProjectRequest,
    user: CurrentUser = Depends(require_role(UserRole.RESEARCHER)),
):
    """Create a new collaborative research project under the authenticated user."""
    project_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO projects (id, org_id, name, description, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, payload.org_id, payload.name, payload.description, user.user_id, now),
    )
    cursor.execute(
        "INSERT INTO project_members (project_id, user_id, membership_role, created_at) VALUES (?, ?, ?, ?)",
        (project_id, user.user_id, "owner", now),
    )
    conn.commit()
    conn.close()
    return {
        "status": "created",
        "project_id": project_id,
        "name": payload.name,
        "created_by": user.user_id,
        "created_at": now,
    }


@router.get("/projects/{project_id}", summary="Get project details")
def get_project(
    project_id: str,
    user: CurrentUser = Depends(require_role(UserRole.RESEARCHER)),
):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found.")

    # Access control: only creator or privileged roles
    is_privileged = ROLE_HIERARCHY.get(user.role, 1) >= ROLE_HIERARCHY.get(UserRole.GOV_OFFICIAL, 4)
    if not is_privileged and row["created_by"] != user.user_id:
        raise HTTPException(status_code=403, detail="Access denied: you are not a member of this project.")

    return dict(row)


@router.delete("/projects/{project_id}", summary="Delete a project [Creator or Admin]")
def delete_project(
    project_id: str,
    user: CurrentUser = Depends(require_role(UserRole.RESEARCHER)),
):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT created_by FROM projects WHERE id = ?", (project_id,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Project not found.")

    is_admin = user.role == UserRole.ADMINISTRATOR
    if not is_admin and row["created_by"] != user.user_id:
        conn.close()
        raise HTTPException(status_code=403, detail="Only the project creator or an Administrator can delete this project.")

    cursor.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    cursor.execute("DELETE FROM project_comments WHERE project_id = ?", (project_id,))
    conn.commit()
    conn.close()
    return {"status": "deleted", "project_id": project_id}


# ---------------------------------------------------------------------------
# Comments / Collaboration Threads
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/comments", summary="List comments on a project")
def list_comments(
    project_id: str,
    user: CurrentUser = Depends(require_role(UserRole.RESEARCHER)),
):
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_project_access(cursor, project_id, user)
    cursor.execute(
        "SELECT id, user_id, user_name, comment_text, created_at FROM project_comments WHERE project_id = ? ORDER BY created_at ASC",
        (project_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    return {"project_id": project_id, "comments": [dict(r) for r in rows]}


@router.post("/projects/{project_id}/comments", summary="Add a comment to a project thread")
def add_comment(
    project_id: str,
    payload: AddCommentRequest,
    user: CurrentUser = Depends(require_role(UserRole.RESEARCHER)),
):
    if not payload.comment_text.strip():
        raise HTTPException(status_code=400, detail="Comment text cannot be empty.")

    comment_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_project_access(cursor, project_id, user)

    cursor.execute(
        "INSERT INTO project_comments (id, project_id, user_id, user_name, comment_text, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (comment_id, project_id, user.user_id, user.email, payload.comment_text.strip(), now),
    )
    conn.commit()
    conn.close()
    return {"status": "created", "comment_id": comment_id, "project_id": project_id, "created_at": now}


@router.delete("/projects/{project_id}/comments/{comment_id}", summary="Delete a comment [Author or Admin]")
def delete_comment(
    project_id: str,
    comment_id: str,
    user: CurrentUser = Depends(require_role(UserRole.RESEARCHER)),
):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM project_comments WHERE id = ? AND project_id = ?", (comment_id, project_id))
    row = cursor.fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Comment not found.")

    if row["user_id"] != user.user_id and user.role != UserRole.ADMINISTRATOR:
        conn.close()
        raise HTTPException(status_code=403, detail="Only the comment author or an Administrator can delete this comment.")

    cursor.execute("DELETE FROM project_comments WHERE id = ?", (comment_id,))
    conn.commit()
    conn.close()
    return {"status": "deleted", "comment_id": comment_id}
