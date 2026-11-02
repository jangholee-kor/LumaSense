param([double]$Hours = 24, [double]$Step = .2)
$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$outputPath = '.local\soak-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff')
& '.venv\Scripts\python.exe' -m tools.soak_test --hours $Hours --step $Step --output $outputPath
exit $LASTEXITCODE
