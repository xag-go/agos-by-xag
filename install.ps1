# AGOS one-command setup for Windows 10 (21H2+) and Windows 11.
#
#   irm https://raw.githubusercontent.com/xag-go/agos-by-xag/main/install.ps1 | iex
#
# AGOS runs inside WSL 2 (Windows's own small Linux): this turns on WSL 2 with
# Ubuntu 24.04, switches systemd on there, and runs the same Linux installer
# inside it. Then http://localhost:3000 opens AGOS from Windows, and an `agos`
# command on Windows forwards to the one inside Ubuntu.
#
# Unattended: set $env:AGOS_YES = "1" (and AGOS_USER_MODE, AGOS_DATA_DIR,
# AGOS_PROVIDER, AGOS_PROVIDER_KEY, AGOS_VOICE, AGOS_REMOTE as in docs/INSTALL.md).
# Continue, not Stop: Windows PowerShell 5.1 turns any stderr line of a native
# program (wsl.exe) into a terminating error under Stop. Every wsl.exe call checks
# $LASTEXITCODE instead; the cmdlets that must not fail say -ErrorAction Stop.
$ErrorActionPreference = 'Continue'

# The one place the public repository is named (owner/name on GitHub).
$GitHubRepo = 'xag-go/agos-by-xag'
$RepoUrl = if ($env:AGOS_REPO_URL) { $env:AGOS_REPO_URL } else { "https://github.com/$GitHubRepo.git" }
$Ref = if ($env:AGOS_REF) { $env:AGOS_REF } else { 'main' }
$RawUrl = if ($env:AGOS_RAW_URL) { $env:AGOS_RAW_URL } else { "https://raw.githubusercontent.com/$GitHubRepo/$Ref/install.sh" }
$Distro = if ($env:AGOS_WSL_DISTRO) { $env:AGOS_WSL_DISTRO } else { 'Ubuntu-24.04' }

function Say($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "`nERROR: $text" -ForegroundColor Red; exit 1 }

# --- Administrator (WSL is a Windows feature) ------------------------------------
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
  Say 'AGOS needs to run this once as Administrator (to turn on WSL). Windows will ask for permission.'
  $self = Join-Path $env:TEMP 'agos-install.ps1'
  if ($PSCommandPath) { Copy-Item $PSCommandPath $self -Force }
  else { Invoke-RestMethod -Uri ($RawUrl -replace 'install\.sh$', 'install.ps1') -OutFile $self -ErrorAction Stop }
  # The elevated window does not see this window's $env: answers: hand them over.
  $pass = ''
  # Never the provider key (it would sit on a command line): with a key, start
  # PowerShell as Administrator yourself.
  if ($env:AGOS_PROVIDER_KEY) { Fail 'With AGOS_PROVIDER_KEY set, run this from a PowerShell opened as Administrator.' }
  foreach ($name in 'AGOS_YES', 'AGOS_USER', 'AGOS_USER_MODE', 'AGOS_DATA_DIR', 'AGOS_PROVIDER',
                    'AGOS_VOICE', 'AGOS_REMOTE', 'AGOS_SANDBOXD', 'AGOS_REPO_URL', 'AGOS_REF', 'AGOS_RAW_URL', 'AGOS_WSL_DISTRO') {
    $value = [Environment]::GetEnvironmentVariable($name)
    if ($value) { $pass += "`$env:$name='" + ($value -replace "'", "''") + "'; " }
  }
  $run = "$pass& '$self'; Read-Host 'Press Enter to close'"
  $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($run))
  Start-Process powershell.exe -Verb RunAs -Wait -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', $encoded)
  exit
}

# --- Requirements -------------------------------------------------------------------
Say 'Checking this PC'
$os = Get-CimInstance Win32_OperatingSystem
if (-not [Environment]::Is64BitOperatingSystem) { Fail 'A 64-bit Windows is needed.' }
if ([int]$os.BuildNumber -lt 19044) { Fail "Windows 10 21H2 (build 19044) or newer is needed (this is build $($os.BuildNumber))." }
$ramGb = [math]::Round($os.TotalVisibleMemorySize / 1MB)
if ($ramGb -lt 8) { Write-Host "  WARNING: $ramGb GB of memory; 8 GB or more is recommended." -ForegroundColor Yellow }
$freeGb = [math]::Round((Get-PSDrive -Name $env:SystemDrive.TrimEnd(':')).Free / 1GB)
if ($freeGb -lt 25) { Fail "Only $freeGb GB free on $($env:SystemDrive): AGOS needs about 25 GB (Ubuntu + AGOS + your data)." }
Write-Host "  [ok] Windows build $($os.BuildNumber), $ramGb GB memory, $freeGb GB free"

# --- WSL 2 + Ubuntu -----------------------------------------------------------------
Say "WSL 2 with $Distro"
$null = & wsl.exe --status 2>&1
if ($LASTEXITCODE -ne 0) {
  & wsl.exe --install --no-distribution
  if ($LASTEXITCODE -ne 0) { Fail 'WSL could not be turned on (is virtualization on in the BIOS?).' }
  Write-Host ''
  Write-Host 'WSL is turned on. RESTART Windows, then run the same command again to finish.' -ForegroundColor Yellow
  exit 0
}
& wsl.exe --update | Out-Null
& wsl.exe --set-default-version 2 | Out-Null
$distros = (& wsl.exe --list --quiet) -replace "`0", '' | Where-Object { $_ }
if ($distros -notcontains $Distro) {
  # Registered with root only; AGOS makes its own user inside.
  & wsl.exe --install -d $Distro --no-launch
  if ($LASTEXITCODE -ne 0) { Fail "$Distro could not be installed." }
  $launcher = Get-Command ("{0}.exe" -f ($Distro -replace '[-.]', '').ToLower()) -ErrorAction SilentlyContinue
  if ($launcher) { & $launcher.Source install --root | Out-Null }
}
& wsl.exe -d $Distro -u root --exec true
if ($LASTEXITCODE -ne 0) { Fail "$Distro does not start. Open it once from the Start menu, then run this again." }

# systemd on (AGOS's services and Hermes's gateways are systemd services).
$conf = & wsl.exe -d $Distro -u root --exec cat /etc/wsl.conf 2>$null
if (-not ($conf -match 'systemd\s*=\s*true')) {
  & wsl.exe -d $Distro -u root --exec bash -c "printf '\n[boot]\nsystemd=true\n' >> /etc/wsl.conf"
  & wsl.exe --terminate $Distro | Out-Null
}
& wsl.exe -d $Distro -u root --exec bash -c 'for i in $(seq 1 30); do [ -d /run/systemd/system ] && exit 0; sleep 1; done; exit 1'
if ($LASTEXITCODE -ne 0) { Fail 'systemd did not start in WSL (wsl --shutdown, then run this again).' }

# --- The Linux installer inside -----------------------------------------------------
Say 'Installing AGOS inside Ubuntu (this takes 15-30 minutes)'
$vars = @("AGOS_REPO_URL=$RepoUrl", "AGOS_REF=$Ref", 'AGOS_HOST_OS=windows')
foreach ($name in 'AGOS_YES', 'AGOS_USER', 'AGOS_USER_MODE', 'AGOS_DATA_DIR', 'AGOS_PROVIDER', 'AGOS_VOICE', 'AGOS_REMOTE', 'AGOS_SANDBOXD') {
  $value = [Environment]::GetEnvironmentVariable($name)
  if ($value) { $vars += "$name=$value" }
}
if ($env:AGOS_PROVIDER_KEY) {
  # The key goes through standard input into a private file, never a command line.
  $env:AGOS_PROVIDER_KEY | & wsl.exe -d $Distro -u root --exec bash -c 'umask 077; cat > /root/.agos-provider-key'
  $vars += 'AGOS_PROVIDER_KEY_FILE=/root/.agos-provider-key'
}
# Inside WSL, root runs the installer: AGOS gets its own user (no password asked).
# (No double quotes inside: Windows PowerShell 5.1 passes them to wsl.exe badly.)
$cmd = "curl -fsSL '$RawUrl' -o /tmp/agos-install.sh && env $($vars -join ' ') bash /tmp/agos-install.sh"
& wsl.exe -d $Distro -u root --exec bash -c $cmd
if ($LASTEXITCODE -ne 0) { Fail 'The install inside Ubuntu stopped; read the message above, then run this again (finished steps are skipped).' }

# --- Keep Ubuntu running, and the agos command on Windows --------------------------
Say 'AGOS starts with Windows'
# WSL stops a distribution when nothing uses it; this keeps it (and AGOS) up after logon.
# conhost --headless: no window.
$action = New-ScheduledTaskAction -Execute 'conhost.exe' -Argument "--headless wsl.exe -d $Distro -u root --exec sleep infinity"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -Hidden
Register-ScheduledTask -TaskName 'AGOS' -Action $action -Trigger $trigger -Settings $settings -Force -ErrorAction Stop | Out-Null
Start-ScheduledTask -TaskName 'AGOS'

$bin = Join-Path $env:LOCALAPPDATA 'AGOS'
New-Item -ItemType Directory -Force -Path $bin -ErrorAction Stop | Out-Null
@"
@echo off
rem The agos command: AGOS runs in WSL ($Distro); this forwards to it.
if /I "%~1"=="open" ( start "" http://localhost:3000 & exit /b 0 )
if /I "%~1"=="uninstall" if /I "%~2"=="--everything" (
  schtasks /Delete /TN AGOS /F >nul 2>&1
  wsl.exe --unregister $Distro
  echo AGOS and its Ubuntu are removed.
  exit /b 0
)
wsl.exe -d $Distro -u root --exec /usr/local/bin/agos %*
"@ | Set-Content -Path (Join-Path $bin 'agos.cmd') -Encoding ASCII
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not ($userPath -split ';' -contains $bin)) {
  [Environment]::SetEnvironmentVariable('Path', "$userPath;$bin", 'User')
}

Say 'Done. Open http://localhost:3000 (or type: agos open, in a new terminal).'
Start-Process 'http://localhost:3000'
