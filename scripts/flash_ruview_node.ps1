param(
    [Parameter(Mandatory = $true)]
    [string]$Port,

    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 255)]
    [int]$NodeId,

    [string]$Ssid = "CCTV-STAND",
    [string]$Password = $env:RUVIEW_WIFI_PASSWORD,
    [string]$TargetIp = "auto",
    [int]$TargetPort = 5005,
    [int]$Channel = 11,
    [int]$TdmTotal = 6,
    [int]$TdmSlot = -1,
    [switch]$NoUpload,
    [switch]$NoProvision,
    [string]$FirmwarePath = "firmware\esp32-rf-node"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$FirmwareFullPath = Join-Path $RepoRoot $FirmwarePath
$PlatformIo = Join-Path $env:USERPROFILE ".platformio\penv\Scripts\platformio.exe"

if (!(Test-Path $FirmwareFullPath)) {
    throw "Firmware path not found: $FirmwareFullPath"
}
if (!(Test-Path $PlatformIo)) {
    throw "PlatformIO CLI not found: $PlatformIo"
}

if ($TdmSlot -lt 0) {
    $TdmSlot = $NodeId - 1
}

if ($TargetIp -eq "auto") {
    $Preferred = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -eq "192.168.88.10" } |
        Select-Object -First 1
    if ($Preferred) {
        $TargetIp = $Preferred.IPAddress
    } else {
        $Preferred = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object {
                $_.AddressState -eq "Preferred" -and
                $_.IPAddress -notmatch "^(127\.|169\.254\.|172\.19\.)" -and
                $_.InterfaceAlias -notmatch "tun|vEthernet|VMware|Loopback"
            } |
            Sort-Object { if ($_.InterfaceAlias -eq "Ethernet") { 0 } else { 1 } }, InterfaceMetric |
            Select-Object -First 1
        if (!$Preferred) {
            throw "Could not auto-detect laptop IPv4 address. Pass -TargetIp explicitly."
        }
        $TargetIp = $Preferred.IPAddress
    }
}

if (!$NoUpload) {
    Write-Host "Building and uploading CCTV/RuView firmware to $Port"
    Push-Location $FirmwareFullPath
    try {
        & $PlatformIo run --target upload --upload-port $Port
    } finally {
        Pop-Location
    }
}

if ($NoProvision) {
    Write-Host "Upload done. NVS provisioning skipped; existing board settings were preserved."
    exit 0
}

$ProvisionArgs = @(
    (Join-Path $FirmwareFullPath "scripts\provision_node.py"),
    "--port", $Port,
    "--node-id", $NodeId,
    "--ssid", $Ssid,
    "--target-ip", $TargetIp,
    "--target-port", $TargetPort,
    "--channel", $Channel,
    "--tdm-total", $TdmTotal,
    "--tdm-slot", $TdmSlot
)
if (![string]::IsNullOrWhiteSpace($Password)) {
    $ProvisionArgs += @("--password", $Password)
} else {
    Write-Host "RUVIEW_WIFI_PASSWORD is empty; WiFi password in NVS will be preserved."
}

Write-Host "Provisioning node=$NodeId slot=$TdmSlot/$TdmTotal target=$TargetIp`:$TargetPort"
py -3.11 @ProvisionArgs
