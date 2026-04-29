import os
import ssl
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from .models.base import Base


def _normalize_db_url(raw: str) -> str:
    """Make a libpq-style Postgres URL safe for SQLAlchemy + asyncpg.

    - postgres:// / postgresql:// -> postgresql+asyncpg://
    - drop sslmode= and channel_binding= query params (asyncpg uses connect_args)
    - leave sqlite/other URLs alone
    """
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://"):]
    if raw.startswith("postgresql://"):
        raw = "postgresql+asyncpg://" + raw[len("postgresql://"):]
    if not raw.startswith("postgresql+asyncpg://"):
        return raw

    parts = urlsplit(raw)
    drop = {"sslmode", "channel_binding"}
    kept = [(k, v) for k, v in parse_qsl(parts.query) if k not in drop]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))


_RAW_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./remoteconnect.db")
DATABASE_URL = _normalize_db_url(_RAW_URL)

_connect_args: dict = {}
if DATABASE_URL.startswith("postgresql+asyncpg://"):
    # Neon and most managed Postgres providers require TLS.
    _connect_args["ssl"] = ssl.create_default_context()

engine = create_async_engine(
    DATABASE_URL,
    echo=True,  # Set to False in production
    poolclass=NullPool,  # Disable connection pooling for async
    connect_args=_connect_args,
)

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


__all__ = ["Base", "engine", "get_db"]
