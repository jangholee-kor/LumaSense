$ErrorActionPreference = 'Stop'
if (-not $env:IDF_PATH) { $env:IDF_PATH = 'C:\Espressif\v5.5.4\esp-idf' }
if (-not (Test-Path (Join-Path $env:IDF_PATH 'tools\idf_tools.py'))) { throw 'Install ESP-IDF 5.5.x and set IDF_PATH.' }
& python (Join-Path $env:IDF_PATH 'tools\idf_tools.py') install --targets esp32s3
if ($LASTEXITCODE -ne 0) { throw 'ESP32-S3 toolchain install failed' }
& python (Join-Path $env:IDF_PATH 'tools\idf_tools.py') install-python-env
if ($LASTEXITCODE -ne 0) { throw 'ESP-IDF Python environment install failed' }
