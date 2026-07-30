# /tv launcher — Steps 1-4 of SKILL.md in one idempotent run.
# Safe to call from the Bash tool:
#   powershell.exe -ExecutionPolicy Bypass -File "$HOME/.claude/skills/tv/launch-tv.ps1"
# Exits 0 when CDP is up on :9222, 1 otherwise.

$ErrorActionPreference = 'Stop'

function Get-CdpVersion {
    try {
        return Invoke-RestMethod -Uri 'http://localhost:9222/json/version' -TimeoutSec 3
    } catch {
        return $null
    }
}

# Step 1 — already running? Never relaunch a live CDP session (kills the tab session).
$cdp = Get-CdpVersion
if ($cdp) {
    Write-Host "ALREADY_UP $($cdp.Browser)"
    exit 0
}

# Step 2 — resolve the executable. Never hardcode a version string or a user-specific path.
$exePath = $null

# Microsoft Store / UWP package
$pkg = Get-AppxPackage | Where-Object { $_.Name -like '*TradingView*' } | Select-Object -First 1
if ($pkg -and (Test-Path "$($pkg.InstallLocation)\TradingView.exe")) {
    $exePath = "$($pkg.InstallLocation)\TradingView.exe"
}

# Classic installer locations
if (-not $exePath) {
    $exePath = @(
        "$env:LOCALAPPDATA\Programs\TradingView\TradingView.exe",
        "$env:LOCALAPPDATA\TradingView\TradingView.exe",
        "$env:ProgramFiles\TradingView\TradingView.exe",
        "${env:ProgramFiles(x86)}\TradingView\TradingView.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
}

# Start Menu / Desktop shortcut — resolve the target, never assume it
if (-not $exePath) {
    $shell = New-Object -ComObject WScript.Shell
    $lnks = @(
        "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\TradingView.lnk",
        "$env:ProgramData\Microsoft\Windows\Start Menu\Programs\TradingView.lnk",
        (Join-Path ([Environment]::GetFolderPath('Desktop')) 'TradingView.lnk'),
        "$env:USERPROFILE\OneDrive\Desktop\TradingView.lnk"
    )
    foreach ($lnk in $lnks) {
        if (Test-Path $lnk) {
            $t = $shell.CreateShortcut($lnk).TargetPath
            if ($t -and (Test-Path $t)) { $exePath = $t; break }
        }
    }
}

if (-not $exePath) {
    Write-Host 'NOT_FOUND TradingView Desktop is not installed, or is in an unusual location.'
    exit 1
}

# Step 3 — launch with CDP.
# MSIX/Store installs live under ACL-protected Program Files\WindowsApps\. Start-Process on that
# exe path works on a normal user token but is Access-Denied from a restricted / packaged-app
# container token (e.g. an agent shell inside the MSIX Claude app), and
# Invoke-CommandInDesktopPackage silently no-ops. shell:AppsFolder activation works on BOTH token
# types and does pass -ArgumentList through. Classic-installer paths keep the direct spawn.
if ($pkg -and $exePath -like '*\WindowsApps\*') {
    $appId = (Get-AppxPackageManifest $pkg).Package.Applications.Application.Id | Select-Object -First 1
    $target = "shell:AppsFolder\$($pkg.PackageFamilyName)!$appId"
    Write-Host "LAUNCHING $target (MSIX activation)"
    Start-Process $target -ArgumentList '--remote-debugging-port=9222'
} else {
    Write-Host "LAUNCHING $exePath"
    Start-Process $exePath -ArgumentList '--remote-debugging-port=9222'
}

# Step 4 — wait and verify (6s, then one 5s retry, per SKILL.md)
Start-Sleep -Seconds 6
$cdp = Get-CdpVersion
if (-not $cdp) {
    Start-Sleep -Seconds 5
    $cdp = Get-CdpVersion
}

if ($cdp) {
    Write-Host "CDP_UP $($cdp.Browser)"
    Write-Host "UA $($cdp.'User-Agent')"
    exit 0
}

Write-Host 'CDP_DOWN Launched, but :9222 never answered. TV may still be loading, or an existing TV instance is running without CDP (Electron single-instance - ask the user before killing it).'
exit 1
