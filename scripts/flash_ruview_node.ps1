param(
    [Parameter(Mandatory = $true)]
    [string]$Port,

    [Parameter(Mandatory = $true)]
    [int]$NodeId,

    [int]$TdmSlot = -1,
    [int]$TdmTotal = 6,
    [string]$Ssid = "CCTV-STAND",
    [string]$Password = $env:RUVIEW_WIFI_PASSWORD,
    [string]$TargetIp = "192.168.88.10",
    [int]$TargetPort = 5005,
    [int]$Channel = 11,
    [int]$EdgeTier = 0,
    [string]$RuViewPath = (Join-Path $env:TEMP "RuView-codex")
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($Password)) {
    throw "Set RUVIEW_WIFI_PASSWORD or pass -Password. The password is intentionally not stored in this repository."
}

if ($TdmSlot -lt 0) {
    $TdmSlot = $NodeId - 1
}

$FirmwareDir = Join-Path $RuViewPath "firmware\esp32-csi-node"
$BinsDir = Join-Path $FirmwareDir "release_bins"
$Provision = Join-Path $FirmwareDir "provision.py"

foreach ($Path in @(
    (Join-Path $BinsDir "bootloader.bin"),
    (Join-Path $BinsDir "partition-table.bin"),
    (Join-Path $BinsDir "ota_data_initial.bin"),
    (Join-Path $BinsDir "esp32-csi-node.bin"),
    $Provision
)) {
    if (!(Test-Path $Path)) {
        throw "RuView firmware file not found: $Path. Clone RuView to $RuViewPath first."
    }
}

Write-Host "Flashing RuView CSI firmware: node=$NodeId slot=$TdmSlot/$TdmTotal port=$Port target=$TargetIp`:$TargetPort"

py -3.11 -m esptool --chip esp32s3 --port $Port --baud 460800 write_flash --flash_mode dio --flash_size 8MB `
    0x0 (Join-Path $BinsDir "bootloader.bin") `
    0x8000 (Join-Path $BinsDir "partition-table.bin") `
    0xf000 (Join-Path $BinsDir "ota_data_initial.bin") `
    0x20000 (Join-Path $BinsDir "esp32-csi-node.bin")

py -3.11 $Provision `
    --port $Port `
    --ssid $Ssid `
    --password $Password `
    --target-ip $TargetIp `
    --target-port $TargetPort `
    --node-id $NodeId `
    --tdm-slot $TdmSlot `
    --tdm-total $TdmTotal `
    --edge-tier $EdgeTier `
    --channel $Channel
