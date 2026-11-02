param([Parameter(Mandatory=$true)][string]$Port)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'idf_environment.ps1')
& python -m esptool --chip esp32s3 --port $Port run
if ($LASTEXITCODE -ne 0) { throw 'ESP32-S3 reset failed' }
