<#
.SYNOPSIS
  Build a Windows agent .exe using PyInstaller.

.DESCRIPTION
  Output: agent\install\build\dist\windows\RemoteConnectAgent-win.exe

  The production server URL is baked into the bundled binary so a customer
  can run RemoteConnectAgent-win.exe with a single double-click and it
  registers with the right backend. Override per-build with -ServerUrl
  (e.g. for staging or local dev binaries).

  If WINDOWS_CODESIGN_CERT (path to .pfx) and WINDOWS_CODESIGN_PASS are set
  in the environment, the binary is signed via signtool. Otherwise the
  build still succeeds — the binary just ships unsigned (Windows
  SmartScreen will warn the customer).

.PARAMETER ServerUrl
  RemoteConnect HTTPS endpoint baked into the binary's bundled .env.
  Defaults to the production deployment.

.PARAMETER WsUrl
  WebSocket endpoint. Defaults to ws/wss derived from ServerUrl.
#>
param(
    [string]$ServerUrl = 'https://remoteconnect.ikieguy.online',
    [string]$WsUrl
)

$ErrorActionPreference = 'Stop'

# Derive WsUrl from ServerUrl unless caller supplied one explicitly
if (-not $WsUrl) {
    if     ($ServerUrl -match '^https://(.+)$') { $WsUrl = "wss://$($Matches[1])" }
    elseif ($ServerUrl -match '^http://(.+)$')  { $WsUrl = "ws://$($Matches[1])"  }
    else { throw "ServerUrl must start with http:// or https:// (got: $ServerUrl)" }
}
Write-Host "Building with SERVER_HTTP_URL=$ServerUrl"
Write-Host "                SERVER_WS_URL=$WsUrl"

# Move to repo root
$repo = Resolve-Path (Join-Path $PSScriptRoot '..\..\..')
Set-Location $repo

$outDir = Join-Path $repo 'agent\install\build\dist\windows'
$workDir = Join-Path $repo 'agent\install\build\.work-windows'
$entry = Join-Path $repo 'agent\install\build\agent_entry.py'
$iconPath = Join-Path $repo 'agent\install\build\win-icon.ico'
$manifestPath = Join-Path $repo 'agent\install\build\win-app.manifest'
$versionTemplate = Join-Path $repo 'agent\install\build\win-version-info.template.txt'

New-Item -ItemType Directory -Force -Path $outDir | Out-Null
New-Item -ItemType Directory -Force -Path $workDir | Out-Null

# ── Build-time metadata: derive a clean numeric version from the git tag ─────
# In CI the tag is in $env:GITHUB_REF_NAME (e.g. "v0.2.4"). For local builds
# we fall back to "0.0.0" so devs can still run this script. The 4-part
# version tuple Windows expects (major, minor, patch, build) is hard-coded
# to build=0; PyInstaller doesn't surface a build counter.
$rawTag = $env:GITHUB_REF_NAME
if (-not $rawTag) { $rawTag = '0.0.0' }
$cleanTag = $rawTag -replace '^v', ''
$parts = $cleanTag.Split('.')
while ($parts.Length -lt 3) { $parts += '0' }
$verMajor = [int]($parts[0] -replace '\D','0')
$verMinor = [int]($parts[1] -replace '\D','0')
$verPatch = [int]($parts[2] -replace '\D','0')
$versionTuple = "($verMajor, $verMinor, $verPatch, 0)"
$versionString = "$verMajor.$verMinor.$verPatch.0"
Write-Host "Embedding version metadata: $versionString $versionTuple"

# Render the version-info file from the template into the work dir.
$versionFile = Join-Path $workDir 'win-version-info.txt'
$tpl = Get-Content -Raw -LiteralPath $versionTemplate
$tpl = $tpl.Replace('{VERSION_TUPLE}', $versionTuple).Replace('{VERSION_STRING}', $versionString)
Set-Content -LiteralPath $versionFile -Value $tpl -Encoding UTF8

# Stage a clean copy of agent/ in the work dir, strip dev artifacts, then
# write the production .env into it. PyInstaller --add-data points at the
# staged copy so the source tree is never mutated and a developer's local
# agent\.env is never bundled accidentally.
$agentStage = Join-Path $workDir 'agent-stage'
if (Test-Path $agentStage) { Remove-Item -Recurse -Force $agentStage }
# Robocopy (not Copy-Item) because the work dir lives inside agent\, so a
# naive recursive copy would self-include and explode. /XD skips the
# installer build dir itself plus dev artifacts. Robocopy exit codes
# 0..7 are success ("files copied"); 8+ is a real failure.
$robocopySrc = Join-Path $repo 'agent'
$null = robocopy $robocopySrc $agentStage /MIR `
    /XD ".work-windows" ".work-linux" ".work-macos" "dist" `
        "venv" ".venv" "__pycache__" "files" `
    /XF "config.json" ".env" `
    /NFL /NDL /NJH /NJS /NP
if ($LASTEXITCODE -ge 8) { throw "robocopy failed with exit code $LASTEXITCODE" }
$LASTEXITCODE = 0  # robocopy uses non-zero on success; reset for later checks
$envContent = @"
SERVER_HTTP_URL=$ServerUrl
SERVER_WS_URL=$WsUrl
HEARTBEAT_INTERVAL_S=30
DAILY_PUBLISHER_CMD=
"@
Set-Content -LiteralPath (Join-Path $agentStage '.env') -Value $envContent -Encoding ASCII

# Set up Python venv with PyInstaller + agent deps.
#
# IMPORTANT: $ErrorActionPreference='Stop' does NOT trap non-zero native
# exit codes from the `&` call operator on Windows PowerShell, so an
# earlier failed `pip install` (e.g., daily-python having no Windows
# wheels) silently produced an empty venv and PyInstaller went on to
# build a binary missing every Python dependency. Explicit
# $LASTEXITCODE guards make the build halt loudly instead.
function Invoke-CheckedNative {
    param([string]$What, [scriptblock]$Block)
    & $Block
    if ($LASTEXITCODE -ne 0) {
        throw "$What failed with exit code $LASTEXITCODE"
    }
}

if (-not (Test-Path "$workDir\venv\Scripts\python.exe")) {
  Invoke-CheckedNative "create venv"     { py -3 -m venv "$workDir\venv" }
  Invoke-CheckedNative "upgrade pip"     { & "$workDir\venv\Scripts\python.exe" -m pip install --upgrade pip }
  Invoke-CheckedNative "install agent reqs" { & "$workDir\venv\Scripts\pip.exe" install -r (Join-Path $repo 'agent\requirements.txt') }
  Invoke-CheckedNative "install pyinstaller" { & "$workDir\venv\Scripts\pip.exe" install "pyinstaller>=6.15.0" }
}

# Build
#
# --noconsole         hides the cmd window so the customer only sees the
#                     installer-style Tk window from agent_entry.py.
# --hidden-import asyncio  belt-and-suspenders: PyInstaller's analyzer
#                     should pick up `import asyncio` from agent_entry,
#                     but state this explicitly so we don't ship a binary
#                     that crashes with "No module named 'asyncio'" if
#                     analysis ever misses it again.
& "$workDir\venv\Scripts\pyinstaller.exe" `
  --onefile `
  --noconsole `
  --name RemoteConnectAgent-win `
  --distpath $outDir `
  --workpath "$workDir\build" `
  --specpath $workDir `
  --icon $iconPath `
  --version-file $versionFile `
  --manifest $manifestPath `
  --add-data "$agentStage;agent" `
  --hidden-import asyncio `
  --hidden-import agent `
  --hidden-import agent.agent `
  --hidden-import agent.config `
  --hidden-import agent.control `
  --hidden-import agent.input_handler `
  --hidden-import agent.screen_capture `
  --hidden-import agent.transfer_handlers `
  --hidden-import agent.runtime_state `
  --hidden-import agent.publisher_daily `
  --hidden-import websockets `
  --hidden-import httpx `
  --hidden-import dotenv `
  --hidden-import mss `
  --hidden-import PIL `
  --hidden-import PIL.Image `
  --hidden-import PIL.ImageOps `
  --hidden-import pynput `
  --hidden-import pynput.mouse `
  --hidden-import pynput.keyboard `
  --hidden-import pyperclip `
  $entry

$built = Join-Path $outDir 'RemoteConnectAgent-win.exe'
Write-Host "`n✓ Windows binary built at: $built"

# Optional signing
& (Join-Path $PSScriptRoot 'sign-windows.ps1') -BinaryPath $built
