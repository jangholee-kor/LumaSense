$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
& '.venv\Scripts\python.exe' -m windows.phase_gate @args
exit $LASTEXITCODE
