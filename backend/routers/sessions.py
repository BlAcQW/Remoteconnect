import os
import time
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from jose import jwt
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import audit
from ..database import get_db
from ..integrations import daily
from ..models.machine import Machine
from ..models.session import Session
from ..models.user import User
from ..websocket_manager import manager
from .auth import get_current_user

router = APIRouter()

JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
GUEST_AUDIENCE = "rc-guest"
GUEST_TOKEN_TTL_S = int(os.getenv("GUEST_TOKEN_TTL_S", str(60 * 60)))  # 1h

# Video transport. "mjpeg" (default) streams JPEG frames over the agent
# WebSocket — works on every OS, no third-party SDK. "daily" keeps the
# Daily.co WebRTC pipeline (legacy, requires daily-python on the agent).
VIDEO_BACKEND = os.getenv("RC_VIDEO_BACKEND", "mjpeg").lower()


class SessionCreate(BaseModel):
    machine_id: str
    require_consent: bool = False


class SessionResponse(BaseModel):
    id: str
    machine_id: str
    technician_id: str
    daily_room_url: Optional[str]
    daily_room_name: Optional[str] = None
    status: str
    started_at: Optional[datetime]
    ended_at: Optional[datetime]
    created_at: datetime
    meeting_token: Optional[str] = None


class MeetingTokenResponse(BaseModel):
    room_url: str
    room_name: Optional[str]
    token: Optional[str]
    role: str


class HandoffRequest(BaseModel):
    to_email: EmailStr


class GuestInviteResponse(BaseModel):
    token: str
    url: str
    expires_in: int


def _room_name_from_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    return url.rstrip("/").rsplit("/", 1)[-1] or None


def _client_ip(req: Request) -> Optional[str]:
    return req.client.host if req.client else None


@router.post("/", response_model=SessionResponse)
async def create_session(
    session_data: SessionCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Machine).where(Machine.id == session_data.machine_id))
    machine = result.scalar_one_or_none()
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")
    if not machine.is_online:
        raise HTTPException(status_code=400, detail="Machine is offline")

    initial_status = "consent_required" if session_data.require_consent else "pending"
    db_session = Session(
        machine_id=session_data.machine_id,
        technician_id=current_user.id,
        status=initial_status,
    )
    db.add(db_session)
    await db.commit()
    await db.refresh(db_session)

    # Video transport selection. MJPEG (default) skips Daily.co entirely —
    # frames stream over the existing agent WebSocket. Daily mode is kept
    # for back-compat / future audio support.
    use_daily = VIDEO_BACKEND == "daily"
    room: Optional[daily.Room] = None
    technician_token: Optional[str] = None
    agent_token: Optional[str] = None
    room_url: Optional[str] = None
    room_name: Optional[str] = None

    if use_daily:
        try:
            room = await daily.create_room(db_session.id)
        except Exception as e:
            await db.delete(db_session)
            await db.commit()
            raise HTTPException(status_code=502, detail=f"Daily.co room creation failed: {e}")

        await db.execute(
            update(Session).where(Session.id == db_session.id).values(daily_room_url=room["url"])
        )
        await db.commit()
        db_session.daily_room_url = room["url"]
        room_url = room["url"]
        room_name = room["name"]

        technician_token = await daily.create_meeting_token(
            room_name=room["name"], user_name=f"tech-{current_user.email}", is_owner=True,
        )
        agent_token = await daily.create_meeting_token(
            room_name=room["name"], user_name=f"agent-{machine.id}", is_owner=False,
        )

    common_payload = {
        "session_id": db_session.id,
        "video_backend": VIDEO_BACKEND,
        "room_url": room_url,
        "room_name": room_name,
        "meeting_token": agent_token,
        "timestamp": datetime.utcnow().isoformat(),
    }
    if session_data.require_consent:
        # Don't autostart capture; ask the remote user first.
        await manager.send_to_machine(
            session_data.machine_id,
            {**common_payload, "type": "consent_required",
             "technician_email": current_user.email},
        )
    else:
        await manager.send_to_machine(
            session_data.machine_id,
            {**common_payload, "type": "start_session"},
        )

    await audit(
        db, "session.create",
        user_id=current_user.id, machine_id=machine.id, session_id=db_session.id,
        actor_ip=_client_ip(request),
        detail={"require_consent": session_data.require_consent, "video_backend": VIDEO_BACKEND},
    )

    return SessionResponse(
        id=db_session.id,
        machine_id=db_session.machine_id,
        technician_id=db_session.technician_id,
        daily_room_url=db_session.daily_room_url,
        daily_room_name=room_name,
        status=db_session.status,
        started_at=db_session.started_at,
        ended_at=db_session.ended_at,
        created_at=db_session.created_at,
        meeting_token=technician_token,
    )


@router.get("/", response_model=List[SessionResponse])
async def get_sessions(
    status_filter: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Session).order_by(Session.created_at.desc())
    if status_filter:
        query = query.where(Session.status == status_filter)

    result = await db.execute(query)
    rows = result.scalars().all()
    return [
        SessionResponse(
            id=s.id,
            machine_id=s.machine_id,
            technician_id=s.technician_id,
            daily_room_url=s.daily_room_url,
            daily_room_name=_room_name_from_url(s.daily_room_url),
            status=s.status,
            started_at=s.started_at,
            ended_at=s.ended_at,
            created_at=s.created_at,
        )
        for s in rows
    ]


@router.get("/{session_id}/meeting-token", response_model=MeetingTokenResponse)
async def get_meeting_token(
    session_id: str,
    role: str = Query("technician", regex="^(technician|agent)$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.daily_room_url:
        raise HTTPException(status_code=409, detail="Session has no Daily room yet")
    if session.technician_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized for this session")

    room_name = _room_name_from_url(session.daily_room_url)
    user_name = f"tech-{current_user.email}" if role == "technician" else f"agent-{session.machine_id}"
    token = await daily.create_meeting_token(
        room_name=room_name or "", user_name=user_name, is_owner=(role == "technician"),
    )
    return MeetingTokenResponse(
        room_url=session.daily_room_url, room_name=room_name, token=token, role=role,
    )


@router.post("/{session_id}/handoff", response_model=SessionResponse)
async def handoff_session(
    session_id: str,
    payload: HandoffRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.technician_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to hand off this session")
    if session.status == "ended":
        raise HTTPException(status_code=409, detail="Session already ended")

    target_q = await db.execute(select(User).where(User.email == payload.to_email))
    target = target_q.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="Target technician not found")
    if target.id == session.technician_id:
        raise HTTPException(status_code=400, detail="Already owned by this technician")

    await db.execute(
        update(Session).where(Session.id == session_id).values(technician_id=target.id)
    )
    await db.commit()
    await db.refresh(session)

    await manager.send_to_technician(session_id, {
        "type": "session_handoff",
        "from_user": current_user.email,
        "to_user": target.email,
    })
    await audit(
        db, "session.handoff",
        user_id=current_user.id, session_id=session_id,
        actor_ip=_client_ip(request),
        detail={"to_user_id": target.id, "to_email": target.email},
    )

    return SessionResponse(
        id=session.id,
        machine_id=session.machine_id,
        technician_id=session.technician_id,
        daily_room_url=session.daily_room_url,
        daily_room_name=_room_name_from_url(session.daily_room_url),
        status=session.status,
        started_at=session.started_at,
        ended_at=session.ended_at,
        created_at=session.created_at,
    )


@router.post("/{session_id}/guest-invite", response_model=GuestInviteResponse)
async def create_guest_invite(
    session_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.technician_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized for this session")
    if session.status == "ended":
        raise HTTPException(status_code=409, detail="Session already ended")

    if not JWT_SECRET:
        raise HTTPException(status_code=500, detail="server is missing JWT_SECRET")

    expires_at = datetime.utcnow() + timedelta(seconds=GUEST_TOKEN_TTL_S)
    token = jwt.encode(
        {
            "sub": session_id,
            "aud": GUEST_AUDIENCE,
            "iss": "remoteconnect",
            "iat": int(time.time()),
            "exp": int(expires_at.timestamp()),
            "issued_by": current_user.email,
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )
    # The frontend will mount /guest/{token} and connect to /ws/guest/{token}.
    url = f"/guest/{token}"

    await audit(
        db, "guest.invite.created",
        user_id=current_user.id, session_id=session_id,
        actor_ip=_client_ip(request),
        detail={"ttl_seconds": GUEST_TOKEN_TTL_S},
    )
    return GuestInviteResponse(token=token, url=url, expires_in=GUEST_TOKEN_TTL_S)


@router.patch("/{session_id}/end")
async def end_session(
    session_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.technician_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to end this session")

    await db.execute(
        update(Session).where(Session.id == session_id).values(
            status="ended", ended_at=datetime.utcnow(),
        )
    )
    await db.commit()

    room_name = _room_name_from_url(session.daily_room_url)
    if room_name:
        await daily.delete_room(room_name)

    await manager.send_to_machine(
        session.machine_id,
        {
            "type": "end_session",
            "session_id": session_id,
            "timestamp": datetime.utcnow().isoformat(),
        },
    )
    await audit(
        db, "session.end",
        user_id=current_user.id, session_id=session_id, machine_id=session.machine_id,
        actor_ip=_client_ip(request),
    )

    return {"status": "ended"}
