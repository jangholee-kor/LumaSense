param([string]$Port = '', [double]$Duration = 600, [string]$Output = '')
$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$captureArgs = @('-m', 'tools.sensor_cli', 'record', '--duration', $Duration)
if ($Port) { $captureArgs += @('--port', $Port) }
if ($Output) { $captureArgs += @('--output', $Output) }
& '.venv\Scripts\python.exe' @captureArgs
exit $LASTEXITCODE
