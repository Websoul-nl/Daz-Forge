$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    Write-Host "Daz Forge could not find .venv\Scripts\python.exe"
    Write-Host "Run the project setup first, or ask Vera to repair the environment."
    Read-Host "Press Enter to close"
    exit 1
}

& $python -m forge.ui.app @args
