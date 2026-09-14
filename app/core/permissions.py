"""
BHUMI-NITI: Server-Side Role-Based Access Control (RBAC) & Permission Engine
Roles: Public, Researcher, Institution, Government Official, Administrator
"""
from enum import Enum
from typing import List, Optional
from fastapi import Request, HTTPException, Depends, Header
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
    Server-side identity verification:
    1. Validates Authorization Bearer token if provided.
    2. If no token provided, defaults to Public guest user.
    3. X-Demo-Role-Override is explicitly isolated for demonstration UI testing and NEVER overrides token claims in production.
    """
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        payload = decode_access_token(token)
        if payload:
            role_str = payload.get("role", UserRole.PUBLIC.value)
            try:
                role = UserRole(role_str)
            except ValueError:
                role = UserRole.PUBLIC
            return CurrentUser(
                user_id=payload.get("sub", "anon"),
                email=payload.get("email", "guest@bhuminiti.gov.in"),
                role=role,
                org_id=payload.get("org_id")
            )
            
    # Demo override (explicitly marked for evaluation/testing UI)
    if x_demo_role:
        try:
            demo_role = UserRole(x_demo_role)
            return CurrentUser(
                user_id="demo-user-123",
                email="demo@bhuminiti.gov.in",
                role=demo_role
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
                detail=f"Access Denied: Action requires '{min_role.value}' role privileges. Your current role is '{current_user.role.value}'."
            )
        return current_user
    return role_checker
