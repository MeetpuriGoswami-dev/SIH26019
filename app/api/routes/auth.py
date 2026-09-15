"""
BHUMI-NITI: Authentication & Identity API Routes
Handles user registration, login, profile, and role management.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr

from app.core.database import get_db_connection
from app.core.security import hash_password, verify_password, create_access_token
from app.core.permissions import (
    UserRole,
    CurrentUser,
    get_current_user_from_token_or_header,
    require_role,
)

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication & Identity"])


# ---------------------------------------------------------------------------
# Request / Response Schemas
# ---------------------------------------------------------------------------

class UserRegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str
    requested_role: Optional[str] = "Public"


class UserLoginRequest(BaseModel):
    email: str
    password: str


class RoleUpgradeRequest(BaseModel):
    requested_role: str
    justification: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/register", summary="Register a new user account")
def register_user(payload: UserRegisterRequest):
    """
    Register a new user. Public and Researcher roles are auto-approved.
    Institution, Government Official, and Administrator roles are created as
    pending and must be approved by an Administrator.
    """
    PRIVILEGED_ROLES = {"Government Official", "Institution", "Administrator"}
    requested = payload.requested_role or "Public"

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM users WHERE email = ?", (payload.email.lower(),))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="Email already registered.")

    user_id = str(uuid.uuid4())
    pw_hash = hash_password(payload.password)
    now = datetime.now(timezone.utc).isoformat()
    # Privileged roles start unapproved; Public/Researcher auto-approved
    is_approved = requested not in PRIVILEGED_ROLES
    assigned_role = requested if requested not in PRIVILEGED_ROLES else "Public"

    cursor.execute(
        """
        INSERT INTO users (id, email, password_hash, full_name, role, is_approved, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, payload.email.lower(), pw_hash, payload.full_name, assigned_role, is_approved, now),
    )
    conn.commit()
    conn.close()

    token = create_access_token({"sub": user_id, "email": payload.email, "role": assigned_role})
    return {
        "status": "success",
        "message": (
            "Registration successful. Your role request is pending administrator approval."
            if requested in PRIVILEGED_ROLES
            else "User registered successfully."
        ),
        "user_id": user_id,
        "access_token": token,
        "token_type": "bearer",
        "role": assigned_role,
    }


@router.post("/login", summary="Authenticate and obtain JWT token")
def login_user(payload: UserLoginRequest):
    """Login with email and password. Returns a signed JWT access token."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, email, password_hash, full_name, role, is_approved FROM users WHERE email = ?",
        (payload.email.lower(),),
    )
    row = cursor.fetchone()
    conn.close()

    if not row or not verify_password(payload.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    if not row["is_approved"]:
        raise HTTPException(
            status_code=403,
            detail="Account pending administrator approval. Contact bhuminiti-admin@dor.gov.in.",
        )

    token = create_access_token({"sub": row["id"], "email": row["email"], "role": row["role"]})
    return {
        "status": "success",
        "access_token": token,
        "token_type": "bearer",
        "role": row["role"],
        "full_name": row["full_name"],
    }


@router.get("/me", summary="Get authenticated user profile")
def get_current_user_profile(user: CurrentUser = Depends(get_current_user_from_token_or_header)):
    """Return JWT-authenticated identity, role, and organisation membership."""
    return {
        "user_id": user.user_id,
        "email": user.email,
        "role": user.role.value,
        "organization_id": user.org_id,
    }


@router.post("/request-role-upgrade", summary="Request elevated role privileges")
def request_role_upgrade(
    payload: RoleUpgradeRequest,
    user: CurrentUser = Depends(get_current_user_from_token_or_header),
):
    """Create a persisted role-upgrade request for admin review."""
    valid_roles = {r.value for r in UserRole}
    if payload.requested_role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"Invalid role. Valid roles: {valid_roles}")

    if user.user_id == "anonymous":
        raise HTTPException(status_code=401, detail="Authentication required to request role upgrade.")

    conn = get_db_connection()
    cursor = conn.cursor()
    request_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    justification = (payload.justification or "").strip()

    cursor.execute(
        """
        INSERT INTO role_requests (id, user_id, requested_role, justification, status, created_at)
        VALUES (?, ?, ?, ?, 'Pending', ?)
        """,
        (request_id, user.user_id, payload.requested_role, justification, now),
    )
    cursor.execute(
        """
        INSERT INTO background_jobs (id, job_type, status, progress_pct, error_log, created_at, updated_at)
        VALUES (?, 'Role_Upgrade_Request', 'Pending', 0.0, ?, ?, ?)
        """,
        (
            request_id,
            f"user:{user.user_id}|requested:{payload.requested_role}|justification:{justification}",
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()

    return {
        "status": "submitted",
        "request_id": request_id,
        "message": f"Role upgrade request to '{payload.requested_role}' submitted. An administrator will review your justification.",
    }


@router.get("/pending-approvals", summary="List pending role upgrade requests [Government Official+]")
def list_pending_approvals(user: CurrentUser = Depends(require_role(UserRole.GOV_OFFICIAL))):
    """Government Official or Administrator review endpoint for pending role upgrade requests."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT rr.id, rr.user_id, rr.requested_role, rr.justification, rr.created_at,
               u.email, u.full_name
        FROM role_requests rr
        JOIN users u ON u.id = rr.user_id
        WHERE rr.status = 'Pending'
        ORDER BY rr.created_at ASC
        """
    )
    rows = cursor.fetchall()
    conn.close()

    return {
        "pending_requests": [
            {
                "request_id": r["id"],
                "user_id": r["user_id"],
                "email": r["email"],
                "full_name": r["full_name"],
                "requested_role": r["requested_role"],
                "justification": r["justification"],
                "submitted_at": r["created_at"],
            }
            for r in rows
        ]
    }


@router.post("/role-requests/{request_id}/approve", summary="Approve a role upgrade request [Government Official+]")
def approve_role_request(
    request_id: str,
    user: CurrentUser = Depends(require_role(UserRole.GOV_OFFICIAL)),
):
    """Approve a pending role request and update the user's current role."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, user_id, requested_role, justification FROM role_requests WHERE id = ? AND status = 'Pending'",
        (request_id,),
    )
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Pending role request not found.")

    requested_role = row["requested_role"]
    valid_roles = {r.value for r in UserRole}
    if requested_role not in valid_roles:
        conn.close()
        raise HTTPException(status_code=400, detail=f"Invalid requested role: {requested_role}")

    cursor.execute(
        "UPDATE users SET role = ?, is_approved = ? WHERE id = ?",
        (requested_role, True, row["user_id"]),
    )
    reviewed_at = datetime.now(timezone.utc).isoformat()
    cursor.execute(
        "UPDATE role_requests SET status = 'Approved', reviewer_user_id = ?, reviewed_at = ?, decision_note = ? WHERE id = ?",
        (user.user_id, reviewed_at, f"Approved by {user.email}", request_id),
    )
    cursor.execute(
        "UPDATE background_jobs SET status = 'Completed', progress_pct = 100.0, error_log = ?, updated_at = ? WHERE id = ?",
        (f"approved:{requested_role}|reviewer:{user.email}|user:{row['user_id']}", reviewed_at, request_id),
    )
    conn.commit()
    conn.close()

    return {
        "status": "approved",
        "request_id": request_id,
        "user_id": row["user_id"],
        "approved_role": requested_role,
        "reviewed_by": user.user_id,
    }


@router.post("/role-requests/{request_id}/reject", summary="Reject a role upgrade request [Government Official+]")
def reject_role_request(
    request_id: str,
    user: CurrentUser = Depends(require_role(UserRole.GOV_OFFICIAL)),
):
    """Reject a pending role request without updating the user's role."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, user_id, requested_role FROM role_requests WHERE id = ? AND status = 'Pending'",
        (request_id,),
    )
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Pending role request not found.")

    reviewed_at = datetime.now(timezone.utc).isoformat()
    cursor.execute(
        "UPDATE role_requests SET status = 'Rejected', reviewer_user_id = ?, reviewed_at = ?, decision_note = ? WHERE id = ?",
        (user.user_id, reviewed_at, f"Rejected by {user.email}", request_id),
    )
    cursor.execute(
        "UPDATE background_jobs SET status = 'Rejected', progress_pct = 100.0, error_log = ?, updated_at = ? WHERE id = ?",
        (f"rejected:{row['requested_role']}|reviewer:{user.email}|user:{row['user_id']}", reviewed_at, request_id),
    )
    conn.commit()
    conn.close()

    return {
        "status": "rejected",
        "request_id": request_id,
        "user_id": row["user_id"],
        "requested_role": row["requested_role"],
        "reviewed_by": user.user_id,
    }
