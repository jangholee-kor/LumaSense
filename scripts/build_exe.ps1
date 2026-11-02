$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot
$pythonPath = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run scripts\setup.ps1 first.' }
$buildPath = $env:PATH
try {
    # Qt uses Windows ICU. Other tools can put incompatible ICU DLLs on PATH.
    $env:PATH = (Join-Path $env:SystemRoot 'System32') + ';' + $buildPath
    & $pythonPath -m PyInstaller --noconfirm --clean --onedir --windowed --name LumaSense --distpath '.local/windows-dist' --workpath '.local/pyinstaller' --specpath '.local/pyinstaller' --paths $repoRoot --hidden-import windows.core.watchdog --hidden-import windows.core.lease_guard --hidden-import serial.tools.list_ports_windows launch.py
    if ($LASTEXITCODE -ne 0) { throw 'LumaSense EXE build failed' }
} finally {
    $env:PATH = $buildPath
}
Write-Output (Join-Path $repoRoot '.local\windows-dist\LumaSense\LumaSense.exe')
