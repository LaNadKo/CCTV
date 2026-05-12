# ESP32 RuView CSI node

This project does not vendor the full RuView repository. For flashing and
provisioning, use a local clone of `https://github.com/ruvnet/RuView`.

Current pilot settings:

- Board: ESP32-S3-N16R8.
- Pilot node: physical board 1, MAC `94:A9:90:D2:04:2C`.
- COM port used during setup: `COM3`.
- Wi-Fi SSID: `CCTV-STAND`.
- Backend/aggregator host: `192.168.88.10`.
- UDP port: `5005`.
- RuView packet formats parsed by backend:
  - `0xC5110001`: ADR-018 raw CSI.
  - `0xC5110002`: vitals packet.

Flash the next node:

```powershell
git clone --depth 1 https://github.com/ruvnet/RuView.git "$env:TEMP\RuView-codex"
$env:RUVIEW_WIFI_PASSWORD = "<stand-wifi-password>"
.\scripts\flash_ruview_node.ps1 -Port COM3 -NodeId 2
```

`NodeId` maps to the physical board label. The script defaults `TdmSlot` to
`NodeId - 1`, `TdmTotal` to `6`, channel to `11`, and edge tier to `0` for raw
CSI capture. Raw CSI is the correct first mode for model calibration and human
tracking; vitals/presence-only mode can be tested later with `-EdgeTier 2`.

After flashing, generate traffic to confirm CSI packets:

```powershell
ping -n 10 -l 1200 192.168.88.101
```

The backend bridge starts automatically with the API server when
`RUVIEW_BRIDGE_ENABLED=true` and exposes status at `GET /ruview/status`.

Note: the current RuView release binary may still put `raw_node_id=1` into ADR-018
CSI packets even after NVS provisioning another `node_id`. The backend resolves
the real physical node by packet source IP from `config/rf_room_layout.json` and
keeps `raw_node_id` only as a diagnostic field.
