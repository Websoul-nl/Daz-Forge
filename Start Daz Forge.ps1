$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    Write-Host "Daz Forge could not find .venv\Scripts\python.exe"
    Write-Host "Run the setup steps in docs/user-manual.md first."
    Read-Host "Press Enter to close"
    exit 1
}

& $python -m forge.ui.app @args
