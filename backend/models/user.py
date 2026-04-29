from sqlalchemy import Column, String, TIMESTAMP, func
from .base import Base, uuid_str


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=uuid_str)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="technician")  # 'admin' | 'technician'
    created_at = Column(TIMESTAMP, server_default=func.now())
