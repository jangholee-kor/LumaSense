param([Parameter(Mandatory=$true)][string]$CheckReport, [string]$Output = '')
$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
if (-not $Output) { $Output = '.local\releases\LumaSense-0.3.0-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') }
& '.venv\Scripts\python.exe' -m tools.package_windows --check-report $CheckReport --output $Output
exit $LASTEXITCODE
