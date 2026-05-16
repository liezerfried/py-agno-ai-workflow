#Requires -Version 5.1
<#
.SYNOPSIS
    Launches the two development servers in separate PowerShell windows.

.DESCRIPTION
    - AgentOS  -> uv run python agent_os.py
    - Chainlit -> chainlit run app.py --port 8001

    Each server runs in its own window so the logs stay separated
    and each one can be closed/restarted independently (Ctrl+C).

.EXAMPLE
    .\scripts\dev.ps1
#>

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot

if (-not (Test-Path (Join-Path $projectRoot 'agent_os.py'))) {
    Write-Error "Could not find agent_os.py in $projectRoot. Run the script from the repo root."
}
if (-not (Test-Path (Join-Path $projectRoot 'app.py'))) {
    Write-Error "Could not find app.py in $projectRoot."
}

Write-Host "Launching servers from: $projectRoot" -ForegroundColor Cyan

Start-Process -FilePath 'powershell.exe' -ArgumentList @(
    '-NoExit',
    '-Command',
    "Set-Location '$projectRoot'; `$Host.UI.RawUI.WindowTitle = 'AgentOS'; uv run python agent_os.py"
)

Start-Process -FilePath 'powershell.exe' -ArgumentList @(
    '-NoExit',
    '-Command',
    "Set-Location '$projectRoot'; `$Host.UI.RawUI.WindowTitle = 'Chainlit :8001'; uv run chainlit run app.py --port 8001"
)

Write-Host "AgentOS  -> window 'AgentOS'" -ForegroundColor Green
Write-Host "Chainlit -> window 'Chainlit :8001' (http://localhost:8001)" -ForegroundColor Green
Write-Host "Close each window with Ctrl+C to stop the corresponding server." -ForegroundColor DarkGray
