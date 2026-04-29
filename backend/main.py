import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

# Load backend/.env before any os.getenv at import time (e.g. auth.py JWT_SECRET)
load_dotenv(Path(__file__).parent / ".env")

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .database import engine, get_db
from .limiting import limiter
from .models import audit_log, file_transfer, join_token, machine, session, user  # noqa: F401  register tables on Base.metadata
from .models.base import Base


ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
IS_PRODUCTION = ENVIRONMENT == "production"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(
    title="RemoteConnect API",
    lifespan=lifespan,
    # Hide auto-generated API docs in production to reduce attack surface.
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_cors_raw = os.getenv("CORS_ORIGINS", "http://localhost:3000")
_cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """Liveness + DB reachability. Returns 503 when the database is down so
    load balancers and orchestrators can react."""
    try:
        await db.execute(text("SELECT 1"))
    except Exception as e:  # broad on purpose — we report any DB failure
        raise HTTPException(status_code=503, detail=f"db unavailable: {e}")
    return {"status": "healthy", "environment": ENVIRONMENT}


# Routers
from .routers import (  # noqa: E402
    auth, install, machines, quick_invite, sessions, signaling, wake,
)

app.include_router(auth.router, prefix="/auth")
app.include_router(machines.router, prefix="/machines")
app.include_router(sessions.router, prefix="/sessions")
app.include_router(quick_invite.router, prefix="/quick-invite")
app.include_router(install.router, prefix="/install")
app.include_router(wake.router, prefix="/wake")
app.include_router(signaling.router, prefix="/ws")
