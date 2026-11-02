param([string]$Compiler = 'gcc')
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot
New-Item -ItemType Directory -Force '.local\firmware-tests' | Out-Null
& $Compiler -std=c11 -Wall -Wextra -Werror '-Ifirmware/components/smc_sensors/include' 'firmware/components/smc_sensors/ld2412_protocol.c' 'firmware/tests/test_ld2412.c' -o '.local/firmware-tests/ld2412_tests.exe'
if ($LASTEXITCODE -ne 0) { throw 'Native parser compile failed' }
& '.local/firmware-tests/ld2412_tests.exe'
if ($LASTEXITCODE -ne 0) { throw 'Native parser tests failed' }
& $Compiler -std=c11 -Wall -Wextra -Werror '-Ifirmware/components/smc_status/include' 'firmware/components/smc_status/status_led_model.c' 'firmware/tests/test_status_led.c' -o '.local/firmware-tests/status_led_tests.exe'
if ($LASTEXITCODE -ne 0) { throw 'Native status LED compile failed' }
& '.local/firmware-tests/status_led_tests.exe'
if ($LASTEXITCODE -ne 0) { throw 'Native status LED tests failed' }
& $Compiler -std=c11 -Wall -Wextra -Werror '-Ifirmware/tests/stubs' '-Ifirmware/components/smc_status/include' 'firmware/components/smc_status/status_led.c' 'firmware/components/smc_status/status_led_model.c' 'firmware/tests/test_status_led_driver.c' -o '.local/firmware-tests/status_led_driver_tests.exe'
if ($LASTEXITCODE -ne 0) { throw 'Native status LED driver compile failed' }
& '.local/firmware-tests/status_led_driver_tests.exe'
if ($LASTEXITCODE -ne 0) { throw 'Native status LED driver tests failed' }
