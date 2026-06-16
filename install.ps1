# Thin shim — all logic lives in install.py. Tries python3 then python (PS 5.1-safe).
$ErrorActionPreference = "Stop"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Get-Command python3 -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python -ErrorAction SilentlyContinue }
if (-not $py) { Write-Error "Python 3 not found on PATH"; exit 1 }
& $py.Source "$dir\install.py" @args
