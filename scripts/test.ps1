$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path '.venv\Scripts\python.exe')) { throw '먼저 scripts\setup.ps1을 실행하세요.' }
& '.venv\Scripts\python.exe' -m pytest @args
exit $LASTEXITCODE
