<#
.SYNOPSIS
  Generate a self-signed Authenticode (code-signing) certificate for
  local dev builds of RemoteConnectAgent-win.exe.

.DESCRIPTION
  This is NOT the ASP.NET HTTPS dev cert (dotnet dev-certs https).
  That cert is for TLS on localhost. This cert has the Code Signing EKU
  (1.3.6.1.5.5.7.3.3) so signtool.exe accepts it.

  What this creates:
    - A self-signed cert in Cert:\CurrentUser\My with CodeSigning EKU
    - A .pfx export at the path you specify (default: same folder as this script)
    - Sets WINDOWS_CODESIGN_CERT and WINDOWS_CODESIGN_PASS in your current
      shell so build-windows.ps1 picks them up immediately.

  Limitations of a self-signed cert:
    - Windows SmartScreen still warns ("Unknown publisher") because the cert
      is not from a trusted CA. For production, buy an OV/EV cert from
      DigiCert, Sectigo, etc.
    - Works fine for dev/internal installs — suppress the warning by importing
      the cert into Trusted Publishers (see -InstallTrusted switch).

.PARAMETER PfxPath
  Where to write the .pfx file.
  Default: <script dir>\RemoteConnect-dev-codesign.pfx

.PARAMETER Password
  Password for the .pfx. Default: RemoteConnectDev (change for real use).

.PARAMETER SubjectName
  CN for the cert. Default: "RemoteConnect Dev Code Signing"

.PARAMETER ValidYears
  How long the cert is valid. Default: 3.

.PARAMETER InstallTrusted
  Also add the cert to Cert:\LocalMachine\TrustedPublisher so SmartScreen
  stops warning on this machine. Requires an elevated shell.

.EXAMPLE
  # Basic — generate cert and set env vars for this session
  .\make-dev-cert.ps1

.EXAMPLE
  # Custom password, also install as trusted (run elevated)
  .\make-dev-cert.ps1 -Password "hunter2" -InstallTrusted
#>
param(
  [string]$PfxPath    = (Join-Path $PSScriptRoot 'RemoteConnect-dev-codesign.pfx'),
  [string]$Password   = 'RemoteConnectDev',
  [string]$SubjectName = 'RemoteConnect Dev Code Signing',
  [int]$ValidYears    = 3,
  [switch]$InstallTrusted
)

$ErrorActionPreference = 'Stop'

# ── 1. Create the self-signed cert ────────────────────────────────────────────
Write-Host "Creating self-signed code-signing certificate…"

$certParams = @{
  Subject           = "CN=$SubjectName"
  Type              = 'CodeSigning'          # sets KeyUsage + EKU automatically
  HashAlgorithm     = 'SHA256'
  KeyLength         = 2048
  KeyAlgorithm      = 'RSA'
  KeyExportPolicy   = 'Exportable'
  CertStoreLocation = 'Cert:\CurrentUser\My'
  NotAfter          = (Get-Date).AddYears($ValidYears)
}
$cert = New-SelfSignedCertificate @certParams
Write-Host "  Thumbprint : $($cert.Thumbprint)"
Write-Host "  Subject    : $($cert.Subject)"
Write-Host "  Not after  : $($cert.NotAfter)"

# ── 2. Export to .pfx ─────────────────────────────────────────────────────────
Write-Host "Exporting to $PfxPath …"
$securePass = ConvertTo-SecureString -String $Password -AsPlainText -Force
Export-PfxCertificate -Cert $cert -FilePath $PfxPath -Password $securePass | Out-Null
Write-Host "  ✓ written"

# ── 3. Optionally install into Trusted Publishers ─────────────────────────────
if ($InstallTrusted) {
  Write-Host "Installing into Cert:\LocalMachine\TrustedPublisher …"
  try {
    $store = New-Object System.Security.Cryptography.X509Certificates.X509Store(
      'TrustedPublisher', 'LocalMachine')
    $store.Open('ReadWrite')
    $store.Add($cert)
    $store.Close()
    Write-Host "  ✓ SmartScreen will no longer warn on this machine"
  } catch {
    Write-Warning "  Could not install to LocalMachine\TrustedPublisher: $_"
    Write-Warning "  Run this script from an elevated (Administrator) prompt to suppress SmartScreen."
  }
}

# ── 4. Set env vars for the current shell ─────────────────────────────────────
$env:WINDOWS_CODESIGN_CERT = $PfxPath
$env:WINDOWS_CODESIGN_PASS = $Password
Write-Host ""
Write-Host "Env vars set for this session:"
Write-Host "  WINDOWS_CODESIGN_CERT = $env:WINDOWS_CODESIGN_CERT"
Write-Host "  WINDOWS_CODESIGN_PASS = $env:WINDOWS_CODESIGN_PASS"
Write-Host ""
Write-Host "You can now run build-windows.ps1 and the exe will be signed."
Write-Host ""
Write-Host "To persist across sessions, add these to your shell profile or CI secrets:"
Write-Host "  `$env:WINDOWS_CODESIGN_CERT = '$PfxPath'"
Write-Host "  `$env:WINDOWS_CODESIGN_PASS = '$Password'"
Write-Host ""
Write-Host "NOTE: self-signed cert → SmartScreen still warns unless -InstallTrusted was used."
Write-Host "      For production, replace with an OV/EV cert from DigiCert/Sectigo."
