"""Tiny helper for writing audit_log rows. Fire-and-forget — never raises
because we don't want auditing to break a happy-path request."""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from .models.audit_log import AuditLog

log = logging.getLogger(__name__)


async def audit(
    db: AsyncSession,
    event: str,
    *,
    user_id: Optional[str] = None,
    machine_id: Optional[str] = None,
    session_id: Optional[str] = None,
    actor_ip: Optional[str] = None,
    detail: Optional[dict[str, Any]] = None,
    commit: bool = True,
) -> None:
    try:
        db.add(
            AuditLog(
                event=event,
                user_id=user_id,
                machine_id=machine_id,
                session_id=session_id,
                actor_ip=actor_ip,
                detail=detail,
            )
        )
        if commit:
            await db.commit()
    except Exception as e:
        log.warning("audit write failed (%s): %s", event, e)
        try:
            await db.rollback()
        except Exception:
            pass
