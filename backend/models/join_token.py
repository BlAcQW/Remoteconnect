"""One-time invite token used by the Quick Connect flow.

A technician creates one of these via POST /quick-invite/. The customer
clicks the resulting URL → downloads + runs the bundled installer → the
installer registers the new agent at /machines/register, passing the
``join_token``. Backend redeems the token (single-use), creates a Machine
row with the technician as creator, and pre-creates a pending Session so
the technician can jump straight in.
"""
from sqlalchemy import Column, String, TIMESTAMP, ForeignKey, func
from .base import Base, uuid_str


class JoinToken(Base):
    __tablename__ = "join_tokens"

    id = Column(String, primary_key=True, default=uuid_str)
    token = Column(String, unique=True, nullable=False, index=True)
    technician_id = Column(String, ForeignKey("users.id"), nullable=False)
    expires_at = Column(TIMESTAMP, nullable=False)
    used_at = Column(TIMESTAMP, nullable=True)
    machine_id = Column(String, ForeignKey("machines.id"), nullable=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=True)
    # 'pending' (created) | 'redeemed' | 'expired'
    status = Column(String, default="pending", nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())
