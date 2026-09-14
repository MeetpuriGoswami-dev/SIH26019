"""
BHUMI-NITI: Innovation Hub & Challenge Management Routes
DoLR Land Governance Innovation Challenges, Team Submissions,
Scoring, Pilot approvals, and Showcase management.
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
)
from app.core.database import get_db_connection

router = APIRouter(prefix="/api/v1/innovation", tags=["Innovation Hub"])


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------

class CreateChallengeRequest(BaseModel):
    title: str
    description: str
    eligibility: str
    deadline: str  # ISO date string
    status: Optional[str] = "Active"


class SubmitProposalRequest(BaseModel):
    challenge_id: str
    team_name: str
    proposal_summary: str


class ScoreSubmissionRequest(BaseModel):
    score: float
    status: str  # Submitted | Shortlisted | Pilot_Approved | Rejected


# ---------------------------------------------------------------------------
# Challenges
# ---------------------------------------------------------------------------

@router.get("/challenges", summary="List all active innovation challenges")
def list_challenges(
    status: Optional[str] = Query(None, description="Filter by status: Active | Draft | Completed"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Public endpoint — lists DoLR land governance innovation challenges."""
    conn = get_db_connection()
    cursor = conn.cursor()

    if status:
        cursor.execute(
            "SELECT * FROM innovation_challenges WHERE status = ? ORDER BY deadline ASC LIMIT ? OFFSET ?",
            (status, limit, offset),
        )
    else:
        cursor.execute(
            "SELECT * FROM innovation_challenges ORDER BY deadline ASC LIMIT ? OFFSET ?",
            (limit, offset),
        )
    rows = cursor.fetchall()
    conn.close()
    return {"challenges": [dict(r) for r in rows], "limit": limit, "offset": offset}


@router.post("/challenges", summary="Create a new innovation challenge [Gov Official+]")
def create_challenge(
    payload: CreateChallengeRequest,
    user: CurrentUser = Depends(require_role(UserRole.GOV_OFFICIAL)),
):
    """Create a new challenge. Requires Government Official or Administrator role."""
    valid_statuses = {"Draft", "Active", "Under_Review", "Completed"}
    if payload.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Allowed: {valid_statuses}")

    challenge_id = str(uuid.uuid4())
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO innovation_challenges (id, title, description, eligibility, deadline, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (challenge_id, payload.title, payload.description, payload.eligibility, payload.deadline, payload.status),
    )
    conn.commit()
    conn.close()
    return {
        "status": "created",
        "challenge_id": challenge_id,
        "title": payload.title,
        "deadline": payload.deadline,
    }


@router.get("/challenges/{challenge_id}", summary="Get challenge details")
def get_challenge(challenge_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM innovation_challenges WHERE id = ?", (challenge_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Challenge not found.")
    return dict(row)


@router.patch("/challenges/{challenge_id}", summary="Update challenge status [Gov Official+]")
def update_challenge_status(
    challenge_id: str,
    status: str = Query(..., description="New status: Draft | Active | Under_Review | Completed"),
    user: CurrentUser = Depends(require_role(UserRole.GOV_OFFICIAL)),
):
    valid_statuses = {"Draft", "Active", "Under_Review", "Completed"}
    if status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status: {valid_statuses}")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE innovation_challenges SET status = ? WHERE id = ?", (status, challenge_id))
    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Challenge not found.")
    conn.commit()
    conn.close()
    return {"status": "updated", "challenge_id": challenge_id, "new_status": status}


# ---------------------------------------------------------------------------
# Submissions
# ---------------------------------------------------------------------------

@router.post("/submissions", summary="Submit a team proposal to a challenge [Researcher+]")
def submit_proposal(
    payload: SubmitProposalRequest,
    user: CurrentUser = Depends(require_role(UserRole.RESEARCHER)),
):
    """Submit a team proposal. Requires Researcher or higher role."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, status FROM innovation_challenges WHERE id = ?", (payload.challenge_id,))
    challenge = cursor.fetchone()
    if not challenge:
        conn.close()
        raise HTTPException(status_code=404, detail="Challenge not found.")
    if challenge["status"] != "Active":
        conn.close()
        raise HTTPException(status_code=400, detail="Submissions are only accepted for Active challenges.")

    sub_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    cursor.execute(
        """
        INSERT INTO innovation_submissions (id, challenge_id, team_name, lead_user, proposal_summary, score, status, created_at)
        VALUES (?, ?, ?, ?, ?, 0.0, 'Submitted', ?)
        """,
        (sub_id, payload.challenge_id, payload.team_name, user.user_id, payload.proposal_summary, now),
    )
    conn.commit()
    conn.close()
    return {
        "status": "submitted",
        "submission_id": sub_id,
        "challenge_id": payload.challenge_id,
        "team_name": payload.team_name,
        "created_at": now,
    }


@router.get("/submissions", summary="List submissions [Gov Official+]")
def list_submissions(
    challenge_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(require_role(UserRole.GOV_OFFICIAL)),
):
    """List all submissions. Optionally filter by challenge or status."""
    conn = get_db_connection()
    cursor = conn.cursor()

    conditions, params = [], []
    if challenge_id:
        conditions.append("challenge_id = ?")
        params.append(challenge_id)
    if status:
        conditions.append("status = ?")
        params.append(status)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    cursor.execute(
        f"SELECT * FROM innovation_submissions {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    )
    rows = cursor.fetchall()
    conn.close()
    return {"submissions": [dict(r) for r in rows], "limit": limit, "offset": offset}


@router.patch("/submissions/{submission_id}/score", summary="Score and update submission status [Gov Official+]")
def score_submission(
    submission_id: str,
    payload: ScoreSubmissionRequest,
    user: CurrentUser = Depends(require_role(UserRole.GOV_OFFICIAL)),
):
    """Score a submission and update its status. Requires Government Official or higher."""
    valid_statuses = {"Submitted", "Shortlisted", "Pilot_Approved", "Rejected"}
    if payload.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Allowed: {valid_statuses}")
    if not (0.0 <= payload.score <= 100.0):
        raise HTTPException(status_code=400, detail="Score must be between 0.0 and 100.0.")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE innovation_submissions SET score = ?, status = ? WHERE id = ?",
        (payload.score, payload.status, submission_id),
    )
    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Submission not found.")
    conn.commit()
    conn.close()
    return {
        "status": "scored",
        "submission_id": submission_id,
        "new_score": payload.score,
        "new_status": payload.status,
    }


@router.get("/showcase", summary="Public showcase of Pilot_Approved submissions")
def get_showcase(limit: int = Query(20, ge=1, le=100)):
    """Returns publicly visible pilot-approved innovation submissions for the showcase."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT s.id, s.team_name, s.proposal_summary, s.score, s.created_at,
               c.title as challenge_title
        FROM innovation_submissions s
        JOIN innovation_challenges c ON s.challenge_id = c.id
        WHERE s.status = 'Pilot_Approved'
        ORDER BY s.score DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = cursor.fetchall()
    conn.close()
    return {"showcase": [dict(r) for r in rows]}
