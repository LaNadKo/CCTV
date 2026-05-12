# RF room layout

`rf_room_layout.json` is the source of truth for the ESP32 room map used by the
backend and frontend diagnostics.

For another demo room, edit only the JSON values:

- `room.width_cm`: room size along the X axis.
- `room.depth_cm`: room size along the Y axis.
- `room.height_cm`: ceiling height.
- `nodes[].x_cm`: node X coordinate from the bottom-left origin.
- `nodes[].y_cm`: node Y coordinate from the bottom-left origin.
- `nodes[].z_cm`: node mounting height above the floor.
- `objects[]`: schematic room objects rendered by the frontend 3D view.
- `objects[].x_cm/y_cm/z_cm`: object origin in the same coordinate system.
- `objects[].width_cm/depth_cm/height_cm`: axis-aligned object dimensions.

The ESP32 firmware does not need to be reflashed when only room dimensions or
physical positions change. Reflash is needed only when the node identity,
network credentials or firmware behavior changes.

To use another layout file without modifying this one, set:

```powershell
$env:RF_ROOM_LAYOUT_PATH = "config/rf_room_layout_diploma.json"
```

RF baseline snapshots are stored in JSONL format at `data/rf_samples.jsonl` by
default. This path is runtime data and is intentionally ignored by git.

Useful RF endpoints:

- `GET /rf/room`: current room layout.
- `PUT /rf/room`: save the edited room layout (admin only).
- `GET /rf/snapshot`: live health snapshot from all ESP32 nodes.
- `GET /rf/snapshot?include_scan=true`: slower snapshot with Wi-Fi scans.
- `POST /rf/history/collect`: save one baseline sample.
- `POST /rf/history/collect-batch`: save several samples with a delay between them.
- `GET /rf/history`: read saved samples.
- `GET /rf/baseline`: aggregate saved samples by node.
- `GET /ruview/status`: live RuView UDP bridge status and parsed CSI node state.
- `POST /ruview/start`: start the RuView UDP bridge if it was not running.
- `POST /ruview/reset`: clear in-memory RuView packet counters.
- `POST /ruview/calibration/collect`: record a stimulated CSI calibration window.
- `GET /ruview/calibration`: read saved calibration windows.
- `GET /ruview/estimate`: rough zone estimate from current CSI vs empty-room baseline.
- `GET /tracking/active`: active hybrid camera/RuView person tracks.

To store baseline samples elsewhere, set:

```powershell
$env:RF_HISTORY_PATH = "data/rf_samples_diploma.jsonl"
```

RuView CSI firmware sends UDP packets to the backend host. Defaults:

```powershell
$env:RUVIEW_UDP_BIND = "0.0.0.0"
$env:RUVIEW_UDP_PORT = "5005"
$env:RUVIEW_BRIDGE_ENABLED = "true"
$env:RUVIEW_STIMULATOR_ENABLED = "true"
$env:RUVIEW_STIMULATOR_INTERVAL_SECONDS = "0.25"
$env:RUVIEW_STIMULATOR_TIMEOUT_SECONDS = "0.35"
$env:ACTIVE_TRACKING_CAMERA_FRESH_SECONDS = "1.5"
$env:ACTIVE_TRACKING_RF_MIN_CONFIDENCE = "0.55"
$env:ACTIVE_TRACKING_ROOM_HOLD_SECONDS = "45"
```

The bridge parses RuView ADR-018 raw CSI packets (`0xC5110001`) and vitals
packets (`0xC5110002`). The stimulator continuously requests each ESP32 OTA
status endpoint to create a stable CSI stream for live room tracking without
manual browser refresh.

CSI calibration samples are stored at `data/ruview_calibration_samples.jsonl` by
default. Record at least one `empty_room` sample before using `/ruview/estimate`;
then record `person_at_point` samples with known coordinates to tune the room
model.

Processor live tracks are sent to `POST /processors/{processor_id}/tracks/observe`.
Unlike detection events, these observations are not deduplicated; they are used
only for the current active-room state. The camera remains the identity source,
and RuView is used as a handoff source after the camera stops seeing the body.
The default processor observation interval is `0.2` seconds. For a faster lab
test it can be lowered to `0.1`; values below that are clamped to protect the
backend from excessive request volume.

```powershell
$env:TRACK_OBSERVATION_ENABLED = "true"
$env:TRACK_OBSERVATION_INTERVAL = "0.2"
$env:TRACK_OBSERVATION_INCLUDE_UNKNOWN = "true"
```
