"""Provision an admin user.

Run from the repo root:
    ./backend/venv/bin/python -m backend.scripts.create_admin

You'll be prompted for email + password. Passing them as flags is also
supported for non-interactive setup (e.g. provisioning scripts):
    python -m backend.scripts.create_admin --email admin@example.com --password 'redacted'

The script idempotently:
  - creates the user as `role=admin` if the email is unknown
  - upgrades an existing technician to admin if the email already exists,
    after confirming with the operator (or `--force`)

Admins must only be created via this CLI. The public `/auth/register`
endpoint is locked to `role=technician`.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

# Make `backend.*` imports work whether the script is invoked as a module
# (`python -m backend.scripts.create_admin`) or directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from sqlalchemy import select  # noqa: E402

from backend.database import AsyncSessionLocal, engine  # noqa: E402
from backend.models import file_transfer, machine, session, user  # noqa: F401,E402
from backend.models.base import Base  # noqa: E402
from backend.models.user import User  # noqa: E402
from backend.routers.auth import get_password_hash  # noqa: E402


async def ensure_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def upsert_admin(email: str, password: str, force: bool) -> None:
    await ensure_tables()
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == email))
        existing = result.scalar_one_or_none()

        if existing is None:
            db.add(
                User(
                    email=email,
                    password_hash=get_password_hash(password),
                    role="admin",
                )
            )
            await db.commit()
            print(f"✓ Created admin: {email}")
            return

        if existing.role == "admin":
            if not force and input(
                f"User {email} is already admin. Reset password? [y/N]: "
            ).strip().lower() not in {"y", "yes"}:
                print("(no change)")
                return
        else:
            if not force and input(
                f"User {email} exists with role={existing.role!r}. "
                f"Promote to admin and reset password? [y/N]: "
            ).strip().lower() not in {"y", "yes"}:
                print("(no change)")
                return

        existing.role = "admin"
        existing.password_hash = get_password_hash(password)
        await db.commit()
        print(f"✓ Updated admin: {email}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Provision a RemoteConnect admin user")
    p.add_argument("--email", help="admin email")
    p.add_argument("--password", help="admin password (omit to be prompted)")
    p.add_argument(
        "--force",
        action="store_true",
        help="don't ask for confirmation when promoting / resetting",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    email = args.email or input("Admin email: ").strip()
    if not email or "@" not in email:
        print("invalid email", file=sys.stderr)
        return 2
    password = args.password or getpass.getpass("Admin password: ")
    if len(password) < 8:
        print("password must be at least 8 characters", file=sys.stderr)
        return 2

    try:
        asyncio.run(upsert_admin(email, password, args.force))
    except KeyboardInterrupt:
        print("\n(cancelled)", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
