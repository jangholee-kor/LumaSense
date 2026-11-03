param([switch]$EnablePsram, [switch]$Menuconfig, [ValidateSet('DevKit', 'SuperMini')][string]$Board = 'DevKit')
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'idf_environment.ps1')
Set-Location -LiteralPath (Join-Path $repoRoot 'firmware')
if ($Board -eq 'SuperMini' -and $EnablePsram) { throw 'SuperMini profile does not use octal PSRAM.' }
$buildName = if ($Board -eq 'SuperMini') { 'firmware-build-supermini' } elseif ($EnablePsram) { 'firmware-build-psram' } else { 'firmware-build' }
$buildPath = Join-Path $repoRoot ".local\$buildName"
$defaults = if ($Board -eq 'SuperMini') { 'sdkconfig.defaults;sdkconfig.supermini' } elseif ($EnablePsram) { 'sdkconfig.defaults;sdkconfig.psram-octal' } else { 'sdkconfig.defaults' }
$action = if ($Menuconfig) { 'menuconfig' } else { 'build' }
New-Item -ItemType Directory -Force $buildPath | Out-Null
& python (Join-Path $env:IDF_PATH 'tools\idf.py') -B $buildPath '-DIDF_TARGET=esp32s3' "-DSDKCONFIG=$buildPath/sdkconfig" "-DSDKCONFIG_DEFAULTS=$defaults" $action
if ($LASTEXITCODE -ne 0) { throw 'ESP32-S3 firmware build failed' }
