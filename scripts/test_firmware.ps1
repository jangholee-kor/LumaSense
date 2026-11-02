param([string]$Compiler = 'gcc')
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot
New-Item -ItemType Directory -Force '.local\firmware-tests' | Out-Null
& $Compiler -std=c11 -Wall -Wextra -Werror '-Ifirmware/components/smc_sensors/include' 'firmware/components/smc_sensors/ld2412_protocol.c' 'firmware/tests/test_ld2412.c' -o '.local/firmware-tests/ld2412_tests.exe'
if ($LASTEXITCODE -ne 0) { throw 'Native parser compile failed' }
& '.local/firmware-tests/ld2412_tests.exe'
if ($LASTEXITCODE -ne 0) { throw 'Native parser tests failed' }
