"""Installer-serving endpoints for the Quick Connect flow.

The /j/{token} public page (frontend) shows a "Download for X" button per
detected OS. That button hits /install/{token}/download/{platform} which:

  1. Validates the token (must exist, not used, not expired)
  2. Resolves the binary in this preference order:
       a. Local file at agent/install/build/dist/<platform>/...  (if a
          deploy step has put a binary there — fastest path)
       b. Latest GitHub Release of GH_RELEASES_REPO  (recommended host —
          repo must be public; the build-installers workflow auto-attaches
          binaries on tag push)
       c. Inline shell/PowerShell installer fallback that does git clone +
          install-{platform}.sh with the token baked in (works without any
          binaries — useful for local dev)

The route returns a 302 redirect for case (b) and streams bytes directly
for cases (a) and (c).
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.join_token import JoinToken

log = logging.getLogger(__name__)
router = APIRouter()

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_DIR = REPO_ROOT / "agent" / "install" / "build" / "dist"

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://remoteconnect.ikieguy.online")
PUBLIC_REPO_URL = os.getenv("PUBLIC_REPO_URL", "https://github.com/BlAcQW/Remoteconnect")

# When set, the install endpoint redirects customers to the latest
# GitHub Release asset. Format: "owner/repo".
GH_RELEASES_REPO = os.getenv("GH_RELEASES_REPO", "BlAcQW/Remoteconnect")

# How long to cache the resolved release-asset URLs in memory (seconds).
RELEASE_CACHE_TTL_S = int(os.getenv("RELEASE_CACHE_TTL_S", "300"))

# platform → (local-disk path under BUILD_DIR, mime, suggested filename,
#             GH-Release-asset filename)
PLATFORM_BINARIES: dict[str, tuple[str, str, str, str]] = {
    "linux": (
        "linux/RemoteConnectAgent-linux-x86_64",
        "application/x-executable",
        "RemoteConnectAgent-linux-x86_64",
        "RemoteConnectAgent-linux-x86_64",
    ),
    "win": (
        "windows/RemoteConnectAgent-win.exe",
        "application/vnd.microsoft.portable-executable",
        "RemoteConnectAgent.exe",
        "RemoteConnectAgent-win.exe",
    ),
    "macos": (
        "macos/RemoteConnectAgent-mac.pkg",
        "application/octet-stream",
        "RemoteConnectAgent.pkg",
        "RemoteConnectAgent-mac.pkg",
    ),
}

# Tiny in-memory cache so we don't hammer the GitHub API on every download.
_release_cache: dict[str, tuple[float, dict[str, str]]] = {}


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


async def _latest_release_assets() -> dict[str, str]:
    """Return {asset_name: browser_download_url} for the latest GH Release.

    Cached in memory for RELEASE_CACHE_TTL_S to avoid GitHub API rate
    limits on busy deploys. Returns {} on any failure (caller falls back
    to local file or inline fallback)."""
    if not GH_RELEASES_REPO:
        return {}

    cached = _release_cache.get(GH_RELEASES_REPO)
    now = time.time()
    if cached and (now - cached[0]) < RELEASE_CACHE_TTL_S:
        return cached[1]

    url = f"https://api.github.com/repos/{GH_RELEASES_REPO}/releases/latest"
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(url, headers={"accept": "application/vnd.github+json"})
        if r.status_code != 200:
            log.info("GH releases lookup %s -> %s", url, r.status_code)
            _release_cache[GH_RELEASES_REPO] = (now, {})
            return {}
        body = r.json()
        assets = {a["name"]: a["browser_download_url"] for a in body.get("assets", [])}
        _release_cache[GH_RELEASES_REPO] = (now, assets)
        return assets
    except Exception as e:
        log.warning("GH releases lookup failed: %s", e)
        _release_cache[GH_RELEASES_REPO] = (now, {})
        return {}


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

    rel, mime, fname, asset_name = PLATFORM_BINARIES[platform]

    # Preference 1: local file on disk (deploy step copied it here)
    target = BUILD_DIR / rel
    if target.is_file():
        return FileResponse(path=str(target), media_type=mime, filename=fname)

    # Preference 2: redirect to GitHub Release asset
    assets = await _latest_release_assets()
    if asset_name in assets:
        return RedirectResponse(url=assets[asset_name], status_code=302)

    # Preference 3: inline shell/powershell fallback (works without any prebuilt binaries)
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
