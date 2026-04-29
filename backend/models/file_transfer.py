from sqlalchemy import Column, String, TIMESTAMP, ForeignKey, BIGINT, func
from .base import Base, uuid_str


class FileTransfer(Base):
    __tablename__ = "file_transfers"

    id = Column(String, primary_key=True, default=uuid_str)
    session_id = Column(String, ForeignKey("sessions.id"))
    filename = Column(String, nullable=False)
    direction = Column(String)  # 'upload' | 'download'
    size_bytes = Column(BIGINT)
    status = Column(String, default="pending")
    created_at = Column(TIMESTAMP, server_default=func.now())
