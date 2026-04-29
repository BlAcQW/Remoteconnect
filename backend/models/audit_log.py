from sqlalchemy import Column, String, TIMESTAMP, ForeignKey, JSON, func
from .base import Base, uuid_str


class AuditLog(Base):
    """Immutable record of security-relevant events.

    `event` examples:
        auth.login.ok            auth.login.failed       auth.register
        machine.register         machine.delete
        session.create           session.end             session.handoff
        session.consent.granted  session.consent.denied
        file.upload.ok           file.upload.rejected
        file.download.ok         file.download.rejected
        wake.sent
        guest.invite.created     guest.invite.consumed
    """

    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, default=uuid_str)
    event = Column(String, nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    machine_id = Column(String, ForeignKey("machines.id"), nullable=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=True)
    actor_ip = Column(String, nullable=True)
    detail = Column(JSON, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now(), index=True)
