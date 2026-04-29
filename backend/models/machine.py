from sqlalchemy import Column, String, TIMESTAMP, Boolean, func
from .base import Base, uuid_str


class Machine(Base):
    __tablename__ = "machines"

    id = Column(String, primary_key=True, default=uuid_str)
    name = Column(String, nullable=False)
    hostname = Column(String)
    os = Column(String)  # 'windows' | 'linux' | 'macos'
    ip_address = Column(String)
    token = Column(String, unique=True, nullable=False)  # Agent auth token
    last_seen = Column(TIMESTAMP)
    is_online = Column(Boolean, default=False)
    created_at = Column(TIMESTAMP, server_default=func.now())
