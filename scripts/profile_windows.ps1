$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
& '.venv\Scripts\python.exe' -m tools.profile_windows @args
exit $LASTEXITCODE
