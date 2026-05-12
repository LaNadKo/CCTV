param(
    [ValidateSet("simulated", "auto", "esp32", "wifi")]
    [string]$Source = "esp32",
    [int]$HttpPort = 3100,
    [int]$WsPort = 3101,
    [int]$UdpPort = 5505,
    [switch]$Stop
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

Push-Location $repoRoot
try {
    if ($Stop) {
        docker compose --profile ruview stop ruview-sensing
        exit 0
    }

    $env:RUVIEW_SIDECAR_SOURCE = $Source
    $env:RUVIEW_SIDECAR_HTTP_PORT = [string]$HttpPort
    $env:RUVIEW_SIDECAR_WS_PORT = [string]$WsPort
    $env:RUVIEW_SIDECAR_UDP_PORT = [string]$UdpPort

    docker compose --profile ruview up -d ruview-sensing

    Write-Host "RuView HTTP: http://127.0.0.1:$HttpPort/ui/index.html"
    Write-Host "RuView API:  http://127.0.0.1:$HttpPort/health"
    Write-Host "RuView WS:   ws://127.0.0.1:$WsPort/ws/sensing"
    Write-Host "RuView UDP:  0.0.0.0:$UdpPort -> container 5005/udp"
}
finally {
    Pop-Location
}
