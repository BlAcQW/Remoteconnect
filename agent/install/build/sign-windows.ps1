<#
.SYNOPSIS
  Optionally sign a Windows binary using signtool.

.DESCRIPTION
  Reads cert path + password from env vars. No-op if not set so the build
  pipeline still works without a code-signing certificate.

  When signed:
   - SmartScreen builds reputation faster (OV cert) or skips warnings
     immediately (EV cert).
   - User sees "Verified publisher: <Your Co.>" instead of
     "Unknown publisher".

.PARAMETER BinaryPath
  Full path to the .exe to sign.
#>
param(
  [Parameter(Mandatory)] [string]$BinaryPath
)

$ErrorActionPreference = 'Stop'

$cert = $env:WINDOWS_CODESIGN_CERT
$pass = $env:WINDOWS_CODESIGN_PASS

if (-not $cert) {
  Write-Host "→ skipping signing — set WINDOWS_CODESIGN_CERT (path to .pfx) and WINDOWS_CODESIGN_PASS to enable"
  return
}
if (-not (Test-Path $cert)) {
  Write-Host "✗ WINDOWS_CODESIGN_CERT='$cert' does not exist; not signing."
  exit 1
}

$signtool = Get-Command signtool.exe -ErrorAction SilentlyContinue
if (-not $signtool) {
  Write-Host "✗ signtool.exe not on PATH. Install Windows SDK or add it to PATH."
  exit 1
}

& $signtool.Source sign `
  /f $cert `
  /p $pass `
  /tr "http://timestamp.digicert.com" `
  /td sha256 `
  /fd sha256 `
  /d "RemoteConnect Quick Connect Agent" `
  $BinaryPath

if ($LASTEXITCODE -ne 0) {
  Write-Host "✗ signtool sign failed"
  exit $LASTEXITCODE
}

Write-Host "✓ signed: $BinaryPath"
