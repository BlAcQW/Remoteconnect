from sqlalchemy import Column, String, TIMESTAMP, ForeignKey, func
from .base import Base, uuid_str


class Session(Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True, default=uuid_str)
    machine_id = Column(String, ForeignKey("machines.id"))
    technician_id = Column(String, ForeignKey("users.id"))
    daily_room_url = Column(String)  # Daily.co room URL
    status = Column(String, default="pending")  # 'pending' | 'active' | 'ended'
    started_at = Column(TIMESTAMP)
    ended_at = Column(TIMESTAMP)
    created_at = Column(TIMESTAMP, server_default=func.now())
