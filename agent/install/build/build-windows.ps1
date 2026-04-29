<#
.SYNOPSIS
  Build a Windows agent .exe using PyInstaller.

.DESCRIPTION
  Output: agent\install\build\dist\windows\RemoteConnectAgent-win.exe

  If WINDOWS_CODESIGN_CERT (path to .pfx) and WINDOWS_CODESIGN_PASS are set
  in the environment, the binary is signed via signtool. Otherwise the
  build still succeeds — the binary just ships unsigned (Windows
  SmartScreen will warn the customer).
#>
$ErrorActionPreference = 'Stop'

# Move to repo root
$repo = Resolve-Path (Join-Path $PSScriptRoot '..\..\..')
Set-Location $repo

$outDir = Join-Path $repo 'agent\install\build\dist\windows'
$workDir = Join-Path $repo 'agent\install\build\.work-windows'
$entry = Join-Path $repo 'agent\install\build\agent_entry.py'

New-Item -ItemType Directory -Force -Path $outDir | Out-Null
New-Item -ItemType Directory -Force -Path $workDir | Out-Null

# Set up Python venv with PyInstaller + agent deps
if (-not (Test-Path "$workDir\venv\Scripts\python.exe")) {
  py -3 -m venv "$workDir\venv"
  & "$workDir\venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
  & "$workDir\venv\Scripts\pip.exe" install -r (Join-Path $repo 'agent\requirements.txt') --quiet
  & "$workDir\venv\Scripts\pip.exe" install pyinstaller==6.10.0 --quiet
}

# Build
& "$workDir\venv\Scripts\pyinstaller.exe" `
  --onefile `
  --name RemoteConnectAgent-win `
  --distpath $outDir `
  --workpath "$workDir\build" `
  --specpath $workDir `
  --add-data "$repo\agent;agent" `
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
  $entry

$built = Join-Path $outDir 'RemoteConnectAgent-win.exe'
Write-Host "`n✓ Windows binary built at: $built"

# Optional signing
& (Join-Path $PSScriptRoot 'sign-windows.ps1') -BinaryPath $built
