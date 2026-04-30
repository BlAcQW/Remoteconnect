import secrets
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import audit
from ..database import get_db
from ..integrations import daily
from ..models.audit_log import AuditLog
from ..models.file_transfer import FileTransfer
from ..models.join_token import JoinToken
from ..models.machine import Machine
from ..models.session import Session
from ..models.user import User
from .auth import get_current_user

router = APIRouter()


class MachineCreate(BaseModel):
    name: str
    hostname: Optional[str] = None
    os: Optional[str] = None
    ip_address: Optional[str] = None
    # Optional Quick Connect token. When present, registration redeems the
    # token, links the machine to the technician who issued it, and pre-
    # creates a Session in `consent_required` state so the technician can
    # jump straight in.
    join_token: Optional[str] = None


class MachineResponse(BaseModel):
    id: str
    name: str
    hostname: Optional[str]
    os: Optional[str]
    ip_address: Optional[str]
    last_seen: Optional[datetime]
    is_online: bool
    created_at: datetime


def _client_ip(req: Request) -> Optional[str]:
    return req.client.host if req.client else None


@router.post("/register", response_model=dict)
async def register_machine(
    machine: MachineCreate, request: Request, db: AsyncSession = Depends(get_db)
):
    """Register a new agent. Optionally redeem a Quick Connect ``join_token``
    in the same call to also pre-create a Session for the issuing technician."""
    invite: Optional[JoinToken] = None
    if machine.join_token:
        q = await db.execute(
            select(JoinToken).where(JoinToken.token == machine.join_token)
        )
        invite = q.scalar_one_or_none()
        if invite is None:
            raise HTTPException(status_code=404, detail="join_token not found")
        if invite.status == "redeemed":
            raise HTTPException(status_code=410, detail="join_token already used")
        if invite.expires_at and invite.expires_at < datetime.utcnow():
            raise HTTPException(status_code=410, detail="join_token expired")

    token = secrets.token_urlsafe(32)
    db_machine = Machine(
        name=machine.name,
        hostname=machine.hostname,
        os=machine.os,
        ip_address=machine.ip_address or _client_ip(request),
        token=token,
    )
    db.add(db_machine)
    await db.commit()
    await db.refresh(db_machine)

    await audit(
        db, "machine.register",
        machine_id=db_machine.id, actor_ip=_client_ip(request),
        detail={
            "name": machine.name, "os": machine.os, "hostname": machine.hostname,
            "via_quick_invite": invite is not None,
        },
    )

    response = {"machine_id": db_machine.id, "token": token}

    if invite is not None:
        # Pre-create a session so the technician's dashboard shows it ready.
        db_session = Session(
            machine_id=db_machine.id,
            technician_id=invite.technician_id,
            status="consent_required",
        )
        db.add(db_session)
        await db.commit()
        await db.refresh(db_session)

        # Daily room (real or mocked depending on DAILY_API_KEY); failures
        # don't block registration — technician can create a fresh session.
        try:
            room = await daily.create_room(db_session.id)
            await db.execute(
                update(Session)
                .where(Session.id == db_session.id)
                .values(daily_room_url=room["url"])
            )
            await db.commit()
        except Exception:
            room = None

        await db.execute(
            update(JoinToken)
            .where(JoinToken.id == invite.id)
            .values(
                status="redeemed",
                used_at=datetime.utcnow(),
                machine_id=db_machine.id,
                session_id=db_session.id,
            )
        )
        await db.commit()

        await audit(
            db, "quick_invite.redeemed",
            user_id=invite.technician_id,
            machine_id=db_machine.id,
            session_id=db_session.id,
            actor_ip=_client_ip(request),
        )

        response["session_id"] = db_session.id
        if room:
            response["room_url"] = room["url"]

    return response


@router.get("/", response_model=List[MachineResponse])
async def get_machines(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Machine))
    return result.scalars().all()


@router.patch("/{machine_id}/heartbeat")
async def machine_heartbeat(
    machine_id: str,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Machine).where(Machine.id == machine_id))
    machine = result.scalar_one_or_none()
    if not machine or machine.token != token:
        raise HTTPException(status_code=401, detail="Invalid machine token")

    await db.execute(
        update(Machine)
        .where(Machine.id == machine_id)
        .values(last_seen=datetime.utcnow(), is_online=True)
    )
    await db.commit()
    return {"status": "ok"}


@router.delete("/{machine_id}")
async def delete_machine(
    machine_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    result = await db.execute(select(Machine).where(Machine.id == machine_id))
    machine = result.scalar_one_or_none()
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")

    # Audit history is preserved with NULL machine/session refs so we still
    # remember "user X deleted machine Y at time Z" without holding a
    # foreign-key lock on the row we're about to delete. Sessions and the
    # file transfers under them are removed because they're meaningless
    # without their machine.
    machine_name = machine.name
    session_ids = (
        await db.execute(select(Session.id).where(Session.machine_id == machine_id))
    ).scalars().all()

    if session_ids:
        await db.execute(
            update(AuditLog)
            .where(AuditLog.session_id.in_(session_ids))
            .values(session_id=None)
        )
        await db.execute(
            delete(FileTransfer).where(FileTransfer.session_id.in_(session_ids))
        )
        await db.execute(delete(Session).where(Session.id.in_(session_ids)))

    await db.execute(
        update(AuditLog).where(AuditLog.machine_id == machine_id).values(machine_id=None)
    )
    await db.execute(delete(Machine).where(Machine.id == machine_id))

    # Audit row for the delete itself — written *after* the cascade so the
    # FK to machines is intentionally NULL (machine no longer exists).
    await audit(
        db, "machine.delete",
        user_id=current_user.id,
        actor_ip=_client_ip(request),
        detail={"name": machine_name, "machine_id": machine_id, "sessions_removed": len(session_ids)},
    )
    await db.commit()
    return {"status": "deleted", "sessions_removed": len(session_ids)}
