"""Quick Connect invite endpoints.

POST /quick-invite/        — auth'd; technician creates a one-time token
GET  /quick-invite/{token} — public; returns metadata about the invite
                              (used by the public /j/[token] landing page
                              to render the right download buttons)
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import audit
from ..database import get_db
from ..models.join_token import JoinToken
from ..models.user import User
from .auth import get_current_user

router = APIRouter()

QUICK_INVITE_TTL_S = int(os.getenv("QUICK_INVITE_TTL_S", str(30 * 60)))  # 30 min default
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://remoteconnect.ikieguy.online")


class QuickInviteCreate(BaseModel):
    note: Optional[str] = None  # informational only — appears in audit log


class QuickInviteResponse(BaseModel):
    token: str
    url: str
    expires_at: datetime
    expires_in: int


class QuickInviteInfo(BaseModel):
    valid: bool
    reason: Optional[str] = None
    expires_in: Optional[int] = None
    technician_email: Optional[str] = None


def _client_ip(req: Request) -> Optional[str]:
    return req.client.host if req.client else None


@router.post("/", response_model=QuickInviteResponse)
async def create_invite(
    payload: QuickInviteCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    token = secrets.token_urlsafe(18)  # ~24 chars, URL-safe
    expires = datetime.utcnow() + timedelta(seconds=QUICK_INVITE_TTL_S)

    db.add(
        JoinToken(
            token=token,
            technician_id=current_user.id,
            expires_at=expires,
            status="pending",
        )
    )
    await db.commit()

    await audit(
        db,
        "quick_invite.created",
        user_id=current_user.id,
        actor_ip=_client_ip(request),
        detail={"ttl_seconds": QUICK_INVITE_TTL_S, "note": payload.note},
    )

    return QuickInviteResponse(
        token=token,
        url=f"{PUBLIC_BASE_URL}/j/{token}",
        expires_at=expires,
        expires_in=QUICK_INVITE_TTL_S,
    )


@router.get("/{token}", response_model=QuickInviteInfo)
async def get_invite_info(token: str, db: AsyncSession = Depends(get_db)):
    """Public endpoint — used by the /j/[token] landing page to know if the
    invite is still valid and who issued it. Does not return the technician's
    user_id, only their email (for "shared by alice@…")."""
    q = await db.execute(select(JoinToken).where(JoinToken.token == token))
    invite = q.scalar_one_or_none()
    if invite is None:
        return QuickInviteInfo(valid=False, reason="not found")
    if invite.status == "redeemed":
        return QuickInviteInfo(valid=False, reason="already used")
    if invite.expires_at and invite.expires_at < datetime.utcnow():
        return QuickInviteInfo(valid=False, reason="expired")

    user_q = await db.execute(select(User).where(User.id == invite.technician_id))
    tech = user_q.scalar_one_or_none()

    remaining = int((invite.expires_at - datetime.utcnow()).total_seconds())
    return QuickInviteInfo(
        valid=True,
        expires_in=max(0, remaining),
        technician_email=tech.email if tech else None,
    )
