---
name: tv
description: Launch TradingView Desktop with CDP debugging port so the TradingView MCP can connect. Use whenever TV isn't open, the MCP reports it's disconnected, or the user says "launch tv", "open tv", "start tv", "tv not connecting", "check tv", "reconnect tradingview", or anything implying TradingView needs to be running for chart work to proceed.
disable-model-invocation: true
---

# /tv — Launch TradingView with CDP

## Platform — Windows vs the Ubuntu box

Steps 1–6 below are for **Windows** (TV + the MCP both run locally on Windows).

**On the Ubuntu trading box (Linux):** the whole procedure reduces to one idempotent launcher —
**`~/.openclaw/scripts/tv-cdp.sh`** (the Linux `/tv` equivalent, committed to openclaw-config). It checks
CDP on :9222 and, only if it's not already up, launches `/usr/bin/tradingview --remote-debugging-port=9222`
on `DISPLAY=:1` (shares the IBKR display); it never relaunches a live CDP session. Run it with
`ssh ubuntu ~/.openclaw/scripts/tv-cdp.sh`.

- ⚠️ **CDP binds to 127.0.0.1**, so the `tradingview-mcp` must run **on the Ubuntu box itself**
  (`node ~/tradingview-mcp/src/server.js`, registered in that session's MCP config) — a Windows MCP can't
  reach it without `--remote-debugging-address=0.0.0.0` (exposes DevTools to the LAN = security risk; tunnel/firewall only).
- ⚠️ If a TV instance is already running **without** CDP, `tv-cdp.sh` can't add the port (Electron single-instance) —
  kill that TV first, then run the launcher. Full setup + activation: `docs/tradingview-ubuntu-setup.md`.

---

## Step 1 — Check if already running

```powershell
curl.exe -s http://localhost:9222/json/version 2>$null | Select-Object -First 2
```

If response contains `"Browser"`, TV is already up with CDP. Call `mcp__tradingview__tv_health_check` to confirm MCP is connected, then stop — nothing else needed.

## Step 2 — Find the correct executable path

TradingView auto-updates and the version folder changes, and install location differs per machine and per install type (Microsoft Store vs classic installer). **Never hardcode the version string or a user-specific path** (`C:\Users\<name>\...`). Resolve dynamically with the self-contained resolver below — it tries every known install method and uses `$env:` variables so it works for any Windows user.

```powershell
# Portable TradingView resolver — works for any user, any install type.
$exePath = $null

# 1. Microsoft Store / UWP package (most common)
$pkg = Get-AppxPackage | Where-Object { $_.Name -like "*TradingView*" } | Select-Object -First 1
if ($pkg -and (Test-Path "$($pkg.InstallLocation)\TradingView.exe")) {
    $exePath = "$($pkg.InstallLocation)\TradingView.exe"
}

# 2. Classic .exe installer locations (per-user and machine-wide)
if (-not $exePath) {
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\TradingView\TradingView.exe",
        "$env:LOCALAPPDATA\TradingView\TradingView.exe",
        "$env:ProgramFiles\TradingView\TradingView.exe",
        "${env:ProgramFiles(x86)}\TradingView\TradingView.exe"
    )
    $exePath = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}

# 3. Start Menu / Desktop shortcut (resolve target, never assume the path)
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

if ($exePath) { Write-Host "Resolved: $exePath" }
else { Write-Host "NOT FOUND" }
```

- If it prints `Resolved: <path>` → use `$exePath` in Step 3 (the variable persists in the same shell, but Step 3 re-resolves so it's safe to run standalone).
- If it prints `NOT FOUND` → TradingView Desktop is not installed, or installed somewhere unusual. Tell the user: "Couldn't locate TradingView Desktop. Make sure it's installed, then launch it manually once so Windows registers it."

## Step 3 — Launch

Re-resolve and launch in one block so the step is self-contained (no dependency on a variable from Step 2):

```powershell
$pkg = Get-AppxPackage | Where-Object { $_.Name -like "*TradingView*" } | Select-Object -First 1
$exePath = if ($pkg) { "$($pkg.InstallLocation)\TradingView.exe" } else {
    @("$env:LOCALAPPDATA\Programs\TradingView\TradingView.exe","$env:ProgramFiles\TradingView\TradingView.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
}
Start-Process $exePath -ArgumentList "--remote-debugging-port=9222"
```

If you already have a valid `$exePath` from Step 2 in the same shell, just run the `Start-Process` line.

## Step 4 — Wait and verify

```powershell
Start-Sleep 6
curl.exe -s http://localhost:9222/json/version | Select-Object -First 3
```

Expect a JSON response with `"Browser": "Chrome/..."`. If empty or error, wait 5 more seconds and retry once.

## Step 5 — MCP health check

Call `mcp__tradingview__tv_health_check` — expect `cdp_connected: true`.

**If false (CDP port up but MCP not connected):**
- TV may still be loading — wait 5s and retry the health check once
- If still false, the MCP server lost its CDP connection; restart Claude Code and retry

## Step 6 — Report

```
TV: running — CDP connected on :9222 (version: X.X.X)
```

Or if something failed, report what step failed and what the error was.

---

## Rules
- Never kill an existing TradingView instance without asking the user first
- CDP must be on port 9222 — that's what the MCP is configured to connect to
- Always resolve the path dynamically (Step 2) — never hardcode the version string OR a user-specific path (`C:\Users\<name>\...`). Use `$env:` variables and `Get-AppxPackage` so the skill works for any Windows user on any machine.
- If CDP is already responding on :9222, do NOT relaunch TV — it kills the existing tab session
