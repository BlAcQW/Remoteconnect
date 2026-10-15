<#
.SYNOPSIS
  Optionally sign a Windows binary using signtool.

.DESCRIPTION
  Reads cert path + password from env vars. No-op if not set so the build
  pipeline still works without a code-signing certificate.

  Two modes:
    PFX mode   — set WINDOWS_CODESIGN_CERT (path to .pfx) + WINDOWS_CODESIGN_PASS
    Store mode — set WINDOWS_CODESIGN_THUMBPRINT (cert thumbprint already in
                 Cert:\CurrentUser\My or Cert:\LocalMachine\My).
                 make-dev-cert.ps1 prints the thumbprint when it creates a cert.

  When signed:
   - SmartScreen builds reputation faster (OV cert) or skips warnings
     immediately (EV cert).
   - User sees "Verified publisher: <Your Co.>" instead of "Unknown publisher".
   - Self-signed dev cert still shows "Unknown publisher" unless you ran
     make-dev-cert.ps1 -InstallTrusted on the target machine.

.PARAMETER BinaryPath
  Full path to the .exe to sign.
#>
param(
  [Parameter(Mandatory)] [string]$BinaryPath
)

$ErrorActionPreference = 'Stop'

$pfxPath   = $env:WINDOWS_CODESIGN_CERT
$pfxPass   = $env:WINDOWS_CODESIGN_PASS
$thumbprint = $env:WINDOWS_CODESIGN_THUMBPRINT

# ── No cert configured → skip silently ───────────────────────────────────────
if (-not $pfxPath -and -not $thumbprint) {
  Write-Host "→ skipping signing — configure one of:"
  Write-Host "    PFX   : set WINDOWS_CODESIGN_CERT (path to .pfx) + WINDOWS_CODESIGN_PASS"
  Write-Host "    Store : set WINDOWS_CODESIGN_THUMBPRINT (run make-dev-cert.ps1 to create one)"
  return
}

# ── Locate signtool ───────────────────────────────────────────────────────────
$signtool = Get-Command signtool.exe -ErrorAction SilentlyContinue
if (-not $signtool) {
  # Try common Windows SDK locations before giving up
  $sdkRoots = @(
    'C:\Program Files (x86)\Windows Kits\10\bin',
    'C:\Program Files\Windows Kits\10\bin'
  )
  foreach ($root in $sdkRoots) {
    if (Test-Path $root) {
      $found = Get-ChildItem $root -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
               Where-Object { $_.FullName -match 'x64' } |
               Sort-Object FullName -Descending |
               Select-Object -First 1
      if ($found) { $signtool = $found; break }
    }
  }
}
if (-not $signtool) {
  Write-Host "✗ signtool.exe not found. Install Windows SDK:"
  Write-Host "  winget install Microsoft.WindowsSDK.10.0.22621"
  exit 1
}
$signtoolExe = if ($signtool -is [System.IO.FileInfo]) { $signtool.FullName } else { $signtool.Source }

# ── Sign ──────────────────────────────────────────────────────────────────────
$commonArgs = @(
  'sign',
  '/tr', 'http://timestamp.digicert.com',
  '/td', 'sha256',
  '/fd', 'sha256',
  '/d',  'RemoteConnect Quick Connect Agent',
  $BinaryPath
)

if ($thumbprint) {
  # Store mode — cert is already in the Windows cert store
  Write-Host "→ signing with cert store thumbprint: $thumbprint"
  & $signtoolExe @commonArgs /sha1 $thumbprint
} else {
  # PFX mode
  if (-not (Test-Path $pfxPath)) {
    Write-Host "✗ WINDOWS_CODESIGN_CERT='$pfxPath' does not exist."
    Write-Host "  Run make-dev-cert.ps1 to generate a dev cert, or set the path correctly."
    exit 1
  }
  Write-Host "→ signing with PFX: $pfxPath"
  & $signtoolExe @commonArgs /f $pfxPath /p $pfxPass
}

if ($LASTEXITCODE -ne 0) {
  Write-Host "✗ signtool sign failed (exit $LASTEXITCODE)"
  exit $LASTEXITCODE
}

Write-Host "✓ signed: $BinaryPath"
