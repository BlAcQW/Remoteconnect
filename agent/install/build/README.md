# Build pipeline — Quick Connect installers

Builds standalone agent binaries that the customer downloads and runs
from the Quick Connect landing page.

## Outputs

```
agent/install/build/dist/
├── linux/
│   └── RemoteConnectAgent-linux-x86_64    (single binary, no Python required)
├── windows/
│   └── RemoteConnectAgent-win.exe         (single .exe)
└── macos/
    ├── RemoteConnectAgent.app             (app bundle)
    └── RemoteConnectAgent-mac.pkg         (installer .pkg)
```

The backend's `/install/{token}/download/{platform}` route serves the
matching file when present; otherwise it falls back to a small shell
script that runs `install-{platform}.sh` after a `git clone`.

## Recommended path: GitHub Actions

The repo ships with [`.github/workflows/build-installers.yml`](../../../.github/workflows/build-installers.yml)
that builds all three platforms in parallel on hosted runners. See
[`.github/workflows/README.md`](../../../.github/workflows/README.md)
for full operator instructions.

Quick version:

```bash
# Trigger a build manually:
gh workflow run build-installers.yml

# Or cut a release (also auto-attaches binaries to a GH Release):
git tag v1.0.0 && git push --tags
```

After the run completes, download artifacts:

```bash
gh run download --name agent-windows
gh run download --name agent-linux
gh run download --name agent-macos
```

If you've configured the `VPS_HOST` + `VPS_SSH_KEY` secrets, the binaries
are auto-deployed to the VPS and the install endpoint immediately starts
serving them — no manual copy needed.

## Fallback: build locally per platform

For one-off builds without GitHub Actions:

```bash
# Linux (Python 3.12+)
./build-linux.sh

# Windows (PowerShell with Python 3.12+ on PATH)
.\build-windows.ps1

# macOS (Python 3.12+ + Xcode command-line tools)
./build-macos.sh
```

Each script:
1. Creates a build venv in `.work-{platform}/`
2. Installs PyInstaller + agent deps
3. Bundles `agent_entry.py` + the `agent/` package into a single artifact
4. Optionally signs the artifact (see below)

After building locally, copy the `dist/` folder onto the server:
```bash
scp -r dist root@<vps>:/root/home/rmm/remoteconnect/agent/install/build/
```

## Code signing — required eventually, optional today

Without signing, customers see scary OS warnings:
- **Windows SmartScreen**: "Microsoft Defender prevented an unrecognized app…"
- **macOS Gatekeeper**: outright blocks; requires right-click → Open

For development you can ship unsigned and walk customers through the
"More info → Run anyway" path. For production you'll want to sign.

The build scripts honor the same env vars whether you run them locally
or in GitHub Actions — they're just exposed as Actions secrets in CI.

### Windows

#### Dev builds — self-signed cert (no money, no CA)

`make-dev-cert.ps1` generates a self-signed Authenticode cert and wires
it into the signing flow automatically:

```powershell
# One-time: create the cert and set env vars for this session
.\make-dev-cert.ps1

# Then build — the exe will be signed
.\build-windows.ps1
```

The cert lives in `Cert:\CurrentUser\My`. Its thumbprint is printed when
it's created; you can also sign by thumbprint instead of a .pfx:

```powershell
$env:WINDOWS_CODESIGN_THUMBPRINT = "<thumbprint from make-dev-cert output>"
.\build-windows.ps1
```

To suppress SmartScreen on *your own machine* (not customers'), run once
from an elevated prompt:

```powershell
.\make-dev-cert.ps1 -InstallTrusted
```

**Note:** `dotnet dev-certs https` (the ASP.NET HTTPS dev cert) is a
*TLS* cert — wrong EKU, signtool rejects it. `make-dev-cert.ps1` creates
a proper *CodeSigning* cert (`Type = CodeSigning` → EKU 1.3.6.1.5.5.7.3.3).

#### Production — buy a cert from a trusted CA

| Type | Cost/yr | What you get |
|---|---|---|
| OV (Organization Validated) | $200-400 | Removes warning after reputation builds (~1000s of downloads) |
| EV (Extended Validation) | $300-700 | Skips warning immediately; cert lives on a hardware token |

**Local build with .pfx:**
```powershell
$env:WINDOWS_CODESIGN_CERT = "C:\path\to\cert.pfx"
$env:WINDOWS_CODESIGN_PASS = "<pfx-password>"
.\build-windows.ps1
```

**GitHub Actions:** add `WINDOWS_CODESIGN_CERT_BASE64` (base64 of the
.pfx) and `WINDOWS_CODESIGN_PASS` as repo secrets. The workflow decodes
the cert into a temp file before invoking the build.

The `sign-windows.ps1` script wraps `signtool sign` with sensible
defaults (SHA-256, DigiCert timestamp). Supports both PFX and cert-store
(thumbprint) modes. Requires `signtool.exe` — pre-installed on
`windows-latest` runners; locally install Windows SDK:
`winget install Microsoft.WindowsSDK.10.0.22621`.

### macOS

Sign up for the Apple Developer Program ($99/yr at
<https://developer.apple.com/programs/>). Generate a "Developer ID
Application" certificate from your account portal.

**Local build:**
```bash
export APPLE_DEVELOPER_ID="Developer ID Application: Hegnone Tech Ltd. (ABCD1234EF)"
export APPLE_TEAM_ID="ABCD1234EF"
export APPLE_ID="you@example.com"
export APPLE_NOTARIZE_PASSWORD="abcd-efgh-ijkl-mnop"   # app-specific password, NOT your Apple ID password
./build-macos.sh
```

**GitHub Actions:** add the same names as repo secrets. The workflow
exports them as env vars before invoking the build.

The `sign-macos.sh` script:
1. `codesign --deep --force --options runtime --sign "$APPLE_DEVELOPER_ID"` the .app
2. Submits to `xcrun notarytool` for notarization (~2-5 min wait)
3. Staples the notarization ticket to the .app
4. Signs the .pkg with `productsign`

### Linux

No signing. Just runs.
