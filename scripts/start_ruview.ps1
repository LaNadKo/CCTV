param(
    [int]$HttpPort = 3100,
    [int]$WsPort = 3101,
    [int]$UdpPort = 5505
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    $env:RUVIEW_SIDECAR_HTTP_PORT = [string]$HttpPort
    $env:RUVIEW_SIDECAR_WS_PORT = [string]$WsPort
    $env:RUVIEW_SIDECAR_UDP_PORT = [string]$UdpPort
    docker compose --profile ruview up -d ruview-sensing
    Write-Host "RuView sidecar: http://127.0.0.1:$HttpPort"
    Write-Host "RuView UDP: 0.0.0.0:$UdpPort"
}
finally {
    Pop-Location
}
