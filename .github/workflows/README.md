# GitHub Actions workflows

## `build-installers.yml`

Builds the agent installers for Linux, Windows, and macOS using the
existing scripts under [`agent/install/build/`](../../agent/install/build/).

### When it runs

| Trigger | When |
|---|---|
| Manual dispatch | Anytime: **Actions → Build installers → Run workflow**, or `gh workflow run build-installers.yml` |
| Tag push | When you push a tag matching `v*.*.*` (e.g., `v1.0.3`). Also auto-creates a GitHub Release with the binaries attached. |

### What it produces

Three workflow artifacts (downloadable from the run summary page or via `gh run download <run-id>`):

| Artifact | Contents |
|---|---|
| `agent-linux` | `RemoteConnectAgent-linux-x86_64` (single binary) |
| `agent-windows` | `RemoteConnectAgent-win.exe` (single .exe) |
| `agent-macos` | `RemoteConnectAgent.app/` and `RemoteConnectAgent-mac.pkg` |

### Optional deploy to VPS

If you set the `VPS_HOST` and `VPS_SSH_KEY` secrets (see below), a fourth
job runs after the builds succeed and SCPs the artifacts onto the VPS at
`/root/home/rmm/remoteconnect/agent/install/build/dist/`. The backend's
`/install/{token}/download/{platform}` route picks them up immediately —
no service restart needed.

### Required for builds: nothing

The workflow runs without any secrets configured. You'll get unsigned
binaries that work; Windows SmartScreen and macOS Gatekeeper will warn
the customer. Customers can still click through ("More info → Run
anyway"). Adequate for early-stage support.

### Optional secrets

Configure under **Settings → Secrets and variables → Actions**:

#### Auto-deploy to VPS

| Name | Notes |
|---|---|
| `VPS_HOST` | e.g. `remoteconnect.ikieguy.online` or `72.62.179.186` |
| `VPS_SSH_USER` | usually `root` (defaults to `root` if unset) |
| `VPS_SSH_KEY` | full content of an OpenSSH private key (paste with newlines) |

To generate an SSH key just for this:
```bash
ssh-keygen -t ed25519 -f ./gh-deploy -N ''
# add the .pub to /root/.ssh/authorized_keys on the VPS
# copy the private key (the one without .pub) into the VPS_SSH_KEY secret
```

#### Windows code signing

| Name | Notes |
|---|---|
| `WINDOWS_CODESIGN_CERT_BASE64` | Base64-encoded `.pfx` file: `base64 -w0 cert.pfx` |
| `WINDOWS_CODESIGN_PASS` | The .pfx password |

Without these, Windows builds skip signing. Smartscreen will warn
("Unknown publisher") until enough downloads build reputation, OR you
buy an EV cert for instant trust.

#### macOS code signing + notarization

| Name | Notes |
|---|---|
| `APPLE_DEVELOPER_ID` | e.g. `Developer ID Application: Hegnone Tech Ltd. (XXXXXXXX)` |
| `APPLE_TEAM_ID` | 10-char Team ID from your Apple developer account |
| `APPLE_ID` | your Apple developer email |
| `APPLE_NOTARIZE_PASSWORD` | app-specific password — NOT your Apple ID password. Generate at appleid.apple.com → App-Specific Passwords |

Without these, macOS builds skip signing + notarization. Gatekeeper
will block the app outright; customers must right-click → Open → confirm.

### Cutting a release

```bash
git tag v1.0.0
git push --tags
```

That triggers:
1. All three platform builds
2. (If VPS secrets configured) deploy to VPS
3. GitHub Release auto-creation with all binaries attached + auto-generated changelog

### Verifying a built binary

After downloading the artifact:

```bash
# Linux:
file RemoteConnectAgent-linux-x86_64
# → "ELF 64-bit LSB executable, x86-64"

# Windows (run on a Windows host):
file RemoteConnectAgent-win.exe
# → "PE32+ executable (console) x86-64"

# macOS:
file RemoteConnectAgent.app/Contents/MacOS/RemoteConnectAgent
# → "Mach-O 64-bit executable arm64" (or x86_64)
```

If signing was enabled:
```bash
# Windows:
signtool verify /pa RemoteConnectAgent-win.exe

# macOS:
codesign --verify --verbose RemoteConnectAgent.app
spctl --assess --type execute RemoteConnectAgent.app
```

All three should exit 0.
