import uuid
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def uuid_str() -> str:
    return str(uuid.uuid4())
