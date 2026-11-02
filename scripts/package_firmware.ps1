param([switch]$EnablePsram)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'idf_environment.ps1')
$profileName = if ($EnablePsram) { 'psram' } else { 'default' }
$buildName = if ($EnablePsram) { 'firmware-build-psram' } else { 'firmware-build' }
$buildPath = Join-Path $repoRoot ".local\$buildName"
$outputPath = Join-Path $repoRoot ".local\firmware-release\$profileName"
if (-not (Test-Path (Join-Path $buildPath 'flasher_args.json'))) { throw 'Build firmware first.' }
New-Item -ItemType Directory -Force $outputPath | Out-Null
$flashArgs = Get-Content -LiteralPath (Join-Path $buildPath 'flasher_args.json') -Raw | ConvertFrom-Json
Push-Location -LiteralPath $buildPath
try {
    & python -m esptool --chip esp32s3 merge_bin -o (Join-Path $outputPath 'firmware-merged.bin') '@flash_args'
    if ($LASTEXITCODE -ne 0) { throw 'Firmware merge failed' }
    $files = @()
    foreach ($entry in $flashArgs.flash_files.PSObject.Properties) {
        $sourcePath = Join-Path $buildPath $entry.Value
        $fileName = Split-Path -Leaf $sourcePath
        Copy-Item -LiteralPath $sourcePath -Destination (Join-Path $outputPath $fileName)
        $files += @{ offset=$entry.Name; file=$fileName; sha256=(Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash }
    }
    $sdk = Get-Content -LiteralPath (Join-Path $buildPath 'config\sdkconfig.json') -Raw | ConvertFrom-Json
    $manifest = @{
        firmware='0.2.0'; target='esp32s3'; profile=$profileName; flash_size='16MB'; psram_enabled=[bool]$EnablePsram
        idf_commit=(& git -C $env:IDF_PATH rev-parse HEAD); physical_validation='unverified'
        gpio=@{sda=$sdk.SMC_I2C_SDA;scl=$sdk.SMC_I2C_SCL;radar_rx=$sdk.SMC_RADAR_RX;radar_tx=$sdk.SMC_RADAR_TX}
        files=$files; merged_sha256=(Get-FileHash -LiteralPath (Join-Path $outputPath 'firmware-merged.bin') -Algorithm SHA256).Hash
    }
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $outputPath 'manifest.json') -Encoding UTF8
} finally { Pop-Location }
Compress-Archive -LiteralPath (Join-Path $outputPath 'bootloader.bin'),(Join-Path $outputPath 'partition-table.bin'),(Join-Path $outputPath 'smart_monitor_s3.bin'),(Join-Path $outputPath 'firmware-merged.bin'),(Join-Path $outputPath 'manifest.json') -DestinationPath "$outputPath.zip" -Force
Write-Output "Package: $outputPath.zip"
