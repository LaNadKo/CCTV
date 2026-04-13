import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  collectRfHistorySample,
  collectRfHistoryBatch,
  getActiveTracking,
  getCameraRoomCalibration,
  getCameraRoomFrame,
  getCameraRoomRedLeds,
  getRfBaseline,
  getRfSnapshot,
  getRuViewCalibration,
  getRuViewEstimate,
  getRuViewStatus,
  getRuViewUpstream,
  saveCameraRoomCalibration,
  startRuViewBridge,
  updateRfRoom,
  type ActivePersonTrack,
  type ActiveTrackingSnapshot,
  type CameraRoomCalibration,
  type CameraRoomLedCandidate,
  type CameraRoomPoint,
  type RuViewBridgeStatus,
  type RuViewCalibrationHistory,
  type RuViewUpstreamStatus,
  type RuViewZoneEstimate,
  type RfBaselineSummary,
  type RfNodeRuntime,
  type RfRoomLayout,
  type RfRoomObject,
  type RfRoomSnapshot,
  type RfSnapshotSample,
} from "../lib/api";
import { useAuth } from "../context/AuthContext";

function formatCm(value?: number | null): string {
  return value == null ? "n/a" : `${Math.round(value)} cm`;
}

function formatUptime(ms?: number): string {
  if (!ms) return "n/a";
  const minutes = Math.floor(ms / 60000);
  if (minutes < 60) return `${minutes} min`;
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

function formatPacketCount(value?: number | null): string {
  if (value == null) return "0";
  return new Intl.NumberFormat("en-US").format(value);
}

function formatHz(value?: number | null): string {
  if (value == null) return "n/a";
  return `${value.toFixed(value >= 10 ? 0 : 1)} Hz`;
}

function nodeRssi(node: RfNodeRuntime): number | null {
  return typeof node.health?.rssi === "number" ? node.health.rssi : null;
}

function rssiTone(rssi: number | null): "good" | "warn" | "bad" | "off" {
  if (rssi == null) return "off";
  if (rssi >= -55) return "good";
  if (rssi >= -70) return "warn";
  return "bad";
}

function strongestNetworks(node: RfNodeRuntime) {
  return [...(node.scan?.networks ?? [])]
    .filter((network) => typeof network.rssi === "number")
    .sort((a, b) => (b.rssi ?? -999) - (a.rssi ?? -999))
    .slice(0, 3);
}

function toNumber(value: string): number {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : 0;
}

function formatPointValue(value: number): string {
  return Number.isFinite(value) ? String(Math.round(value * 10) / 10) : "0";
}

function cloneLayout(layout: RfRoomLayout): RfRoomLayout {
  return JSON.parse(JSON.stringify(layout)) as RfRoomLayout;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

const COCO_POSE_EDGES: [number, number][] = [
  [5, 7],
  [7, 9],
  [6, 8],
  [8, 10],
  [5, 6],
  [5, 11],
  [6, 12],
  [11, 12],
  [11, 13],
  [13, 15],
  [12, 14],
  [14, 16],
  [0, 5],
  [0, 6],
  [0, 1],
  [0, 2],
  [1, 3],
  [2, 4],
];

function nodeRuntimeById(snapshot: RfRoomSnapshot): Map<string, RfNodeRuntime> {
  return new Map(snapshot.nodes.map((node) => [node.config.node_id, node]));
}

function trackDisplayName(track: ActivePersonTrack): string {
  if (track.person_label) return track.person_label;
  if (track.person_id != null) return `Person #${track.person_id}`;
  return `Track #${track.processor_track_id ?? "?"}`;
}

function tracksWithRoomPosition(activeTracking?: ActiveTrackingSnapshot | null): ActivePersonTrack[] {
  return (activeTracking?.tracks ?? []).filter(
    (track) =>
      (track.status === "camera" || track.status === "rf") &&
      track.estimated_x_cm != null &&
      track.estimated_y_cm != null
  );
}

type RoomPersonEstimate = {
  key: string;
  x: number;
  y: number;
  confidence: number;
  label: string;
  displayId: string;
  activeNodes: number[];
  track: ActivePersonTrack | null;
};

type SceneSkeleton = {
  joints: Record<string, { x: number; y: number }>;
  bones: [string, string][];
  source: "camera_pose" | "rf_position";
};

function roomPersonEstimates(
  room: RfRoomLayout["room"],
  estimate?: RuViewZoneEstimate | null,
  activeTracking?: ActiveTrackingSnapshot | null
): RoomPersonEstimate[] {
  const tracks = tracksWithRoomPosition(activeTracking);
  if (tracks.length > 0) {
    return tracks.map((track, index) => {
      const cameraConfidence = track.confidence == null ? null : track.confidence / 100;
      const rfConfidence = track.source === "fusion" || track.status === "rf" ? track.rf_confidence : null;
      return {
        key: track.track_key,
        x: clamp(track.estimated_x_cm ?? 0, 0, room.width_cm),
        y: clamp(track.estimated_y_cm ?? 0, 0, room.depth_cm),
        confidence: Math.round((rfConfidence ?? cameraConfidence ?? 0) * 100),
        label: trackDisplayName(track),
        displayId: String(track.person_id ?? track.processor_track_id ?? index + 1),
        activeNodes: track.active_nodes ?? [],
        track,
      };
    });
  }
  void estimate;
  return [];
}

function isLive3DSceneObject(object: RfRoomObject): boolean {
  if (object.object_id.startsWith("draft-rf-link-")) return false;
  return !["activity_zone", "walkable_zone", "camera_view", "rf_link"].includes(object.object_type);
}

function RfRoomMap({
  snapshot,
  layout,
  estimate,
  activeTracking,
}: {
  snapshot: RfRoomSnapshot;
  layout?: RfRoomLayout | null;
  estimate?: RuViewZoneEstimate | null;
  activeTracking?: ActiveTrackingSnapshot | null;
}) {
  const viewLayout = layout ?? snapshot.layout;
  const { room } = viewLayout;
  const width = Math.max(room.width_cm, 1);
  const depth = Math.max(room.depth_cm, 1);
  const runtimeById = nodeRuntimeById(snapshot);
  const personDots = roomPersonEstimates(room, estimate, activeTracking).map((person) => ({
    ...person,
    left: `${(person.x / width) * 100}%`,
    top: `${(1 - person.y / depth) * 100}%`,
  }));

  return (
    <section className="rf-room-card">
      <div className="rf-room-card__header">
        <div>
          <div className="summary-card__label">Room map</div>
          <div className="summary-card__hint">
            {formatCm(room.width_cm)} x {formatCm(room.depth_cm)} x {formatCm(room.height_cm)}
          </div>
        </div>
        <div className="rf-room-scale">origin: bottom-left</div>
      </div>

      <div className="rf-room-map" style={{ aspectRatio: `${width} / ${depth}` }}>
        <div className="rf-room-map__axis rf-room-map__axis--x">{formatCm(room.width_cm)}</div>
        <div className="rf-room-map__axis rf-room-map__axis--y">{formatCm(room.depth_cm)}</div>
        {(viewLayout.objects ?? []).map((object) => {
          const left = `${(clamp(object.x_cm, 0, width) / width) * 100}%`;
          const top = `${(1 - clamp(object.y_cm + object.depth_cm, 0, depth) / depth) * 100}%`;
          const objectWidth = `${(clamp(object.width_cm, 1, width) / width) * 100}%`;
          const objectDepth = `${(clamp(object.depth_cm, 1, depth) / depth) * 100}%`;
          return (
            <div
              key={object.object_id}
              className={`rf-room-map-object rf-room-map-object--${object.object_type}`}
              style={{
                left,
                top,
                width: objectWidth,
                height: objectDepth,
                transform: `rotate(${object.rotation_deg ?? 0}deg)`,
              }}
              title={`${object.label}: ${Math.round(object.width_cm)} x ${Math.round(object.depth_cm)} x ${Math.round(object.height_cm)} cm`}
            >
              <span>{object.label}</span>
            </div>
          );
        })}
        {viewLayout.nodes.map((config) => {
          const node = runtimeById.get(config.node_id);
          const left = `${(config.x_cm / width) * 100}%`;
          const top = `${(1 - config.y_cm / depth) * 100}%`;
          const rssi = node ? nodeRssi(node) : null;
          return (
            <div
              key={config.node_id}
              className={`rf-node-dot rf-node-dot--${node?.online ? rssiTone(rssi) : "off"}`}
              style={{ left, top }}
              title={`${config.node_id} ${config.position_label}`}
            >
              <span className="rf-node-dot__label">{config.physical_label}</span>
              <span className="rf-node-dot__meta">
                {rssi == null ? "offline" : `${rssi} dBm`} / z {formatCm(config.z_cm)}
              </span>
            </div>
          );
        })}
        {personDots.map((personDot) => (
          <div
            key={personDot.key}
            className="rf-person-dot"
            style={{ left: personDot.left, top: personDot.top }}
            title={`${personDot.label}, confidence ${personDot.confidence}%`}
          >
            <span>{personDot.displayId}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

type Point3D = {
  x: number;
  y: number;
  z: number;
};

function cuboidCorners(object: RfRoomObject): Point3D[] {
  const x2 = object.x_cm + object.width_cm;
  const y2 = object.y_cm + object.depth_cm;
  const z2 = object.z_cm + object.height_cm;
  const centerX = object.x_cm + object.width_cm / 2;
  const centerY = object.y_cm + object.depth_cm / 2;
  const angle = ((object.rotation_deg ?? 0) * Math.PI) / 180;
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  const rotate = (point: Point3D): Point3D => {
    if (!object.rotation_deg) return point;
    const dx = point.x - centerX;
    const dy = point.y - centerY;
    return {
      x: centerX + dx * cos - dy * sin,
      y: centerY + dx * sin + dy * cos,
      z: point.z,
    };
  };
  return [
    { x: object.x_cm, y: object.y_cm, z: object.z_cm },
    { x: x2, y: object.y_cm, z: object.z_cm },
    { x: x2, y: y2, z: object.z_cm },
    { x: object.x_cm, y: y2, z: object.z_cm },
    { x: object.x_cm, y: object.y_cm, z: z2 },
    { x: x2, y: object.y_cm, z: z2 },
    { x: x2, y: y2, z: z2 },
    { x: object.x_cm, y: y2, z: z2 },
  ].map(rotate);
}

function RfRoomScene3D({
  snapshot,
  layout,
  estimate,
  activeTracking,
}: {
  snapshot: RfRoomSnapshot;
  layout?: RfRoomLayout | null;
  estimate?: RuViewZoneEstimate | null;
  activeTracking?: ActiveTrackingSnapshot | null;
}) {
  const viewLayout = layout ?? snapshot.layout;
  const { room } = viewLayout;
  const roomHeight = room.height_cm ?? 300;
  const runtimeById = nodeRuntimeById(snapshot);
  const objects = viewLayout.objects ?? [];
  const sceneObjects = objects.filter(isLive3DSceneObject);
  const [yaw, setYaw] = useState(35);
  const [pitch, setPitch] = useState(58);
  const [dragPoint, setDragPoint] = useState<{ x: number; y: number } | null>(null);

  const roomCorners: Point3D[] = [
    { x: 0, y: 0, z: 0 },
    { x: room.width_cm, y: 0, z: 0 },
    { x: room.width_cm, y: room.depth_cm, z: 0 },
    { x: 0, y: room.depth_cm, z: 0 },
    { x: 0, y: 0, z: roomHeight },
    { x: room.width_cm, y: 0, z: roomHeight },
    { x: room.width_cm, y: room.depth_cm, z: roomHeight },
    { x: 0, y: room.depth_cm, z: roomHeight },
  ];
  const nodePoints = viewLayout.nodes.flatMap((node) => [
    { x: node.x_cm, y: node.y_cm, z: 0 },
    { x: node.x_cm, y: node.y_cm, z: node.z_cm ?? 0 },
  ]);
  const allPoints = [...roomCorners, ...sceneObjects.flatMap(cuboidCorners), ...nodePoints];
  const yawRad = (yaw * Math.PI) / 180;
  const pitchRad = (pitch * Math.PI) / 180;
  const rawProject = (point: Point3D) => {
    const centeredX = point.x - room.width_cm / 2;
    const centeredY = point.y - room.depth_cm / 2;
    const rotatedX = centeredX * Math.cos(yawRad) - centeredY * Math.sin(yawRad);
    const rotatedY = centeredX * Math.sin(yawRad) + centeredY * Math.cos(yawRad);
    return {
      x: rotatedX,
      y: rotatedY * Math.sin(pitchRad) - point.z * Math.cos(pitchRad),
    };
  };
  const rawPoints = allPoints.map(rawProject);
  const minX = Math.min(...rawPoints.map((point) => point.x));
  const maxX = Math.max(...rawPoints.map((point) => point.x));
  const minY = Math.min(...rawPoints.map((point) => point.y));
  const maxY = Math.max(...rawPoints.map((point) => point.y));
  const scale = Math.min(860 / Math.max(maxX - minX, 1), 520 / Math.max(maxY - minY, 1));
  const project = (point: Point3D) => {
    const raw = rawProject(point);
    return {
      x: 70 + (raw.x - minX) * scale,
      y: 70 + (raw.y - minY) * scale,
    };
  };
  const points = (items: Point3D[]) => items.map((point) => {
    const projected = project(point);
    return `${projected.x.toFixed(1)},${projected.y.toFixed(1)}`;
  }).join(" ");
  const line = (from: Point3D, to: Point3D, key: string) => {
    const a = project(from);
    const b = project(to);
    return <line key={key} x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="rf-scene__edge" />;
  };
  const personEstimates = roomPersonEstimates(room, estimate, activeTracking);
  const personBodyHeight = Math.min(Math.max(roomHeight * 0.42, 90), 165);
  const buildPersonSkeleton = (personEstimate: RoomPersonEstimate): SceneSkeleton => {
    const lateral = { x: 1, y: 0 };
    const forward = { x: 0, y: 1 };
    const cameraTrack = personEstimate.track;
    const cameraKeypoints = cameraTrack?.keypoints;
    const cameraBox = cameraTrack?.bbox;
    if (
      Array.isArray(cameraKeypoints) &&
      cameraKeypoints.length >= 17 &&
      cameraBox &&
      cameraBox.x2 > cameraBox.x1 &&
      cameraBox.y2 > cameraBox.y1
    ) {
      const joints: Record<string, { x: number; y: number }> = {};
      const confs = Array.isArray(cameraTrack?.keypoint_conf) ? cameraTrack.keypoint_conf : [];
      const boxWidth = Math.max(1, cameraBox.x2 - cameraBox.x1);
      const boxHeight = Math.max(1, cameraBox.y2 - cameraBox.y1);
      const centerX = cameraBox.x1 + boxWidth / 2;
      const lowerBodyDepth: Record<number, number> = {
        11: 0,
        12: 0,
        13: 26,
        14: 26,
        15: 42,
        16: 42,
      };
      cameraKeypoints.forEach((point, index) => {
        if (!Array.isArray(point) || point.length < 2) return;
        const confidence = typeof confs[index] === "number" ? confs[index] : 1;
        if (confidence < 0.28) return;
        const sideOffset = clamp(((Number(point[0]) - centerX) / boxWidth) * 82, -58, 58);
        const forwardOffset = lowerBodyDepth[index] ?? 0;
        const z = clamp(((cameraBox.y2 - Number(point[1])) / boxHeight) * 178, 4, 184);
        joints[`kp${index}`] = project({
          x: personEstimate.x + lateral.x * sideOffset,
          y: personEstimate.y + lateral.y * sideOffset + forward.y * forwardOffset,
          z,
        });
      });
      const bones = COCO_POSE_EDGES.map(([from, to]) => [`kp${from}`, `kp${to}`] as [string, string]).filter(
        ([from, to]) => joints[from] && joints[to]
      );
      if (bones.length >= 6) {
        return { joints, bones, source: "camera_pose" as const };
      }
    }

    return { joints: {}, bones: [], source: "rf_position" as const };
  };
  const renderPerson = (personEstimate: RoomPersonEstimate) => {
    const base = project({ x: personEstimate.x, y: personEstimate.y, z: 0 });
    const body = project({ x: personEstimate.x, y: personEstimate.y, z: personBodyHeight });
    const head = project({ x: personEstimate.x, y: personEstimate.y, z: personBodyHeight + 24 });
    const activeNodes = viewLayout.nodes.filter((node) => personEstimate.activeNodes.includes(Number(node.physical_label)));
    const skeleton = buildPersonSkeleton(personEstimate);
    return (
      <g key={personEstimate.key} className="rf-scene-person">
        {activeNodes.map((node) => {
          const nodeTop = project({ x: node.x_cm, y: node.y_cm, z: node.z_cm ?? 0 });
          return (
            <line
              key={`person-ray-${personEstimate.key}-${node.node_id}`}
              x1={nodeTop.x}
              y1={nodeTop.y}
              x2={body.x}
              y2={body.y}
              className="rf-scene-person__ray"
            />
          );
        })}
        <ellipse cx={base.x} cy={base.y} rx="18" ry="8" className="rf-scene-person__shadow" />
        {skeleton.bones.map(([from, to]) => {
          const a = skeleton.joints[from];
          const b = skeleton.joints[to];
          return (
            <line
              key={`skeleton-${personEstimate.key}-${from}-${to}`}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              className="rf-scene-person__bone"
            />
          );
        })}
        {Object.entries(skeleton.joints).map(([name, joint]) => (
          <circle
            key={`joint-${personEstimate.key}-${name}`}
            cx={joint.x}
            cy={joint.y}
            r={name === "head" ? 8 : 4.5}
            className="rf-scene-person__joint"
          />
        ))}
        <circle cx={head.x} cy={head.y} r="12" className="rf-scene-person__head" />
        <text x={head.x + 18} y={head.y - 10} className="rf-scene-person__label">
          {personEstimate.label} {personEstimate.confidence}% {skeleton.source === "camera_pose" ? "pose" : "rf handoff"}
        </text>
      </g>
    );
  };

  const floor = [roomCorners[0], roomCorners[1], roomCorners[2], roomCorners[3]];
  const backWall = [roomCorners[3], roomCorners[2], roomCorners[6], roomCorners[7]];
  const leftWall = [roomCorners[0], roomCorners[3], roomCorners[7], roomCorners[4]];
  const roomEdges = [
    [roomCorners[0], roomCorners[1]],
    [roomCorners[1], roomCorners[2]],
    [roomCorners[2], roomCorners[3]],
    [roomCorners[3], roomCorners[0]],
    [roomCorners[4], roomCorners[5]],
    [roomCorners[5], roomCorners[6]],
    [roomCorners[6], roomCorners[7]],
    [roomCorners[7], roomCorners[4]],
    [roomCorners[0], roomCorners[4]],
    [roomCorners[1], roomCorners[5]],
    [roomCorners[2], roomCorners[6]],
    [roomCorners[3], roomCorners[7]],
  ];
  const setPreset = (nextYaw: number, nextPitch: number) => {
    setYaw(nextYaw);
    setPitch(nextPitch);
  };

  return (
    <section className="rf-room-card rf-scene-card">
      <div className="rf-room-card__header">
        <div>
          <div className="summary-card__label">Schematic 3D</div>
          <div className="summary-card__hint">Drag the room to rotate. This is the schematic base for the future Scanner View.</div>
        </div>
        <div className="page-actions">
          <span className="rf-room-scale">
            yaw {Math.round(yaw)} / pitch {Math.round(pitch)}
          </span>
          <button className="btn secondary rf-scene-control" type="button" onClick={() => setPreset(35, 58)}>
            Iso
          </button>
          <button className="btn secondary rf-scene-control" type="button" onClick={() => setPreset(0, 70)}>
            Front
          </button>
          <button className="btn secondary rf-scene-control" type="button" onClick={() => setPreset(90, 70)}>
            Side
          </button>
          <span className="rf-room-scale">{sceneObjects.length}/{objects.length} objects</span>
        </div>
      </div>

      <svg
        className={`rf-scene ${dragPoint ? "rf-scene--dragging" : ""}`}
        viewBox="0 0 1000 640"
        role="img"
        aria-label="Schematic 3D RF room"
        onPointerDown={(event) => {
          setDragPoint({ x: event.clientX, y: event.clientY });
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerMove={(event) => {
          if (!dragPoint) return;
          const dx = event.clientX - dragPoint.x;
          const dy = event.clientY - dragPoint.y;
          setYaw((value) => value + dx * 0.35);
          setPitch((value) => clamp(value - dy * 0.25, 25, 78));
          setDragPoint({ x: event.clientX, y: event.clientY });
        }}
        onPointerUp={(event) => {
          setDragPoint(null);
          try {
            event.currentTarget.releasePointerCapture(event.pointerId);
          } catch {
            // Pointer may already be released by the browser.
          }
        }}
        onPointerLeave={() => setDragPoint(null)}
      >
        <polygon points={points(leftWall)} className="rf-scene__wall" />
        <polygon points={points(backWall)} className="rf-scene__wall rf-scene__wall--back" />
        <polygon points={points(floor)} className="rf-scene__floor" />
        {roomEdges.map(([from, to], index) => line(from, to, `room-edge-${index}`))}

        {[...sceneObjects]
          .sort((a, b) => a.x_cm + a.y_cm - (b.x_cm + b.y_cm))
          .map((object) => {
            const [p000, p100, p110, , p001, p101, p111, p011] = cuboidCorners(object);
            const labelPoint = project({
              x: object.x_cm + object.width_cm / 2,
              y: object.y_cm + object.depth_cm / 2,
              z: object.z_cm + object.height_cm + 18,
            });
            return (
              <g key={object.object_id} className="rf-scene-object">
                <polygon points={points([p000, p100, p101, p001])} className="rf-scene-object__face rf-scene-object__face--front" />
                <polygon points={points([p100, p110, p111, p101])} className="rf-scene-object__face rf-scene-object__face--side" />
                <polygon points={points([p001, p101, p111, p011])} className="rf-scene-object__face rf-scene-object__face--top" />
                <text x={labelPoint.x} y={labelPoint.y} className="rf-scene-object__label">
                  {object.label}
                </text>
              </g>
            );
          })}

        {viewLayout.nodes.map((config) => {
          const runtime = runtimeById.get(config.node_id);
          const base = project({ x: config.x_cm, y: config.y_cm, z: 0 });
          const top = project({ x: config.x_cm, y: config.y_cm, z: config.z_cm ?? 0 });
          return (
            <g key={config.node_id} className={runtime?.online ? "rf-scene-node online" : "rf-scene-node"}>
              <line x1={base.x} y1={base.y} x2={top.x} y2={top.y} className="rf-scene-node__stem" />
              <circle cx={top.x} cy={top.y} r="9" className="rf-scene-node__dot" />
              <text x={top.x + 14} y={top.y - 8} className="rf-scene-node__label">
                #{config.physical_label}
              </text>
            </g>
          );
        })}

        {personEstimates.map(renderPerson)}

        <text x="70" y="610" className="rf-scene__axis">
          {formatCm(room.width_cm)} x {formatCm(room.depth_cm)} x {formatCm(room.height_cm)}
        </text>
      </svg>
    </section>
  );
}

type CloudPoint = Point3D & {
  intensity: number;
  size: number;
  kind: "room" | "object" | "node" | "person";
};

function liveRoomPoint(
  room: RfRoomLayout["room"],
  estimate?: RuViewZoneEstimate | null,
  activeTracking?: ActiveTrackingSnapshot | null
) {
  const activeRoomTrack = tracksWithRoomPosition(activeTracking)[0] ?? null;
  if (activeRoomTrack?.estimated_x_cm != null && activeRoomTrack.estimated_y_cm != null) {
    return {
      x: clamp(activeRoomTrack.estimated_x_cm, 0, room.width_cm),
      y: clamp(activeRoomTrack.estimated_y_cm, 0, room.depth_cm),
      confidence: activeRoomTrack.rf_confidence ?? 0,
      label: trackDisplayName(activeRoomTrack),
    };
  }
  if (estimate?.ready && estimate.estimated_x_cm != null && estimate.estimated_y_cm != null) {
    return {
      x: clamp(estimate.estimated_x_cm, 0, room.width_cm),
      y: clamp(estimate.estimated_y_cm, 0, room.depth_cm),
      confidence: estimate.confidence,
      label: "RuView",
    };
  }
  return null;
}

function buildScannerPointCloud(
  layout: RfRoomLayout,
  estimate?: RuViewZoneEstimate | null,
  activeTracking?: ActiveTrackingSnapshot | null
): CloudPoint[] {
  const points: CloudPoint[] = [];
  const { room } = layout;
  const height = room.height_cm ?? 300;
  const add = (x: number, y: number, z: number, intensity = 0.48, size = 1.4, kind: CloudPoint["kind"] = "room") => {
    points.push({ x, y, z, intensity, size, kind });
  };
  const step = 36;
  const wallStep = 32;

  for (let x = 0; x <= room.width_cm; x += step) {
    for (let y = 0; y <= room.depth_cm; y += step) add(x, y, 0, 0.24, 1.1);
  }
  for (let x = 0; x <= room.width_cm; x += wallStep) {
    for (let z = 0; z <= height; z += wallStep) {
      add(x, 0, z, 0.52, 1.25);
      add(x, room.depth_cm, z, 0.52, 1.25);
    }
  }
  for (let y = 0; y <= room.depth_cm; y += wallStep) {
    for (let z = 0; z <= height; z += wallStep) {
      add(0, y, z, 0.52, 1.25);
      add(room.width_cm, y, z, 0.52, 1.25);
    }
  }

  const addObjectFace = (object: RfRoomObject) => {
    const objectStep = 18;
    const x2 = object.x_cm + object.width_cm;
    const y2 = object.y_cm + object.depth_cm;
    const z2 = object.z_cm + object.height_cm;
    for (let x = object.x_cm; x <= x2; x += objectStep) {
      for (let y = object.y_cm; y <= y2; y += objectStep) add(x, y, z2, 0.76, 1.7, "object");
    }
    for (let x = object.x_cm; x <= x2; x += objectStep) {
      for (let z = object.z_cm; z <= z2; z += objectStep) {
        add(x, object.y_cm, z, 0.62, 1.45, "object");
        add(x, y2, z, 0.62, 1.45, "object");
      }
    }
    for (let y = object.y_cm; y <= y2; y += objectStep) {
      for (let z = object.z_cm; z <= z2; z += objectStep) {
        add(object.x_cm, y, z, 0.62, 1.45, "object");
        add(x2, y, z, 0.62, 1.45, "object");
      }
    }
  };
  (layout.objects ?? []).forEach(addObjectFace);

  layout.nodes.forEach((node) => {
    add(node.x_cm, node.y_cm, node.z_cm ?? 0, 0.95, 3.2, "node");
    add(node.x_cm, node.y_cm, 0, 0.36, 1.5, "node");
  });

  const livePoint = liveRoomPoint(room, estimate, activeTracking);
  if (livePoint) {
    for (let z = 0; z <= 175; z += 14) {
      const radius = z > 140 ? 16 : 9;
      for (let angle = 0; angle < Math.PI * 2; angle += Math.PI / 5) {
        add(
          livePoint.x + Math.cos(angle) * radius,
          livePoint.y + Math.sin(angle) * radius,
          z,
          1,
          z > 140 ? 3.2 : 2.4,
          "person"
        );
      }
    }
  }
  return points;
}

function ScannerView({
  layout,
  estimate,
  activeTracking,
}: {
  layout: RfRoomLayout;
  estimate?: RuViewZoneEstimate | null;
  activeTracking?: ActiveTrackingSnapshot | null;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const keysRef = useRef<Set<string>>(new Set());
  const dragRef = useRef<{ x: number; y: number } | null>(null);
  const cameraRef = useRef({
    x: layout.room.width_cm / 2,
    y: Math.max(40, layout.room.depth_cm * 0.18),
    z: 155,
    yaw: Math.PI / 2,
    pitch: 0,
  });
  const cloud = useMemo(() => buildScannerPointCloud(layout, estimate, activeTracking), [activeTracking, estimate, layout]);
  const livePoint = liveRoomPoint(layout.room, estimate, activeTracking);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      keysRef.current.add(event.key.toLowerCase());
    };
    const handleKeyUp = (event: KeyboardEvent) => {
      keysRef.current.delete(event.key.toLowerCase());
    };
    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("keyup", handleKeyUp);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("keyup", handleKeyUp);
    };
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    let frame = 0;
    let last = performance.now();
    const render = (now: number) => {
      const dt = Math.min((now - last) / 1000, 0.05);
      last = now;
      const camera = cameraRef.current;
      const speed = 170 * dt;
      const turnSpeed = 1.8 * dt;
      const keys = keysRef.current;
      if (keys.has("arrowleft")) camera.yaw -= turnSpeed;
      if (keys.has("arrowright")) camera.yaw += turnSpeed;
      if (keys.has("arrowup")) camera.pitch = clamp(camera.pitch + turnSpeed * 0.55, -0.55, 0.55);
      if (keys.has("arrowdown")) camera.pitch = clamp(camera.pitch - turnSpeed * 0.55, -0.55, 0.55);
      const forwardX = Math.cos(camera.yaw);
      const forwardY = Math.sin(camera.yaw);
      const rightX = Math.cos(camera.yaw + Math.PI / 2);
      const rightY = Math.sin(camera.yaw + Math.PI / 2);
      if (keys.has("w") || keys.has("ц")) {
        camera.x += forwardX * speed;
        camera.y += forwardY * speed;
      }
      if (keys.has("s") || keys.has("ы")) {
        camera.x -= forwardX * speed;
        camera.y -= forwardY * speed;
      }
      if (keys.has("a") || keys.has("ф")) {
        camera.x -= rightX * speed;
        camera.y -= rightY * speed;
      }
      if (keys.has("d") || keys.has("в")) {
        camera.x += rightX * speed;
        camera.y += rightY * speed;
      }
      camera.x = clamp(camera.x, 8, layout.room.width_cm - 8);
      camera.y = clamp(camera.y, 8, layout.room.depth_cm - 8);

      const width = canvas.clientWidth * window.devicePixelRatio;
      const height = canvas.clientHeight * window.devicePixelRatio;
      if (canvas.width !== Math.round(width) || canvas.height !== Math.round(height)) {
        canvas.width = Math.round(width);
        canvas.height = Math.round(height);
      }
      context.fillStyle = "#020202";
      context.fillRect(0, 0, canvas.width, canvas.height);

      const focal = canvas.width * 0.62;
      const projected: { x: number; y: number; depth: number; alpha: number; radius: number; kind: CloudPoint["kind"] }[] = [];
      for (const point of cloud) {
        const dx = point.x - camera.x;
        const dy = point.y - camera.y;
        const dz = point.z - camera.z;
        const forward = dx * Math.cos(camera.yaw) + dy * Math.sin(camera.yaw);
        const right = -dx * Math.sin(camera.yaw) + dy * Math.cos(camera.yaw);
        const depth = forward * Math.cos(camera.pitch) + dz * Math.sin(camera.pitch);
        const vertical = -forward * Math.sin(camera.pitch) + dz * Math.cos(camera.pitch);
        if (depth <= 8 || depth > 1200) continue;
        const x = canvas.width / 2 + (right / depth) * focal;
        const y = canvas.height / 2 - (vertical / depth) * focal;
        if (x < -40 || x > canvas.width + 40 || y < -40 || y > canvas.height + 40) continue;
        const distanceFade = clamp(1 - depth / 1200, 0.12, 1);
        projected.push({
          x,
          y,
          depth,
          alpha: point.intensity * distanceFade,
          radius: Math.max(0.8, point.size * distanceFade * window.devicePixelRatio),
          kind: point.kind,
        });
      }
      projected.sort((a, b) => b.depth - a.depth);
      for (const point of projected) {
        const pulse = point.kind === "person" ? 0.35 + Math.sin(now / 130) * 0.18 : 0;
        const alpha = clamp(point.alpha + pulse, 0.08, 1);
        const shade = point.kind === "node" ? 230 : point.kind === "person" ? 255 : point.kind === "object" ? 205 : 168;
        context.fillStyle = `rgba(${shade}, ${shade}, ${shade}, ${alpha})`;
        context.beginPath();
        context.arc(point.x, point.y, point.radius + (point.kind === "person" ? 1.1 : 0), 0, Math.PI * 2);
        context.fill();
      }
      context.strokeStyle = "rgba(255,255,255,0.34)";
      context.lineWidth = window.devicePixelRatio;
      context.beginPath();
      context.moveTo(canvas.width / 2 - 12, canvas.height / 2);
      context.lineTo(canvas.width / 2 + 12, canvas.height / 2);
      context.moveTo(canvas.width / 2, canvas.height / 2 - 12);
      context.lineTo(canvas.width / 2, canvas.height / 2 + 12);
      context.stroke();
      frame = window.requestAnimationFrame(render);
    };
    frame = window.requestAnimationFrame(render);
    return () => window.cancelAnimationFrame(frame);
  }, [cloud, layout.room.depth_cm, layout.room.width_cm]);

  return (
    <section className="rf-room-card scanner-view-card">
      <div className="rf-room-card__header">
        <div>
          <div className="summary-card__label">Scanner View</div>
          <div className="summary-card__hint">First-person monochrome point cloud. WASD moves, mouse drag looks around.</div>
        </div>
        <div className="page-actions">
          <span className="rf-room-scale">{cloud.length} points</span>
          <span className="rf-room-scale">
            {livePoint ? `${livePoint.label}: ${Math.round(livePoint.x)}, ${Math.round(livePoint.y)} cm` : "no live RF point"}
          </span>
        </div>
      </div>
      <canvas
        ref={canvasRef}
        className="scanner-canvas"
        onPointerDown={(event) => {
          dragRef.current = { x: event.clientX, y: event.clientY };
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerMove={(event) => {
          const drag = dragRef.current;
          if (!drag) return;
          const camera = cameraRef.current;
          camera.yaw += (event.clientX - drag.x) * 0.0045;
          camera.pitch = clamp(camera.pitch - (event.clientY - drag.y) * 0.0035, -0.55, 0.55);
          dragRef.current = { x: event.clientX, y: event.clientY };
        }}
        onPointerUp={(event) => {
          dragRef.current = null;
          try {
            event.currentTarget.releasePointerCapture(event.pointerId);
          } catch {
            // Pointer may already be released.
          }
        }}
        onPointerLeave={() => {
          dragRef.current = null;
        }}
      />
      <div className="scanner-view-hint">
        Geometry is generated from the editable room layout. RF CSI drives the live marker; it does not create dense LiDAR geometry by itself.
      </div>
    </section>
  );
}

function RfLayoutEditor({
  layout,
  dirty,
  saving,
  onChange,
  onReset,
  onSave,
}: {
  layout: RfRoomLayout | null;
  dirty: boolean;
  saving: boolean;
  onChange: (layout: RfRoomLayout) => void;
  onReset: () => void;
  onSave: () => void;
}) {
  if (!layout) return null;
  const objects = layout.objects ?? [];

  const updateRoomNumber = (field: "width_cm" | "depth_cm" | "height_cm", value: string) => {
    onChange({ ...layout, room: { ...layout.room, [field]: toNumber(value) } });
  };
  const updateNodeNumber = (index: number, field: "x_cm" | "y_cm" | "z_cm", value: string) => {
    onChange({
      ...layout,
      nodes: layout.nodes.map((node, nodeIndex) => (nodeIndex === index ? { ...node, [field]: toNumber(value) } : node)),
    });
  };
  const updateObjectText = (index: number, field: "object_id" | "label" | "object_type", value: string) => {
    onChange({
      ...layout,
      objects: objects.map((object, objectIndex) => (objectIndex === index ? { ...object, [field]: value } : object)),
    });
  };
  const updateObjectNumber = (
    index: number,
    field: "x_cm" | "y_cm" | "z_cm" | "width_cm" | "depth_cm" | "height_cm" | "rotation_deg",
    value: string
  ) => {
    onChange({
      ...layout,
      objects: objects.map((object, objectIndex) => (objectIndex === index ? { ...object, [field]: toNumber(value) } : object)),
    });
  };
  const addObject = () => {
    const nextIndex = objects.length + 1;
    onChange({
      ...layout,
      objects: [
        ...objects,
        {
          object_id: `object-${nextIndex}-${Date.now().toString(36)}`,
          label: `Object ${nextIndex}`,
          object_type: "box",
          x_cm: 100,
          y_cm: 100,
          z_cm: 0,
          width_cm: 80,
          depth_cm: 60,
          height_cm: 80,
          rotation_deg: 0,
        },
      ],
    });
  };
  const removeObject = (index: number) => {
    onChange({ ...layout, objects: objects.filter((_, objectIndex) => objectIndex !== index) });
  };

  return (
    <section className="rf-room-card rf-layout-editor">
      <div className="rf-room-card__header">
        <div>
          <div className="summary-card__label">Room editor</div>
          <div className="summary-card__hint">Adjust dimensions, anchors and schematic objects for the current demo room</div>
        </div>
        <div className="page-actions">
          <button className="btn secondary" type="button" onClick={onReset} disabled={!dirty || saving}>
            Reset
          </button>
          <button className="btn" type="button" onClick={onSave} disabled={!dirty || saving}>
            {saving ? "Saving..." : "Save layout"}
          </button>
        </div>
      </div>

      <div className="rf-editor-grid">
        <label>
          <span>Layout name</span>
          <input value={layout.name} onChange={(event) => onChange({ ...layout, name: event.target.value })} />
        </label>
        <label>
          <span>Width, cm</span>
          <input type="number" min="1" value={layout.room.width_cm} onChange={(event) => updateRoomNumber("width_cm", event.target.value)} />
        </label>
        <label>
          <span>Depth, cm</span>
          <input type="number" min="1" value={layout.room.depth_cm} onChange={(event) => updateRoomNumber("depth_cm", event.target.value)} />
        </label>
        <label>
          <span>Height, cm</span>
          <input
            type="number"
            min="1"
            value={layout.room.height_cm ?? 0}
            onChange={(event) => updateRoomNumber("height_cm", event.target.value)}
          />
        </label>
      </div>

      <div className="rf-editor-block">
        <div className="rf-editor-block__title">ESP32 anchors</div>
        <div className="rf-editor-scroll">
          <table className="soft-table rf-editor-table">
            <thead>
              <tr>
                <th>Node</th>
                <th>X</th>
                <th>Y</th>
                <th>Z</th>
              </tr>
            </thead>
            <tbody>
              {layout.nodes.map((node, index) => (
                <tr key={node.node_id}>
                  <td>
                    #{node.physical_label} {node.position_label}
                  </td>
                  <td>
                    <input type="number" min="0" value={node.x_cm} onChange={(event) => updateNodeNumber(index, "x_cm", event.target.value)} />
                  </td>
                  <td>
                    <input type="number" min="0" value={node.y_cm} onChange={(event) => updateNodeNumber(index, "y_cm", event.target.value)} />
                  </td>
                  <td>
                    <input
                      type="number"
                      min="0"
                      value={node.z_cm ?? 0}
                      onChange={(event) => updateNodeNumber(index, "z_cm", event.target.value)}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="rf-editor-block">
        <div className="rf-editor-block__title">
          Objects
          <button className="btn secondary" type="button" onClick={addObject}>
            Add object
          </button>
        </div>
        <div className="rf-editor-scroll">
          <table className="soft-table rf-editor-table rf-editor-table--objects">
            <thead>
              <tr>
                <th>Label</th>
                <th>Type</th>
                <th>X/Y/Z</th>
                <th>W/D/H</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {objects.map((object, index) => (
                <tr key={object.object_id}>
                  <td>
                    <input value={object.label} onChange={(event) => updateObjectText(index, "label", event.target.value)} />
                  </td>
                  <td>
                    <input value={object.object_type} onChange={(event) => updateObjectText(index, "object_type", event.target.value)} />
                  </td>
                  <td>
                    <div className="rf-editor-triplet">
                      <input type="number" min="0" value={object.x_cm} onChange={(event) => updateObjectNumber(index, "x_cm", event.target.value)} />
                      <input type="number" min="0" value={object.y_cm} onChange={(event) => updateObjectNumber(index, "y_cm", event.target.value)} />
                      <input type="number" min="0" value={object.z_cm} onChange={(event) => updateObjectNumber(index, "z_cm", event.target.value)} />
                    </div>
                  </td>
                  <td>
                    <div className="rf-editor-triplet">
                      <input
                        type="number"
                        min="1"
                        value={object.width_cm}
                        onChange={(event) => updateObjectNumber(index, "width_cm", event.target.value)}
                      />
                      <input
                        type="number"
                        min="1"
                        value={object.depth_cm}
                        onChange={(event) => updateObjectNumber(index, "depth_cm", event.target.value)}
                      />
                      <input
                        type="number"
                        min="1"
                        value={object.height_cm}
                        onChange={(event) => updateObjectNumber(index, "height_cm", event.target.value)}
                      />
                    </div>
                  </td>
                  <td>
                    <button className="btn secondary" type="button" onClick={() => removeObject(index)}>
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
              {objects.length === 0 && (
                <tr>
                  <td colSpan={5}>No objects yet. Add simple boxes and tune their dimensions for the demo room.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

const CAMERA_CALIBRATION_LABELS = ["Near left", "Near right", "Far right", "Far left"];

function defaultImageCalibrationPoints(): CameraRoomCalibration["image_points"] {
  return [
    { x: 0.08, y: 0.86, normalized: true },
    { x: 0.92, y: 0.86, normalized: true },
    { x: 0.92, y: 0.38, normalized: true },
    { x: 0.08, y: 0.38, normalized: true },
  ];
}

function defaultRoomCalibrationPoints(layout: RfRoomLayout): CameraRoomPoint[] {
  return [
    { x_cm: 0, y_cm: 0, z_cm: 0 },
    { x_cm: layout.room.width_cm, y_cm: 0, z_cm: 0 },
    { x_cm: layout.room.width_cm, y_cm: layout.room.depth_cm, z_cm: 0 },
    { x_cm: 0, y_cm: layout.room.depth_cm, z_cm: 0 },
  ];
}

function normalizeImageCalibrationPoints(calibration: CameraRoomCalibration | null): CameraRoomCalibration["image_points"] {
  if (!calibration || calibration.image_points.length !== 4) {
    return defaultImageCalibrationPoints();
  }
  return calibration.image_points.map((point) => ({
    x: clamp(point.x, 0, point.normalized === false ? Number.MAX_SAFE_INTEGER : 1),
    y: clamp(point.y, 0, point.normalized === false ? Number.MAX_SAFE_INTEGER : 1),
    normalized: point.normalized !== false,
  }));
}

function CameraRoomCalibrationPanel({
  token,
  cameraId,
  layout,
  onError,
}: {
  token: string | null;
  cameraId: number;
  layout: RfRoomLayout;
  onError: (message: string | null) => void;
}) {
  const frameUrlRef = useRef<string | null>(null);
  const [calibration, setCalibration] = useState<CameraRoomCalibration | null>(null);
  const [imagePoints, setImagePoints] = useState<CameraRoomCalibration["image_points"]>(defaultImageCalibrationPoints);
  const [roomPoints, setRoomPoints] = useState<CameraRoomPoint[]>(() => defaultRoomCalibrationPoints(layout));
  const [selectedPoint, setSelectedPoint] = useState(0);
  const [frameUrl, setFrameUrl] = useState<string | null>(null);
  const [frameSize, setFrameSize] = useState({ width: 0, height: 0 });
  const [ledCandidates, setLedCandidates] = useState<CameraRoomLedCandidate[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const refreshFrame = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    onError(null);
    try {
      const blob = await getCameraRoomFrame(token, cameraId);
      const nextUrl = URL.createObjectURL(blob);
      if (frameUrlRef.current) {
        URL.revokeObjectURL(frameUrlRef.current);
      }
      frameUrlRef.current = nextUrl;
      setFrameUrl(nextUrl);
      setLedCandidates([]);
      setMessage("Frame refreshed. Keep this PTZ position fixed while saving calibration.");
    } catch (event: any) {
      onError(event?.message || "Failed to load camera frame");
    } finally {
      setLoading(false);
    }
  }, [cameraId, onError, token]);

  const loadCalibration = useCallback(async () => {
    if (!token) return;
    try {
      const current = await getCameraRoomCalibration(token, cameraId);
      setCalibration(current);
      setImagePoints(normalizeImageCalibrationPoints(current));
      setRoomPoints(current.room_points.length === 4 ? current.room_points : defaultRoomCalibrationPoints(layout));
    } catch (event: any) {
      onError(event?.message || "Failed to load camera-room calibration");
    }
  }, [cameraId, layout, onError, token]);

  useEffect(() => {
    loadCalibration();
    refreshFrame();
    return () => {
      if (frameUrlRef.current) {
        URL.revokeObjectURL(frameUrlRef.current);
        frameUrlRef.current = null;
      }
    };
  }, [loadCalibration, refreshFrame]);

  const handleFrameClick = useCallback(
    (event: React.PointerEvent<HTMLButtonElement>) => {
      const rect = event.currentTarget.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      const x = clamp((event.clientX - rect.left) / rect.width, 0, 1);
      const y = clamp((event.clientY - rect.top) / rect.height, 0, 1);
      setImagePoints((current) => current.map((point, index) => (index === selectedPoint ? { ...point, x, y, normalized: true } : point)));
      setSelectedPoint((current) => (current >= 3 ? current : current + 1));
      setMessage(`Point ${selectedPoint + 1} set on the camera frame.`);
    },
    [selectedPoint]
  );

  const updateRoomPoint = useCallback((index: number, field: keyof CameraRoomPoint, value: string) => {
    setRoomPoints((current) =>
      current.map((point, pointIndex) => (pointIndex === index ? { ...point, [field]: toNumber(value) } : point))
    );
  }, []);

  const resetDraft = useCallback(() => {
    setImagePoints(defaultImageCalibrationPoints());
    setRoomPoints(defaultRoomCalibrationPoints(layout));
    setSelectedPoint(0);
    setMessage("Draft reset to room corners. Click the visible floor points again before saving.");
  }, [layout]);

  const detectLeds = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    onError(null);
    try {
      const detection = await getCameraRoomRedLeds(token, cameraId);
      setFrameSize({ width: detection.frame_width, height: detection.frame_height });
      setLedCandidates(detection.candidates);
      setMessage(
        detection.candidates.length
          ? `Detected ${detection.candidates.length} red LED candidate(s). Use them only as visual hints.`
          : "No red LED candidates detected in the current view."
      );
    } catch (event: any) {
      onError(event?.message || "Failed to detect red LEDs");
    } finally {
      setLoading(false);
    }
  }, [cameraId, onError, token]);

  const saveCalibration = useCallback(async () => {
    if (!token) return;
    setSaving(true);
    onError(null);
    try {
      const saved = await saveCameraRoomCalibration(token, cameraId, {
        enabled: true,
        label: `Camera ${cameraId} fixed live view`,
        image_points: imagePoints.map((point) => ({ x: point.x, y: point.y, normalized: true })),
        room_points: roomPoints.map((point) => ({ x_cm: point.x_cm, y_cm: point.y_cm, z_cm: point.z_cm ?? 0 })),
        source: "manual_fixed_view",
      });
      setCalibration(saved);
      setMessage("Calibration saved. Do not move the PTZ camera during live tracking.");
    } catch (event: any) {
      onError(event?.message || "Failed to save camera-room calibration");
    } finally {
      setSaving(false);
    }
  }, [cameraId, imagePoints, onError, roomPoints, token]);

  return (
    <section className="rf-room-card camera-calibration-panel">
      <div className="rf-room-card__header">
        <div>
          <div className="summary-card__label">Camera-room calibration</div>
          <div className="summary-card__hint">
            Fixed PTZ view for camera-supervised RF. Click four floor points and bind them to room coordinates.
          </div>
        </div>
        <div className="page-actions">
          <button className="btn secondary" type="button" onClick={refreshFrame} disabled={loading || saving}>
            {loading ? "Loading..." : "Refresh frame"}
          </button>
          <button className="btn secondary" type="button" onClick={detectLeds} disabled={loading || saving}>
            Find red LEDs
          </button>
          <button className="btn" type="button" onClick={saveCalibration} disabled={saving || loading}>
            {saving ? "Saving..." : "Save camera map"}
          </button>
        </div>
      </div>

      <div className="camera-calibration-grid">
        <button className="camera-calibration-frame" type="button" onPointerDown={handleFrameClick}>
          {frameUrl ? (
            <img
              src={frameUrl}
              alt="Current camera frame for room calibration"
              onLoad={(event) =>
                setFrameSize({ width: event.currentTarget.naturalWidth || 0, height: event.currentTarget.naturalHeight || 0 })
              }
            />
          ) : (
            <span className="camera-calibration-placeholder">Camera frame is not loaded</span>
          )}
          {imagePoints.map((point, index) => (
            <span
              key={`point-${index}`}
              className={`camera-calibration-point${index === selectedPoint ? " active" : ""}`}
              style={{ left: `${point.x * 100}%`, top: `${point.y * 100}%` }}
            >
              {index + 1}
            </span>
          ))}
          {ledCandidates.map((candidate, index) => {
            const left = frameSize.width ? (candidate.x / frameSize.width) * 100 : 0;
            const top = frameSize.height ? (candidate.y / frameSize.height) * 100 : 0;
            return (
              <span
                key={`led-${index}-${candidate.x}-${candidate.y}`}
                className="camera-led-candidate"
                style={{ left: `${left}%`, top: `${top}%` }}
                title={`LED candidate score ${candidate.score}`}
              />
            );
          })}
        </button>

        <div className="camera-calibration-side">
          <div className="scanner-view-hint">
            Red LEDs are useful as visual anchors, but direct floor points are better for person coordinates. Moving PTZ requires recalibration.
          </div>
          <div className="camera-calibration-points">
            {CAMERA_CALIBRATION_LABELS.map((label, index) => (
              <button
                key={label}
                className={`camera-point-tab${index === selectedPoint ? " active" : ""}`}
                type="button"
                onClick={() => setSelectedPoint(index)}
              >
                {index + 1}. {label}
              </button>
            ))}
          </div>
          <div className="rf-editor-scroll">
            <table className="soft-table rf-editor-table camera-calibration-table">
              <thead>
                <tr>
                  <th>Point</th>
                  <th>Image X/Y</th>
                  <th>Room X/Y/Z, cm</th>
                </tr>
              </thead>
              <tbody>
                {roomPoints.map((point, index) => (
                  <tr key={`room-point-${index}`}>
                    <td>{index + 1}</td>
                    <td>
                      {Math.round(imagePoints[index].x * 1000) / 10}% / {Math.round(imagePoints[index].y * 1000) / 10}%
                    </td>
                    <td>
                      <div className="rf-editor-triplet">
                        <input
                          type="number"
                          value={formatPointValue(point.x_cm)}
                          onChange={(event) => updateRoomPoint(index, "x_cm", event.target.value)}
                        />
                        <input
                          type="number"
                          value={formatPointValue(point.y_cm)}
                          onChange={(event) => updateRoomPoint(index, "y_cm", event.target.value)}
                        />
                        <input
                          type="number"
                          value={formatPointValue(point.z_cm ?? 0)}
                          onChange={(event) => updateRoomPoint(index, "z_cm", event.target.value)}
                        />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="camera-calibration-footer">
            <button className="btn secondary" type="button" onClick={resetDraft} disabled={saving || loading}>
              Reset draft
            </button>
            <span>
              Source: <strong>{calibration?.source ?? "not saved"}</strong>
            </span>
            {message && <span>{message}</span>}
          </div>
        </div>
      </div>
    </section>
  );
}

function RfNodeCard({ node }: { node: RfNodeRuntime }) {
  const rssi = nodeRssi(node);
  const tone = node.online ? rssiTone(rssi) : "off";
  const topNetworks = strongestNetworks(node);

  return (
    <article className="rf-node-card">
      <div className="rf-node-card__top">
        <div>
          <div className="rf-node-card__id">
            #{node.config.physical_label} {node.config.node_id}
          </div>
          <div className="summary-card__hint">{node.config.position_label}</div>
        </div>
        <span className={`rf-status rf-status--${tone}`}>{node.online ? "online" : "offline"}</span>
      </div>

      <div className="rf-node-card__metrics">
        <div>
          <span>IP</span>
          <strong>{node.config.ip}</strong>
        </div>
        <div>
          <span>RSSI</span>
          <strong>{rssi == null ? "n/a" : `${rssi} dBm`}</strong>
        </div>
        <div>
          <span>Height</span>
          <strong>{formatCm(node.config.z_cm)}</strong>
        </div>
        <div>
          <span>Latency</span>
          <strong>{node.latency_ms == null ? "n/a" : `${node.latency_ms.toFixed(1)} ms`}</strong>
        </div>
      </div>

      <div className="rf-node-card__footer">
        <span>{node.health?.ssid || "no ssid"}</span>
        <span>{node.health?.bssid || node.config.mac}</span>
        <span>{formatUptime(node.health?.uptime_ms)}</span>
      </div>

      {topNetworks.length > 0 && (
        <div className="rf-node-card__scan">
          {topNetworks.map((network) => (
            <span key={`${network.bssid}-${network.ssid}`}>
              {network.ssid || "hidden"} {network.rssi} dBm
            </span>
          ))}
        </div>
      )}

      {node.error && <div className="rf-node-card__error">{node.error}</div>}
    </article>
  );
}

type RuViewLink = RuViewBridgeStatus["links"][number];

function linkQualityTone(score?: number | null): "good" | "warn" | "bad" | "off" {
  if (score == null || score <= 0) return "off";
  if (score >= 0.62) return "good";
  if (score >= 0.32) return "warn";
  return "bad";
}

function formatQuality(score?: number | null): string {
  return score == null ? "n/a" : `${Math.round(score * 100)}%`;
}

function formatAgeMs(age?: number | null): string {
  if (age == null) return "n/a";
  if (age < 1000) return `${age} ms`;
  return `${(age / 1000).toFixed(age < 10000 ? 1 : 0)} s`;
}

function readMetric(record: Record<string, unknown> | null | undefined, key: string): string {
  const value = record?.[key];
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(1);
  if (typeof value === "string") return value;
  if (typeof value === "boolean") return value ? "yes" : "no";
  return "n/a";
}

function nodeLabelFromLink(link: RuViewLink, side: "rx" | "tx"): string {
  if (side === "rx") return link.rx_physical_label ?? `#${link.rx_node_id}`;
  return link.tx_physical_label ?? (link.tx_node_id ? `#${link.tx_node_id}` : link.tx_mac ?? "unknown");
}

function RuViewBridgePanel({
  status,
  upstream,
  calibration,
  estimate,
  liveEnabled,
  onStart,
  onToggleLive,
}: {
  status: RuViewBridgeStatus | null;
  upstream: RuViewUpstreamStatus | null;
  calibration: RuViewCalibrationHistory | null;
  estimate: RuViewZoneEstimate | null;
  liveEnabled: boolean;
  onStart: () => void;
  onToggleLive: () => void;
}) {
  const nodes = status?.nodes ?? [];
  const links = status?.links ?? [];
  const rfHealth = status?.rf_health ?? [];
  const activeNodes = nodes.filter((node) => !node.stale);
  const activeLinks = links.filter((link) => !link.stale);
  const activePairwiseLinks = activeLinks.filter((link) => link.pairwise && link.tx_node_id > 0);
  const activeUnknownLinks = activeLinks.filter((link) => !link.pairwise || link.tx_node_id <= 0 || link.unknown_peer);
  const healthyRfNodes = rfHealth.filter((node) => !node.stale);
  const totalRate = activeNodes.reduce((sum, node) => sum + (node.packet_rate_hz ?? 0), 0);
  const totalLinkRate = activePairwiseLinks.reduce((sum, link) => sum + (link.packet_rate_hz ?? 0), 0);
  const matrixNodeIds = Array.from(
    new Set([
      ...rfHealth.map((node) => node.node_id),
      ...activePairwiseLinks.flatMap((link) => [link.rx_node_id, link.tx_node_id]),
    ])
  )
    .filter((nodeId) => nodeId > 0)
    .sort((a, b) => a - b);
  const expectedDirections = Math.max(matrixNodeIds.length * Math.max(matrixNodeIds.length - 1, 0), 1);
  const coveragePercent = Math.round((activePairwiseLinks.length / expectedDirections) * 100);
  const averageQuality =
    activePairwiseLinks.length > 0
      ? activePairwiseLinks.reduce((sum, link) => sum + (link.quality_score ?? 0), 0) / activePairwiseLinks.length
      : null;
  const linkByDirection = new Map(activePairwiseLinks.map((link) => [`${link.rx_node_id}-${link.tx_node_id}`, link]));
  const stimulatorTone = !status?.stimulator_enabled ? "off" : status.stimulator_running ? "good" : "warn";
  const upstreamPersons =
    typeof upstream?.pose_current?.total_persons === "number"
      ? upstream.pose_current.total_persons
      : Array.isArray(upstream?.pose_current?.persons)
        ? upstream.pose_current.persons.length
        : null;
  const livePoint =
    estimate?.ready && estimate.estimated_x_cm != null && estimate.estimated_y_cm != null
      ? {
          x: Math.round(estimate.estimated_x_cm),
          y: Math.round(estimate.estimated_y_cm),
          confidence: Math.round(estimate.confidence * 100),
          nodes: estimate.active_nodes.join(", ") || "n/a",
        }
      : null;
  return (
    <section className="rf-room-card ruview-panel">
      <div className="rf-room-card__header">
        <div>
          <div className="summary-card__label">RuView CSI Bridge</div>
          <div className="summary-card__hint">
            UDP {status?.bind ?? "0.0.0.0"}:{status?.port ?? 5005}, raw CSI packets from ESP32-S3 firmware
          </div>
        </div>
        <div className="page-actions">
          <span className={`rf-status rf-status--${stimulatorTone}`}>
            {status?.stimulator_running ? "stimulating" : "stim off"}
          </span>
          <span className={`rf-status rf-status--${status?.listening ? "good" : "off"}`}>
            {status?.listening ? "listening" : "stopped"}
          </span>
          <span className={`rf-status rf-status--${upstream?.reachable ? "good" : "off"}`}>
            {upstream?.reachable ? "RuView upstream" : "upstream off"}
          </span>
          <button className="btn secondary" type="button" onClick={onToggleLive}>
            {liveEnabled ? "Pause live" : "Resume live"}
          </button>
          <span className="rf-status rf-status--good">camera-supervised labels</span>
          <button className="btn secondary" type="button" onClick={onStart}>
            Start bridge
          </button>
        </div>
      </div>

      <div className={`ruview-live-strip ${liveEnabled ? "ruview-live-strip--active" : ""}`}>
        <div>
          <span>LIVE RF POSITION</span>
          <strong>{livePoint ? `${livePoint.x}, ${livePoint.y} cm` : "no point"}</strong>
        </div>
        <div>
          <span>Confidence</span>
          <strong>{livePoint ? `${livePoint.confidence}%` : "n/a"}</strong>
        </div>
        <div>
          <span>Active anchors</span>
          <strong>{livePoint?.nodes ?? "n/a"}</strong>
        </div>
        <div>
          <span>Stream</span>
          <strong>
            {activeNodes.length} nodes, {activePairwiseLinks.length} RF links / {formatHz(totalRate + totalLinkRate || null)}
          </strong>
        </div>
        <div>
          <span>Official RuView</span>
          <strong>{upstream?.reachable ? `${upstreamPersons ?? "n/a"} pose / ${readMetric(upstream.stream_status, "source")}` : "offline"}</strong>
        </div>
      </div>

      <div className="ruview-metrics">
        <div>
          <span>Total packets</span>
          <strong>{formatPacketCount(status?.packet_count)}</strong>
        </div>
        <div>
          <span>CSI packets</span>
          <strong>{formatPacketCount(status?.csi_packet_count)}</strong>
        </div>
        <div>
          <span>Active nodes</span>
          <strong>
            {activeNodes.length}/{nodes.length || 1}
          </strong>
        </div>
        <div>
          <span>Active RF health</span>
          <strong>
            {healthyRfNodes.length}/{rfHealth.length || 1}
          </strong>
        </div>
        <div>
          <span>Pairwise links</span>
          <strong>
            {activePairwiseLinks.length}/{expectedDirections}
          </strong>
        </div>
        <div>
          <span>RF coverage</span>
          <strong>{coveragePercent}%</strong>
        </div>
        <div>
          <span>Avg link quality</span>
          <strong>{formatQuality(averageQuality)}</strong>
        </div>
        <div>
          <span>CSI rate</span>
          <strong>{formatHz(totalRate + totalLinkRate || null)}</strong>
        </div>
        <div>
          <span>Stimulus</span>
          <strong>{formatPacketCount(status?.stimulus_count)}</strong>
        </div>
        <div>
          <span>Last packet</span>
          <strong>{status?.last_packet_at ? new Date(status.last_packet_at).toLocaleTimeString() : "n/a"}</strong>
        </div>
        <div>
          <span>Calibration samples</span>
          <strong>{calibration?.total_samples ?? 0}</strong>
        </div>
        <div>
          <span>Zone estimate</span>
          <strong>
            {estimate?.ready && estimate.estimated_x_cm != null && estimate.estimated_y_cm != null
              ? `${Math.round(estimate.estimated_x_cm)}, ${Math.round(estimate.estimated_y_cm)} (${Math.round(estimate.confidence * 100)}%)`
              : "n/a"}
          </strong>
        </div>
        <div>
          <span>RuView API fps</span>
          <strong>{readMetric(upstream?.stream_status, "fps")}</strong>
        </div>
        <div>
          <span>RuView detections</span>
          <strong>{readMetric(upstream?.pose_stats, "total_detections")}</strong>
        </div>
      </div>

      {estimate?.message && <div className="summary-card__hint">{estimate.message}</div>}
      {upstream?.base_url && (
        <div className="summary-card__hint">
          Official RuView sidecar: {upstream.base_url}. UI: http://127.0.0.1:3100/ui/index.html
        </div>
      )}
      {upstream?.error && <div className="rf-node-card__error">{upstream.error}</div>}

      {status?.last_error && <div className="rf-node-card__error">{status.last_error}</div>}
      {status?.last_stimulus_error && <div className="rf-node-card__error">{status.last_stimulus_error}</div>}

      <div className="rf-link-matrix">
        <div className="rf-editor-block__title">
          <span>Live ESP-NOW link matrix</span>
          <span className="rf-room-scale">{activeUnknownLinks.length} AP/unknown samples filtered from tracking</span>
        </div>
        <div className="rf-editor-scroll">
          <table className="soft-table rf-link-matrix__table">
            <thead>
              <tr>
                <th>RX \ TX</th>
                {matrixNodeIds.map((nodeId) => (
                  <th key={`tx-${nodeId}`}>#{nodeId}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {matrixNodeIds.map((rxNodeId) => (
                <tr key={`rx-${rxNodeId}`}>
                  <th>#{rxNodeId}</th>
                  {matrixNodeIds.map((txNodeId) => {
                    if (rxNodeId === txNodeId) {
                      return (
                        <td key={`${rxNodeId}-${txNodeId}`} className="rf-link-cell rf-link-cell--self">
                          self
                        </td>
                      );
                    }
                    const link = linkByDirection.get(`${rxNodeId}-${txNodeId}`);
                    return (
                      <td
                        key={`${rxNodeId}-${txNodeId}`}
                        className={`rf-link-cell rf-link-cell--${linkQualityTone(link?.quality_score)}`}
                        title={
                          link
                            ? `RSSI ${link.rssi ?? "n/a"} dBm, rate ${formatHz(link.packet_rate_hz)}, age ${formatAgeMs(link.link_age_ms)}`
                            : "No live pairwise CSI in the current window"
                        }
                      >
                        {link ? (
                          <>
                            <strong>{formatQuality(link.quality_score)}</strong>
                            <span>{formatHz(link.packet_rate_hz)}</span>
                          </>
                        ) : (
                          <span>--</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
              {matrixNodeIds.length === 0 && (
                <tr>
                  <td>No RF nodes yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="rf-editor-scroll">
        <table className="soft-table">
          <thead>
            <tr>
              <th>Node</th>
              <th>Source</th>
              <th>Packets</th>
              <th>RSSI</th>
              <th>Power</th>
              <th>Rate</th>
              <th>CSI shape</th>
              <th>Seq</th>
            </tr>
          </thead>
          <tbody>
            {nodes.map((node) => (
              <tr key={node.node_id}>
                <td>
                  #{node.physical_label ?? node.node_id}
                  {node.raw_node_id != null && node.raw_node_id !== node.node_id ? ` (raw ${node.raw_node_id})` : ""}
                </td>
                <td>
                  {node.source_ip}:{node.source_port}
                </td>
                <td>{formatPacketCount(node.packet_count)}</td>
                <td>{node.rssi == null ? "n/a" : `${node.rssi} dBm`}</td>
                <td>{node.mean_power == null ? "n/a" : Math.round(node.mean_power)}</td>
                <td>{formatHz(node.packet_rate_hz)}</td>
                <td>
                  {node.frequency_mhz ?? "n/a"} MHz / {node.subcarriers ?? "n/a"} subc.
                </td>
                <td>{node.last_sequence ?? "n/a"}</td>
              </tr>
            ))}
            {nodes.length === 0 && (
              <tr>
                <td colSpan={8}>No RuView CSI packets received yet. Check ESP32 power, Wi-Fi and UDP port 5005.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="summary-card__hint">
        Live position is updated from the rolling CSI window. Current UI polling is 2 Hz; the backend stimulator interval is{" "}
        {status?.stimulator_interval_seconds ? `${Math.round(status.stimulator_interval_seconds * 1000)} ms` : "n/a"}.
      </div>

      <div className="rf-editor-scroll">
        <table className="soft-table">
          <thead>
            <tr>
              <th>RF link</th>
              <th>Quality</th>
              <th>Packets</th>
              <th>RSSI</th>
              <th>Power</th>
              <th>Rate</th>
              <th>Channel</th>
              <th>Mode</th>
              <th>Seq</th>
            </tr>
          </thead>
          <tbody>
            {activePairwiseLinks
              .slice()
              .sort((a, b) => (b.quality_score ?? 0) - (a.quality_score ?? 0))
              .slice(0, 40)
              .map((link) => (
              <tr key={`${link.rx_node_id}-${link.tx_node_id}`}>
                <td>
                  RX #{nodeLabelFromLink(link, "rx")} {" <- "} TX {nodeLabelFromLink(link, "tx")}
                </td>
                <td>
                  <span className={`rf-status rf-status--${linkQualityTone(link.quality_score)}`}>
                    {formatQuality(link.quality_score)}
                  </span>
                </td>
                <td>{formatPacketCount(link.packet_count)}</td>
                <td>{link.rssi == null ? "n/a" : `${link.rssi} dBm`}</td>
                <td>{link.mean_power == null ? "n/a" : Math.round(link.mean_power)}</td>
                <td>{formatHz(link.packet_rate_hz)}</td>
                <td>{link.channel ?? "n/a"}</td>
                <td>{link.inferred ? "ESP-NOW inferred" : "ESP-NOW"}</td>
                <td>{link.last_sequence ?? "n/a"}</td>
              </tr>
            ))}
            {activePairwiseLinks.length === 0 && (
              <tr>
                <td colSpan={9}>No pairwise RF links yet. Flash the new CCTV RF CSI firmware and provision peer MACs.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ActiveTrackingPanel({ snapshot }: { snapshot: ActiveTrackingSnapshot | null }) {
  const tracks = snapshot?.tracks ?? [];
  return (
    <section className="rf-room-card active-tracking-panel">
      <div className="rf-room-card__header">
        <div>
          <div className="summary-card__label">Hybrid Active Tracking</div>
          <div className="summary-card__hint">Camera identity and pose, with RuView handoff after camera detection</div>
        </div>
        <div className="page-actions">
          <span className="rf-room-scale">{snapshot?.active_count ?? 0} active</span>
          <span className="rf-room-scale">{snapshot?.rf_count ?? 0} RF live</span>
        </div>
      </div>

      <div className="rf-editor-scroll">
        <table className="soft-table">
          <thead>
            <tr>
              <th>Person / track</th>
              <th>Status</th>
              <th>Camera</th>
              <th>Room position</th>
              <th>Confidence</th>
              <th>Last seen</th>
            </tr>
          </thead>
          <tbody>
            {tracks.map((track) => (
              <tr key={track.track_key}>
                <td>{trackDisplayName(track)}</td>
                <td>
                  <span className={`tracking-status tracking-status--${track.status}`}>{track.status}</span>
                </td>
                <td>
                  cam {track.camera_id ?? "n/a"} / track {track.processor_track_id ?? "n/a"}
                </td>
                <td>
                  {track.estimated_x_cm != null && track.estimated_y_cm != null
                    ? `${Math.round(track.estimated_x_cm)}, ${Math.round(track.estimated_y_cm)}`
                    : "camera only"}
                </td>
                <td>
                  {track.status === "rf"
                    ? `${Math.round((track.rf_confidence ?? 0) * 100)}% RF`
                    : track.confidence == null
                      ? "n/a"
                      : `${Math.round(track.confidence)}% face`}
                </td>
                <td>{new Date(track.last_seen_at).toLocaleTimeString()}</td>
              </tr>
            ))}
            {tracks.length === 0 && (
              <tr>
                <td colSpan={6}>No live camera or RuView track yet. Check Processor, RF nodes, and empty-room baseline.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {snapshot?.rf_message && <div className="summary-card__hint">{snapshot.rf_message}</div>}
    </section>
  );
}

const RfRoomPage: React.FC = () => {
  const { token } = useAuth();
  const [snapshot, setSnapshot] = useState<RfRoomSnapshot | null>(null);
  const [layoutDraft, setLayoutDraft] = useState<RfRoomLayout | null>(null);
  const [baseline, setBaseline] = useState<RfBaselineSummary | null>(null);
  const [ruviewStatus, setRuviewStatus] = useState<RuViewBridgeStatus | null>(null);
  const [ruviewUpstream, setRuviewUpstream] = useState<RuViewUpstreamStatus | null>(null);
  const [ruviewCalibration, setRuviewCalibration] = useState<RuViewCalibrationHistory | null>(null);
  const [ruviewEstimate, setRuviewEstimate] = useState<RuViewZoneEstimate | null>(null);
  const [activeTracking, setActiveTracking] = useState<ActiveTrackingSnapshot | null>(null);
  const [lastSample, setLastSample] = useState<RfSnapshotSample | null>(null);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [collecting, setCollecting] = useState(false);
  const [batchCollecting, setBatchCollecting] = useState(false);
  const [savingLayout, setSavingLayout] = useState(false);
  const [layoutDirty, setLayoutDirty] = useState(false);
  const [liveRuView, setLiveRuView] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadBaseline = useCallback(async () => {
    if (!token) return;
    setBaseline(await getRfBaseline(token, 200));
  }, [token]);

  const loadRuView = useCallback(async () => {
    if (!token) return;
    const [status, upstream, history, estimate, tracking] = await Promise.all([
      getRuViewStatus(token),
      getRuViewUpstream(token),
      getRuViewCalibration(token, 50),
      getRuViewEstimate(token, 200),
      getActiveTracking(token, 200),
    ]);
    setRuviewStatus(status);
    setRuviewUpstream(upstream);
    setRuviewCalibration(history);
    setRuviewEstimate(estimate);
    setActiveTracking(tracking);
  }, [token]);

  const loadRuViewLive = useCallback(async () => {
    if (!token) return;
    const [status, estimate, tracking] = await Promise.all([
      getRuViewStatus(token),
      getRuViewEstimate(token, 200),
      getActiveTracking(token, 200),
    ]);
    setRuviewStatus(status);
    setRuviewEstimate(estimate);
    setActiveTracking(tracking);
  }, [token]);

  const load = useCallback(
    async (includeScan = false) => {
      if (!token) return;
      if (includeScan) setScanning(true);
      setLoading(true);
      setError(null);
      try {
        setSnapshot(await getRfSnapshot(token, includeScan));
        await loadBaseline();
        await loadRuView();
      } catch (event: any) {
        setError(event?.message || "Failed to load RF room");
      } finally {
        setLoading(false);
        setScanning(false);
      }
    },
    [loadBaseline, loadRuView, token]
  );

  useEffect(() => {
    if (snapshot && !layoutDirty) {
      setLayoutDraft(cloneLayout(snapshot.layout));
    }
  }, [layoutDirty, snapshot]);

  const changeLayoutDraft = useCallback((nextLayout: RfRoomLayout) => {
    setLayoutDraft(nextLayout);
    setLayoutDirty(true);
  }, []);

  const resetLayoutDraft = useCallback(() => {
    if (!snapshot) return;
    setLayoutDraft(cloneLayout(snapshot.layout));
    setLayoutDirty(false);
  }, [snapshot]);

  const saveLayoutDraft = useCallback(async () => {
    if (!token || !layoutDraft) return;
    setSavingLayout(true);
    setError(null);
    try {
      const savedLayout = await updateRfRoom(token, layoutDraft);
      setLayoutDraft(cloneLayout(savedLayout));
      setLayoutDirty(false);
      setSnapshot((current) =>
        current
          ? {
              ...current,
              layout: savedLayout,
              nodes: current.nodes.map((node) => ({
                ...node,
                config: savedLayout.nodes.find((config) => config.node_id === node.config.node_id) ?? node.config,
              })),
            }
          : current
      );
      await load(false);
    } catch (event: any) {
      setError(event?.message || "Failed to save RF room layout");
    } finally {
      setSavingLayout(false);
    }
  }, [layoutDraft, load, token]);

  const collectSample = useCallback(
    async (includeScan = false) => {
      if (!token) return;
      setCollecting(true);
      setError(null);
      try {
        const sample = await collectRfHistorySample(token, includeScan);
        setLastSample(sample);
        await loadBaseline();
      } catch (event: any) {
        setError(event?.message || "Failed to collect RF sample");
      } finally {
        setCollecting(false);
      }
    },
    [loadBaseline, token]
  );

  const collectOneMinuteBaseline = useCallback(async () => {
    if (!token) return;
    setBatchCollecting(true);
    setError(null);
    try {
      setBaseline(await collectRfHistoryBatch(token, { count: 12, intervalSeconds: 5 }));
      await load(false);
    } catch (event: any) {
      setError(event?.message || "Failed to collect RF baseline batch");
    } finally {
      setBatchCollecting(false);
    }
  }, [load, token]);

  const startBridge = useCallback(async () => {
    if (!token) return;
    setError(null);
    try {
      setRuviewStatus(await startRuViewBridge(token));
    } catch (event: any) {
      setError(event?.message || "Failed to start RuView bridge");
    }
  }, [token]);

  useEffect(() => {
    load(false);
  }, [load]);

  useEffect(() => {
    const timer = window.setInterval(() => load(false), 7000);
    return () => window.clearInterval(timer);
  }, [load]);

  useEffect(() => {
    if (!token || !liveRuView) return;
    let disposed = false;
    let inFlight = false;
    const tick = async () => {
      if (disposed || inFlight) return;
      inFlight = true;
      try {
        await loadRuViewLive();
      } catch {
        // Keep the last known live point visible; the full refresh path reports persistent failures.
      } finally {
        inFlight = false;
      }
    };
    tick();
    const timer = window.setInterval(tick, 900);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [liveRuView, loadRuViewLive, token]);

  const toggleRuViewLive = useCallback(() => {
    setLiveRuView((current) => !current);
  }, []);

  const stats = useMemo(() => {
    const nodes = snapshot?.nodes ?? [];
    const rssiValues = nodes.map(nodeRssi).filter((value): value is number => typeof value === "number");
    const avgRssi = rssiValues.length ? Math.round(rssiValues.reduce((sum, value) => sum + value, 0) / rssiValues.length) : null;
    return {
      total: nodes.length,
      online: snapshot?.online_count ?? 0,
      avgRssi,
      scans: nodes.filter((node) => node.scan).length,
    };
  }, [snapshot]);

  return (
    <div className="stack rf-room-page">
      <section className="page-hero">
        <div className="page-hero__content">
          <div className="page-hero__eyebrow">RF diagnostics</div>
          <h2 className="title">RF Room</h2>
          <div className="summary-card__hint">
            Layout is loaded from JSON, so the diploma room can use different dimensions and heights.
          </div>
        </div>
        <div className="page-actions">
          <button className="btn secondary" type="button" onClick={() => load(false)} disabled={loading || scanning}>
            Refresh
          </button>
          <button className="btn secondary" type="button" onClick={() => collectSample(false)} disabled={loading || scanning || collecting}>
            {collecting ? "Saving..." : "Save sample"}
          </button>
          <button
            className="btn secondary"
            type="button"
            onClick={collectOneMinuteBaseline}
            disabled={loading || scanning || collecting || batchCollecting}
          >
            {batchCollecting ? "Collecting 1 min..." : "Collect 1 min"}
          </button>
          <button className="btn" type="button" onClick={() => load(true)} disabled={loading || scanning}>
            {scanning ? "Scanning..." : "Run scan"}
          </button>
        </div>
      </section>

      {error && <div className="form-error">{error}</div>}

      <div className="summary-grid">
        <div className="summary-card">
          <div className="summary-card__label">Nodes online</div>
          <div className="summary-card__value">
            {stats.online}/{stats.total || 6}
          </div>
          <div className="summary-card__hint">ESP32-S3 anchors in current room layout</div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">Average RSSI</div>
          <div className="summary-card__value">{stats.avgRssi == null ? "n/a" : `${stats.avgRssi} dBm`}</div>
          <div className="summary-card__hint">Signal to the CCTV-STAND router</div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">Room size</div>
          <div className="summary-card__value" style={{ fontSize: 28 }}>
            {snapshot ? `${snapshot.layout.room.width_cm} x ${snapshot.layout.room.depth_cm}` : "n/a"}
          </div>
          <div className="summary-card__hint">centimeters, height {formatCm(snapshot?.layout.room.height_cm)}</div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">Last update</div>
          <div className="summary-card__value" style={{ fontSize: 24 }}>
            {snapshot ? new Date(snapshot.generated_at).toLocaleTimeString() : "n/a"}
          </div>
          <div className="summary-card__hint">{stats.scans ? `${stats.scans} nodes include scan data` : "health-only polling"}</div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">Baseline samples</div>
          <div className="summary-card__value">{baseline?.sample_count ?? 0}</div>
          <div className="summary-card__hint">
            {lastSample ? `last saved ${new Date(lastSample.generated_at).toLocaleTimeString()}` : "stored in data/rf_samples.jsonl"}
          </div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">RuView CSI</div>
          <div className="summary-card__value">{formatPacketCount(ruviewStatus?.csi_packet_count)}</div>
          <div className="summary-card__hint">
            {ruviewStatus?.last_packet_at
                ? `last packet ${new Date(ruviewStatus.last_packet_at).toLocaleTimeString()}`
                : "waiting on UDP 5005"}
          </div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">RuView upstream</div>
          <div className="summary-card__value">{ruviewUpstream?.reachable ? "online" : "offline"}</div>
          <div className="summary-card__hint">
            {ruviewUpstream?.reachable
              ? `${readMetric(ruviewUpstream.stream_status, "source")} / ${readMetric(ruviewUpstream.stream_status, "fps")} fps`
              : "sidecar on 3100 is not reachable"}
          </div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">Active tracks</div>
          <div className="summary-card__value">{activeTracking?.active_count ?? 0}</div>
          <div className="summary-card__hint">
            {activeTracking?.rf_count ? `${activeTracking.rf_count} continued by RuView` : "camera identity handoff layer"}
          </div>
        </div>
      </div>

      {loading && !snapshot && <div className="summary-card">Loading RF room...</div>}

      {snapshot && (
        <>
          <RfRoomMap snapshot={snapshot} layout={layoutDraft} estimate={ruviewEstimate} activeTracking={activeTracking} />
          <RfRoomScene3D snapshot={snapshot} layout={layoutDraft} estimate={ruviewEstimate} activeTracking={activeTracking} />
          <ScannerView layout={layoutDraft ?? snapshot.layout} estimate={ruviewEstimate} activeTracking={activeTracking} />
          <RuViewBridgePanel
            status={ruviewStatus}
            upstream={ruviewUpstream}
            calibration={ruviewCalibration}
            estimate={ruviewEstimate}
            liveEnabled={liveRuView}
            onStart={startBridge}
            onToggleLive={toggleRuViewLive}
          />
          <ActiveTrackingPanel snapshot={activeTracking} />
          <CameraRoomCalibrationPanel token={token} cameraId={1} layout={layoutDraft ?? snapshot.layout} onError={setError} />
          <RfLayoutEditor
            layout={layoutDraft}
            dirty={layoutDirty}
            saving={savingLayout}
            onChange={changeLayoutDraft}
            onReset={resetLayoutDraft}
            onSave={saveLayoutDraft}
          />
          <section className="rf-node-grid">
            {snapshot.nodes.map((node) => (
              <RfNodeCard key={node.config.node_id} node={node} />
            ))}
          </section>
          {baseline && baseline.nodes.length > 0 && (
            <section className="rf-room-card">
              <div className="rf-room-card__header">
                <div>
                  <div className="summary-card__label">Baseline RSSI</div>
                  <div className="summary-card__hint">
                    {baseline.sample_count} saved snapshots, last summary {new Date(baseline.generated_at).toLocaleTimeString()}
                  </div>
                </div>
              </div>
              <div style={{ overflowX: "auto", marginTop: 12 }}>
                <table className="soft-table">
                  <thead>
                    <tr>
                      <th>Node</th>
                      <th>Position</th>
                      <th>Samples</th>
                      <th>Avg RSSI</th>
                      <th>Min/Max</th>
                      <th>Last</th>
                    </tr>
                  </thead>
                  <tbody>
                    {baseline.nodes.map((node) => (
                      <tr key={node.node_id}>
                        <td>
                          #{node.physical_label} {node.node_id}
                        </td>
                        <td>{node.position_label}</td>
                        <td>
                          {node.online_samples}/{node.samples}
                        </td>
                        <td>{node.avg_rssi == null ? "n/a" : `${node.avg_rssi} dBm`}</td>
                        <td>
                          {node.min_rssi == null || node.max_rssi == null ? "n/a" : `${node.min_rssi}/${node.max_rssi} dBm`}
                        </td>
                        <td>{node.last_rssi == null ? "n/a" : `${node.last_rssi} dBm`}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
};

export default RfRoomPage;
