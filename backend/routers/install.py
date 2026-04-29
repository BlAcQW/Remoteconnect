"""Installer-serving endpoints for the Quick Connect flow.

The /j/{token} public page (frontend) shows a "Download for X" button per
detected OS. That button hits /install/{token}/download/{platform} which:

  1. Validates the token (must exist, not used, not expired)
  2. Resolves the prebuilt binary at agent/install/build/dist/<platform>/...
  3. Streams it to the browser

If no prebuilt binary is available for that platform, we fall back to the
shell-installer-with-token approach: serve a small script that uses curl
to fetch the agent source and runs install-linux.sh / install-windows.ps1
with the token baked in. This means the flow works *today* without the
PyInstaller binaries, and silently upgrades when binaries are present.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from ..database import get_db
from ..models.join_token import JoinToken

router = APIRouter()

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_DIR = REPO_ROOT / "agent" / "install" / "build" / "dist"

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://remoteconnect.ikieguy.online")
PUBLIC_REPO_URL = os.getenv(
    "PUBLIC_REPO_URL",
    # Default: the technician hosts a public clone — override per deployment.
    "https://remoteconnect.ikieguy.online",
)

# platform → (binary path relative to BUILD_DIR, mime, suggested filename)
PLATFORM_BINARIES: dict[str, tuple[str, str, str]] = {
    "linux":   ("linux/RemoteConnectAgent-linux-x86_64",
                "application/x-executable",
                "RemoteConnectAgent-linux-x86_64"),
    "win":     ("windows/RemoteConnectAgent-win.exe",
                "application/vnd.microsoft.portable-executable",
                "RemoteConnectAgent.exe"),
    "macos":   ("macos/RemoteConnectAgent-mac.pkg",
                "application/octet-stream",
                "RemoteConnectAgent.pkg"),
}


async def _validate(token: str, db: AsyncSession) -> JoinToken:
    q = await db.execute(select(JoinToken).where(JoinToken.token == token))
    invite = q.scalar_one_or_none()
    if invite is None:
        raise HTTPException(status_code=404, detail="invite not found")
    if invite.status == "redeemed":
        raise HTTPException(status_code=410, detail="invite already used")
    if invite.expires_at and invite.expires_at < datetime.utcnow():
        raise HTTPException(status_code=410, detail="invite expired")
    return invite


@router.get("/{token}/download/{platform}")
async def download_installer(
    token: str,
    platform: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    if platform not in PLATFORM_BINARIES:
        raise HTTPException(status_code=400, detail=f"unsupported platform: {platform}")
    await _validate(token, db)

    rel, mime, fname = PLATFORM_BINARIES[platform]
    target = BUILD_DIR / rel
    if target.is_file():
        return FileResponse(
            path=str(target), media_type=mime, filename=fname,
        )

    # ── Fallback: serve a shell installer that uses the token ──────────────
    # If no prebuilt binary is available we hand back a tiny script that:
    #   1. clones / fetches the repo on the customer's machine
    #   2. runs the existing install-linux.sh / install-windows.ps1
    #      with --join-token=<token>
    # Customers paste the displayed `curl | bash` command from the landing
    # page; we serve the inline script here.
    if platform in ("linux", "macos"):
        return PlainTextResponse(
            _shell_fallback(token, platform),
            media_type="text/x-shellscript",
            headers={"Content-Disposition": f'attachment; filename="install-rc-{platform}.sh"'},
        )
    if platform == "win":
        return PlainTextResponse(
            _powershell_fallback(token),
            media_type="text/plain",
            headers={"Content-Disposition": 'attachment; filename="install-rc.ps1"'},
        )
    raise HTTPException(status_code=500, detail="no installer available for this platform")


def _shell_fallback(token: str, platform: str) -> str:
    return f"""#!/usr/bin/env bash
# RemoteConnect Quick Connect installer — token-bound, no signing required.
# Generated for platform={platform}, token=<redacted>
set -euo pipefail

INSTALL_DIR="$HOME/.local/share/remoteconnect-agent"
JOIN_TOKEN={token!r}
SERVER_URL={PUBLIC_BASE_URL!r}
REPO_URL={PUBLIC_REPO_URL!r}

echo "→ Downloading RemoteConnect agent…"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
git clone --depth 1 "$REPO_URL" "$TMP/rc" 2>/dev/null \\
  || curl -fsSL "$REPO_URL/repo/tarball/main" | tar -xz -C "$TMP"

cd "$TMP"/rc/agent/install 2>/dev/null || cd "$TMP"/*/agent/install
JOIN_TOKEN="$JOIN_TOKEN" ./install-linux.sh \\
    --server-url "$SERVER_URL" \\
    --join-token "$JOIN_TOKEN"

echo "✓ Agent installed and connecting. The technician will join shortly."
"""


def _powershell_fallback(token: str) -> str:
    return f"""# RemoteConnect Quick Connect installer (Windows)
# token=<redacted>

$ErrorActionPreference = 'Stop'
$JoinToken = {token!r}
$ServerUrl = {PUBLIC_BASE_URL!r}
$RepoUrl   = {PUBLIC_REPO_URL!r}

Write-Host "→ Downloading RemoteConnect agent…"
$tmp = Join-Path $env:TEMP ("rc-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $tmp | Out-Null
try {{
  git clone --depth 1 $RepoUrl $tmp 2>$null
  if ($LASTEXITCODE -ne 0) {{
    Invoke-WebRequest "$RepoUrl/repo/tarball/main" -OutFile "$tmp\\src.tar.gz"
    tar -xzf "$tmp\\src.tar.gz" -C $tmp
    $repo = Get-ChildItem -Directory -Path $tmp | Select-Object -First 1
    $tmp = $repo.FullName
  }}
  $installer = Join-Path $tmp "agent\\install\\install-windows.ps1"
  & $installer -ServerUrl $ServerUrl -JoinToken $JoinToken
}}
finally {{
  Remove-Item -Recurse -Force -LiteralPath $tmp -ErrorAction SilentlyContinue
}}

Write-Host "✓ Agent installed and connecting. The technician will join shortly."
"""
