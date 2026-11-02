$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 가상 환경 생성 실패' }
}
& '.venv\Scripts\python.exe' -m pip install -r requirements-lock.txt
if ($LASTEXITCODE -ne 0) { throw '패키지 설치 실패' }
