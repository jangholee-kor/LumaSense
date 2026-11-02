param([string]$IdfPath = $env:IDF_PATH, [string]$ToolsPath = $env:IDF_TOOLS_PATH)
$ErrorActionPreference = 'Stop'
if (-not $IdfPath) { $IdfPath = 'C:\Espressif\v5.5.4\esp-idf' }
if (-not (Test-Path -LiteralPath (Join-Path $IdfPath 'tools\idf.py'))) { throw 'Set IDF_PATH to an ESP-IDF 5.5.x checkout.' }
$idfVersion = Get-Content -LiteralPath (Join-Path $IdfPath 'tools\cmake\version.cmake') -Raw
if ($idfVersion -notmatch 'IDF_VERSION_MAJOR 5\)' -or $idfVersion -notmatch 'IDF_VERSION_MINOR 5\)') { throw 'Tested ESP-IDF 5.5.x checkout required.' }
if (-not $ToolsPath) { $ToolsPath = Join-Path $env:USERPROFILE '.espressif' }
$env:IDF_PATH = (Resolve-Path -LiteralPath $IdfPath).Path
$env:IDF_TOOLS_PATH = $ToolsPath
$env:PYTHONIOENCODING = 'utf-8'
. (Join-Path $env:IDF_PATH 'export.ps1')
if ($LASTEXITCODE -ne 0) { throw 'ESP-IDF environment export failed' }
