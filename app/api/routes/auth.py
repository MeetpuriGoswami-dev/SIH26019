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
    is_approved = 0 if requested in PRIVILEGED_ROLES else 1
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
    """
    Request a role upgrade (e.g. Public → Researcher, Researcher → Institution).
    Administrators process these via the admin panel.
    """
    valid_roles = {r.value for r in UserRole}
    if payload.requested_role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"Invalid role. Valid roles: {valid_roles}")

    if user.user_id == "anonymous":
        raise HTTPException(status_code=401, detail="Authentication required to request role upgrade.")

    conn = get_db_connection()
    cursor = conn.cursor()
    request_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    cursor.execute(
        """
        INSERT INTO background_jobs (id, job_type, status, progress_pct, error_log, created_at, updated_at)
        VALUES (?, 'Role_Upgrade_Request', 'Pending', 0.0, ?, ?, ?)
        """,
        (request_id, f"user:{user.user_id}|requested:{payload.requested_role}|justification:{payload.justification}", now, now),
    )
    conn.commit()
    conn.close()

    return {
        "status": "submitted",
        "request_id": request_id,
        "message": f"Role upgrade request to '{payload.requested_role}' submitted. An administrator will review your justification.",
    }


@router.get("/pending-approvals", summary="List pending role upgrade requests [Admin only]")
def list_pending_approvals(user: CurrentUser = Depends(require_role(UserRole.ADMINISTRATOR))):
    """Administrator endpoint: list all pending role upgrade requests."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, error_log, created_at FROM background_jobs WHERE job_type = 'Role_Upgrade_Request' AND status = 'Pending'"
    )
    rows = cursor.fetchall()
    conn.close()

    return {
        "pending_requests": [
            {"request_id": r["id"], "details": r["error_log"], "submitted_at": r["created_at"]}
            for r in rows
        ]
    }
