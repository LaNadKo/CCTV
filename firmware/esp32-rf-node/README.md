# ESP32 RF CSI node

Stand firmware for ESP32-S3-N16R8 boards used by the CCTV/RuView demo.

This is no longer only a Wi-Fi health probe. The firmware is the project-owned
radio layer for the stand:

- one shared binary for all boards;
- per-board provisioning stored in ESP32 NVS;
- stable `node_id` 1..6;
- TDM sounding slots;
- ESP-NOW peer-to-peer sounding frames;
- Wi-Fi CSI callback;
- UDP telemetry to the backend with `rx_node_id` and `tx_node_id`;
- HTTP health/config endpoints for diagnostics.

It does not generate the 3D room on the ESP32. ESP32 boards only collect radio
measurements. Room reconstruction / occupancy grid / Live3D must be built in the
backend from the link matrix.

## UDP packets

Backend UDP port: `5005`.

`0xC5110101` RF link packet:

- `rx_node_id`: board that received the frame and captured CSI.
- `tx_node_id`: peer board that sent the sounding frame.
- `flags`: CSI present / ESP-NOW / broadcast / unknown peer.
- `rssi`, `noise_floor`, `channel`, `sequence`.
- payload: raw signed CSI bytes.

`0xC5110102` RF health packet:

- `node_id`, `tdm_slot`, `tdm_total`;
- `rssi`, `channel`, `peer_count`, dropped CSI queue counter;
- uptime and sequence.

The old RuView ADR-018/ADR-002 packet formats remain supported by the backend,
but this firmware should be the main path for the final stand.

## Build

```powershell
& "$env:USERPROFILE\.platformio\penv\Scripts\platformio.exe" run -d firmware/esp32-rf-node
```

Output binary:

```text
firmware/esp32-rf-node/.pio/build/esp32_s3_n16r8/firmware.bin
```

## Flash and Provision

Use the root helper script. It uploads the shared binary and then writes runtime
settings over serial:

```powershell
$env:RUVIEW_WIFI_PASSWORD = "<stand-wifi-password>"
.\scripts\flash_rf_node.ps1 -Port COM3 -NodeId 1
```

For the next boards, only change `-NodeId` and the COM port:

```powershell
.\scripts\flash_rf_node.ps1 -Port COM4 -NodeId 2
.\scripts\flash_rf_node.ps1 -Port COM5 -NodeId 3
```

The script reads `config/rf_room_layout.json` and generates the peer list from
the known MAC/IP values. Default settings:

- SSID: `CCTV-STAND`
- backend IP: `192.168.88.10`
- UDP port: `5005`
- channel: `11`
- TDM total: `6`
- TDM slot: `NodeId - 1`

If the firmware is already uploaded and only settings should be rewritten:

```powershell
.\scripts\flash_rf_node.ps1 -Port COM3 -NodeId 1 -NoUpload
```

## Serial Commands

The firmware accepts simple serial commands at `115200` baud:

```text
SHOW
SET node_id 1
SET ssid CCTV-STAND
SET password <stand-wifi-password>
SET target_ip 192.168.88.10
SET target_port 5005
SET channel 11
SET tdm_total 6
SET tdm_slot 0
SET peers 1@94:A9:90:D2:04:2C@192.168.88.101;2@94:A9:90:D2:00:78@192.168.88.102
REBOOT
FACTORY_RESET
```

## HTTP Endpoints

Port `80`:

- `GET /health`: node state, Wi-Fi, CSI/ESP-NOW readiness, queue drops.
- `GET /config`: current non-secret config.
- `POST /config?...`: update config values.
- `GET /scan`: visible Wi-Fi networks.
- `GET /sound`: manually send one sounding burst to peers.

Port `8032`:

- `GET /ota/status`: compatibility endpoint used by the existing backend
  stimulator. It returns the same health JSON.

## Current Physical Layout

Room size: `600 cm x 355 cm x 330 cm`.

Current nodes are defined in `config/rf_room_layout.json`:

- `1`: top-left corner, `192.168.88.101`, `94:A9:90:D2:04:2C`
- `2`: bottom-left corner, `192.168.88.102`, `94:A9:90:D2:00:78`
- `3`: bottom long-wall midpoint, `192.168.88.103`, `A4:CB:8F:D4:88:10`
- `4`: bottom-right corner, `192.168.88.104`, `94:A9:90:D2:06:30`
- `5`: top-right corner, `192.168.88.105`, `94:A9:90:D1:FB:64`
- `6`: top long-wall midpoint, `192.168.88.106`, `94:A9:90:D2:0B:14`
