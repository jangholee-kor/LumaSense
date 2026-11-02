$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
New-Item -ItemType Directory -Force '.local\smoke' | Out-Null
$oldDataDir = $env:SMC_DATA_DIR
$oldQtPlatform = $env:QT_QPA_PLATFORM
try {
    $env:SMC_DATA_DIR = Join-Path (Get-Location) '.local\smoke'
    $env:QT_QPA_PLATFORM = 'offscreen'
    & '.venv\Scripts\python.exe' -m windows.main --smoke-test --screenshot '.local\smoke\ui.png'
    if ($LASTEXITCODE -ne 0) { throw 'GUI smoke 실행 실패' }
} finally {
    $env:SMC_DATA_DIR = $oldDataDir
    $env:QT_QPA_PLATFORM = $oldQtPlatform
}
