param([string]$Port = '', [switch]$EnablePsram, [ValidateSet('DevKit', 'SuperMini')][string]$Board = 'DevKit')
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'idf_environment.ps1')
Set-Location -LiteralPath $repoRoot
if (-not $Port) {
    $Port = & '.venv\Scripts\python.exe' -m tools.sensor_cli select-port
    if ($LASTEXITCODE -ne 0) { throw 'Specify -Port COMx explicitly.' }
}
if ($Board -eq 'SuperMini' -and $EnablePsram) { throw 'SuperMini profile does not use octal PSRAM.' }
$buildName = if ($Board -eq 'SuperMini') { 'firmware-build-supermini' } elseif ($EnablePsram) { 'firmware-build-psram' } else { 'firmware-build' }
$buildPath = Join-Path $repoRoot ".local\$buildName"
if (-not (Test-Path -LiteralPath (Join-Path $buildPath 'smart_monitor_s3.bin'))) { throw 'Run build_firmware.ps1 first.' }
Set-Location -LiteralPath (Join-Path $repoRoot 'firmware')
# IDF's generated flasher arguments enforce chip=esp32s3 before any write.
& python (Join-Path $env:IDF_PATH 'tools\idf.py') -B $buildPath -p $Port flash
if ($LASTEXITCODE -ne 0) { throw 'Flash failed; check exclusive COM port ownership and the ESP USB connector.' }
