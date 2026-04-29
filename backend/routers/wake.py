"""Wake-on-LAN endpoint.

The technician can't send a WoL magic packet from their browser (browsers
can't send raw UDP), and the backend usually isn't on the same LAN as the
target. So we relay through *another* online agent that *is* on the same
LAN — the technician picks an online "helper" machine, gives the target
MAC, and the helper agent sends the magic packet on its broadcast.
"""
from __future__ import annotations

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import audit
from ..database import get_db
from ..models.machine import Machine
from ..models.user import User
from ..websocket_manager import manager
from .auth import get_current_user

router = APIRouter()

MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}([:-]?[0-9A-Fa-f]{2}){5}$")


class WakeRequest(BaseModel):
    target_mac: str
    helper_machine_id: str
    broadcast: Optional[str] = None  # optional override broadcast address

    @field_validator("target_mac")
    @classmethod
    def _validate_mac(cls, v: str) -> str:
        if not MAC_RE.match(v):
            raise ValueError("invalid MAC")
        # normalize to AA:BB:...
        cleaned = re.sub(r"[:-]", "", v).upper()
        return ":".join(cleaned[i:i+2] for i in range(0, 12, 2))


@router.post("/")
async def send_wol(
    payload: WakeRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    helper_q = await db.execute(select(Machine).where(Machine.id == payload.helper_machine_id))
    helper = helper_q.scalar_one_or_none()
    if helper is None:
        raise HTTPException(status_code=404, detail="Helper machine not found")
    if not helper.is_online:
        raise HTTPException(status_code=409, detail="Helper machine is offline")

    actor_ip = request.client.host if request.client else None
    await audit(
        db, "wake.requested",
        user_id=current_user.id, machine_id=helper.id,
        actor_ip=actor_ip,
        detail={"target_mac": payload.target_mac, "broadcast": payload.broadcast},
    )

    await manager.send_to_machine(helper.id, {
        "type": "wake_lan",
        "target_mac": payload.target_mac,
        "broadcast": payload.broadcast,
    })

    return {"status": "queued", "via": helper.id, "target_mac": payload.target_mac}
