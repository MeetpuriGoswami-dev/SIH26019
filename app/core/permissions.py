"""
BHUMI-NITI: Server-Side Role-Based Access Control (RBAC) & Permission Engine
Roles: Public, Researcher, Institution, Government Official, Administrator
"""
import os
from enum import Enum
from typing import Optional

from fastapi import HTTPException, Depends, Header

from app.core.config import settings
from app.core.database import get_db_connection
from app.core.security import decode_access_token


class UserRole(str, Enum):
    PUBLIC = "Public"
    RESEARCHER = "Researcher"
    INSTITUTION = "Institution"
    GOV_OFFICIAL = "Government Official"
    ADMINISTRATOR = "Administrator"


ROLE_HIERARCHY = {
    UserRole.PUBLIC: 1,
    UserRole.RESEARCHER: 2,
    UserRole.INSTITUTION: 3,
    UserRole.GOV_OFFICIAL: 4,
    UserRole.ADMINISTRATOR: 5,
}


class CurrentUser:
    def __init__(self, user_id: str, email: str, role: UserRole, org_id: Optional[str] = None):
        self.user_id = user_id
        self.email = email
        self.role = role
        self.org_id = org_id


def get_current_user_from_token_or_header(
    authorization: Optional[str] = Header(None),
    x_demo_role: Optional[str] = Header(None, alias="X-Demo-Role-Override")
) -> CurrentUser:
    """
    Validate a bearer token when present. Invalid bearer tokens fail with HTTP 401.
    Anonymous access remains public only when no authorization header is supplied.
    Demo-role overrides are disabled outside explicit demo mode.
    """
    if authorization is not None:
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Invalid Authorization header format. Use 'Bearer <token>'.")

        token = authorization.split(" ", 1)[1].strip()
        if not token:
            raise HTTPException(status_code=401, detail="Missing bearer token.")

        payload = decode_access_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid or expired bearer token.")

        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Bearer token missing user identifier.")

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, email, role, org_id FROM users WHERE id = ? LIMIT 1",
                (user_id,),
            )
            row = cursor.fetchone()
            conn.close()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Authentication backend unavailable: {exc}") from exc

        if not row:
            raise HTTPException(status_code=401, detail="User account no longer exists or token is invalid.")

        token_email = (payload.get("email") or "").lower()
        db_email = (row["email"] if isinstance(row, dict) else row[1]).lower()
        if token_email and token_email != db_email:
            raise HTTPException(status_code=401, detail="Token email does not match current account.")

        try:
            role = UserRole(row["role"] if isinstance(row, dict) else row[2])
        except ValueError:
            role = UserRole.PUBLIC

        return CurrentUser(
            user_id=row["id"] if isinstance(row, dict) else row[0],
            email=row["email"] if isinstance(row, dict) else row[1],
            role=role,
            org_id=row["org_id"] if isinstance(row, dict) else row[3],
        )

    demo_mode = settings.DEMO_MODE and os.getenv("ENVIRONMENT", "development").lower() != "production"
    if demo_mode and x_demo_role:
        try:
            demo_role = UserRole(x_demo_role)
            return CurrentUser(
                user_id="demo-user-123",
                email="demo@bhuminiti.gov.in",
                role=demo_role,
            )
        except ValueError:
            pass

    return CurrentUser(user_id="anonymous", email="public@bhuminiti.gov.in", role=UserRole.PUBLIC)


def require_role(min_role: UserRole):
    """Dependency guard requiring at least `min_role` in hierarchy."""
    def role_checker(current_user: CurrentUser = Depends(get_current_user_from_token_or_header)):
        user_level = ROLE_HIERARCHY.get(current_user.role, 1)
        required_level = ROLE_HIERARCHY.get(min_role, 1)

        if user_level < required_level:
            raise HTTPException(
                status_code=403,
                detail=f"Access Denied: Action requires '{min_role.value}' role privileges. Your current role is '{current_user.role.value}'.",
            )
        return current_user

    return role_checker
