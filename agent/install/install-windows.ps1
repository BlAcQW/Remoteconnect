<#
.SYNOPSIS
  RemoteConnect agent — Windows installer.

.DESCRIPTION
  Installs the agent under the current user's profile and registers it as
  a Scheduled Task that runs at logon. Task Scheduler (rather than a
  Windows Service running as LocalSystem) is the right primitive here —
  pynput needs to inject input into the active desktop session, which a
  service running as LocalSystem cannot do.

.PARAMETER ServerUrl
  RemoteConnect backend, e.g. https://remoteconnect.example.com.
  Required for install.

.PARAMETER WsUrl
  WebSocket endpoint. Defaults to ws/wss derived from ServerUrl.

.PARAMETER Name
  Machine display name. Defaults to $env:COMPUTERNAME.

.PARAMETER InstallDir
  Install location. Defaults to "$env:LOCALAPPDATA\RemoteConnect".

.PARAMETER Uninstall
  Remove the scheduled task and the install directory.

.EXAMPLE
  PS> .\install-windows.ps1 -ServerUrl https://your.host

.EXAMPLE
  PS> .\install-windows.ps1 -Uninstall
#>
param(
  [string]$ServerUrl,
  [string]$WsUrl,
  [string]$Name,
  [string]$InstallDir = "$env:LOCALAPPDATA\RemoteConnect",
  [string]$JoinToken = $env:JOIN_TOKEN,
  [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$TaskName = 'RemoteConnectAgent'

function Fail($msg) { Write-Error $msg; exit 1 }

function Get-PythonExe {
  # Prefer `py -3` (Python launcher), fall back to `python`/`python3`.
  foreach ($cand in @('py.exe', 'python.exe', 'python3.exe')) {
    $exe = Get-Command $cand -ErrorAction SilentlyContinue
    if ($exe) {
      $args = @('-c', 'import sys; print(sys.version_info[0:3])')
      if ($cand -eq 'py.exe') { $args = @('-3') + $args }
      try {
        $ver = & $exe.Source @args 2>$null
        if ($ver -match '\((\d+),\s*(\d+)') {
          $maj = [int]$Matches[1]; $min = [int]$Matches[2]
          if ($maj -gt 3 -or ($maj -eq 3 -and $min -ge 12)) {
            return @{ Exe = $exe.Source; UseLauncher = ($cand -eq 'py.exe') }
          }
        }
      } catch {}
    }
  }
  return $null
}

function Uninstall-Agent {
  Write-Host "Stopping and removing scheduled task '$TaskName'..."
  $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  if ($task) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
  }
  if (Test-Path $InstallDir) {
    Write-Host "Removing $InstallDir"
    Remove-Item -Recurse -Force -LiteralPath $InstallDir
  }
  Write-Host "Uninstalled."
}

function Install-Agent {
  if (-not $ServerUrl) { Fail "-ServerUrl is required for install" }

  if (-not $WsUrl) {
    if ($ServerUrl -match '^https://(.+)$') { $WsUrl = "wss://$($Matches[1])" }
    elseif ($ServerUrl -match '^http://(.+)$') { $WsUrl = "ws://$($Matches[1])" }
    else { Fail "-ServerUrl must start with http:// or https://" }
  }

  if (-not $Name) { $Name = $env:COMPUTERNAME }

  $py = Get-PythonExe
  if (-not $py) { Fail "Python 3.12+ is required. Install from https://www.python.org/downloads/" }

  $scriptDir = Split-Path -LiteralPath $MyInvocation.MyCommand.Path -Parent
  $agentSrc  = Resolve-Path (Join-Path $scriptDir '..')

  Write-Host "Installing RemoteConnect agent to $InstallDir"
  New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

  Write-Host "Copying agent source"
  $destAgent = Join-Path $InstallDir 'agent'
  if (Test-Path $destAgent) { Remove-Item -Recurse -Force $destAgent }
  Copy-Item -Recurse -Path $agentSrc -Destination $destAgent

  # Strip dev-only artifacts that may have been copied
  foreach ($skip in @('venv', '.venv', '__pycache__', 'config.json', '.env', 'files')) {
    $p = Join-Path $destAgent $skip
    if (Test-Path $p) { Remove-Item -Recurse -Force $p }
  }
  # Ensure the package is importable
  $initPath = Join-Path $destAgent '__init__.py'
  if (-not (Test-Path $initPath)) { New-Item -ItemType File -Path $initPath | Out-Null }

  Write-Host "Creating venv"
  $venvDir = Join-Path $InstallDir 'venv'
  if ($py.UseLauncher) {
    & $py.Exe -3 -m venv $venvDir
  } else {
    & $py.Exe -m venv $venvDir
  }
  $venvPython = Join-Path $venvDir 'Scripts\python.exe'
  $venvPip = Join-Path $venvDir 'Scripts\pip.exe'

  Write-Host "Installing agent dependencies"
  & $venvPython -m pip install --upgrade pip --quiet
  & $venvPip install --quiet -r (Join-Path $destAgent 'requirements.txt')
  if ($LASTEXITCODE -ne 0) { Fail "pip install failed" }

  Write-Host "Writing $destAgent\.env"
  $envContent = @"
SERVER_HTTP_URL=$ServerUrl
SERVER_WS_URL=$WsUrl
MACHINE_NAME=$Name
HEARTBEAT_INTERVAL_S=30
DAILY_PUBLISHER_CMD=
JOIN_TOKEN=$JoinToken
"@
  Set-Content -LiteralPath (Join-Path $destAgent '.env') -Value $envContent -Encoding ASCII

  # Drop any prior task so we can re-register cleanly
  $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  if ($existing) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
  }

  Write-Host "Registering scheduled task '$TaskName' (run at logon)"
  $action = New-ScheduledTaskAction `
      -Execute $venvPython `
      -Argument '-m agent.agent' `
      -WorkingDirectory $InstallDir
  $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
  $settings = New-ScheduledTaskSettingsSet `
      -AllowStartIfOnBatteries `
      -DontStopIfGoingOnBatteries `
      -RestartCount 999 `
      -RestartInterval (New-TimeSpan -Minutes 1) `
      -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
      -StartWhenAvailable
  $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

  Register-ScheduledTask `
      -TaskName $TaskName `
      -Action $action `
      -Trigger $trigger `
      -Settings $settings `
      -Principal $principal `
      -Description "RemoteConnect agent — runs at $env:USERNAME logon" | Out-Null

  Write-Host "Starting now"
  Start-ScheduledTask -TaskName $TaskName

  Write-Host ""
  Write-Host "Installed."
  Write-Host "  Status:    Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
  Write-Host "  Logs:      $destAgent\agent.log  (and current task output)"
  Write-Host "  Stop:      Stop-ScheduledTask -TaskName $TaskName"
  Write-Host "  Uninstall: .\install-windows.ps1 -Uninstall"
}

if ($Uninstall) { Uninstall-Agent } else { Install-Agent }
