# ESP32 RuView Broadcast CSI Node

PlatformIO firmware for the six ESP32-S3-N16R8 boards used by the CCTV/RuView stand.

The firmware sends two UDP packet types for every accepted ESP-NOW sounding CSI capture:

- ADR-018 RuView-compatible CSI packet, magic `0xC5110001`;
- project RF-link diagnostic packet, magic `0xC5110101`, with `rx_node_id`, inferred `tx_node_id`, RSSI and raw CSI bytes.

Health is sent once per second as magic `0xC5110102`.

## Why Broadcast

The earlier firmware needed a preconfigured peer MAC list. This version uses ESP-NOW broadcast sounding in a TDM schedule, so the six boards can generate link CSI without manually entering every peer MAC. CSI frames not tied to a recent ESP-NOW sounding are dropped on-device to keep backend/RuView load stable.

## Build

```powershell
& "$env:USERPROFILE\.platformio\penv\Scripts\platformio.exe" run -d firmware\esp32-rf-node
```

Optional per-node binaries:

```powershell
& "$env:USERPROFILE\.platformio\penv\Scripts\platformio.exe" run -d firmware\esp32-rf-node -e node1 -e node2 -e node3 -e node4 -e node5 -e node6
```

## Flash

The normal path preserves existing NVS settings, including WiFi password and node id:

```powershell
.\scripts\flash_ruview_node.ps1 -Port COM3 -NodeId 1 -NoProvision
```

If provisioning is needed:

```powershell
$env:RUVIEW_WIFI_PASSWORD = "<stand-wifi-password>"
.\scripts\flash_ruview_node.ps1 -Port COM3 -NodeId 1
```

Defaults:

- SSID: `CCTV-STAND`;
- backend target: auto-detected laptop IP, fallback can be passed with `-TargetIp`;
- UDP port: `5005`;
- channel: `11`;
- TDM total: `6`;
- TDM slot: `NodeId - 1`.

## Serial Commands

Baud rate: `115200`.

```text
SHOW
SECRET_SHOW
HEALTH
SOUND
SET node_id 1
SET ssid CCTV-STAND
SET password <password>
SET target_ip 192.168.88.10
SET target_port 5005
SET channel 11
SET tdm_total 6
SET tdm_slot 0
REBOOT
FACTORY_RESET
```

## HTTP Endpoints

Port `80`:

- `GET /health`;
- `GET /config`;
- `POST /config?...`;
- `GET /scan`;
- `GET /sound`.

Compatibility port `8032`:

- `GET /ota/status`;
- `GET /sound`.
