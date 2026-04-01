import { useEffect, useMemo, useRef, useState } from "react";
import type { DragEvent, PointerEvent, WheelEvent } from "react";
import { useAuth } from "../context/AuthContext";
import {
  API_URL,
  createCameraPreset,
  deleteCameraPreset,
  getAdminCamera,
  getCameras,
  gotoCameraPreset,
  listGroups,
  ptzContinuous,
  ptzHome,
  ptzStop,
  refreshCameraPresets,
  refreshOnvifCamera,
  type CameraDetail,
  type CameraPtzCapabilities,
  type CameraSummary,
  type GroupOut,
} from "../lib/api";
import { loadUiSettings } from "../lib/uiSettings";

type LiveGridMode = "auto" | "1x1" | "2x2" | "3x3";
type FixedGridMode = Exclude<LiveGridMode, "auto">;

const GRID_MODE_LABELS: Record<LiveGridMode, string> = {
  auto: "Авто",
  "1x1": "1 x 1",
  "2x2": "2 x 2",
  "3x3": "3 x 3",
};

const GRID_MODE_CAPACITY: Record<Exclude<LiveGridMode, "auto">, number> = {
  "1x1": 1,
  "2x2": 4,
  "3x3": 9,
};

const GRID_STORAGE_KEY = "cctv_live_grid_mode";
const ORDER_STORAGE_KEY = "cctv_live_camera_order";
const GRID_LAYOUT_STORAGE_KEY = "cctv_live_grid_layouts";

type ZoomState = {
  scale: number;
  originX: number;
  originY: number;
};

type LiveGridLayouts = Partial<Record<FixedGridMode, Array<number | null>>>;
type LiveGridItem =
  | { slotIndex: number; camera: CameraSummary }
  | { slotIndex: number; placeholderId: string };
type PtzMovePayload = { pan?: number; tilt?: number; zoom?: number; timeout_seconds?: number };

const DEFAULT_ZOOM: ZoomState = {
  scale: 1,
  originX: 50,
  originY: 50,
};

function readGridMode(): LiveGridMode {
  const stored = typeof window !== "undefined" ? localStorage.getItem(GRID_STORAGE_KEY) : null;
  return stored === "1x1" || stored === "2x2" || stored === "3x3" ? stored : "auto";
}

function readCameraOrder(): number[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(ORDER_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.map((value) => Number(value)).filter((value) => Number.isInteger(value)) : [];
  } catch {
    return [];
  }
}

function saveCameraOrder(order: number[]) {
  localStorage.setItem(ORDER_STORAGE_KEY, JSON.stringify(order));
}

function readGridLayouts(): LiveGridLayouts {
  if (typeof window === "undefined") return {};
  try {
    const raw = localStorage.getItem(GRID_LAYOUT_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    if (!parsed || typeof parsed !== "object") return {};
    const next: LiveGridLayouts = {};
    for (const mode of Object.keys(GRID_MODE_CAPACITY) as FixedGridMode[]) {
      const layout = parsed[mode];
      if (Array.isArray(layout)) {
        next[mode] = layout.map((value) => (Number.isInteger(value) ? Number(value) : null));
      }
    }
    return next;
  } catch {
    return {};
  }
}

function saveGridLayouts(layouts: LiveGridLayouts) {
  localStorage.setItem(GRID_LAYOUT_STORAGE_KEY, JSON.stringify(layouts));
}

function mergeOrder(cameras: CameraSummary[], savedOrder: number[]): CameraSummary[] {
  const byId = new Map(cameras.map((camera) => [camera.camera_id, camera]));
  const ordered: CameraSummary[] = [];
  for (const cameraId of savedOrder) {
    const camera = byId.get(cameraId);
    if (camera) {
      ordered.push(camera);
      byId.delete(cameraId);
    }
  }
  const tail = Array.from(byId.values()).sort((left, right) => left.name.localeCompare(right.name, "ru"));
  return ordered.concat(tail);
}

function reorder<T>(items: T[], fromIndex: number, toIndex: number): T[] {
  if (fromIndex === toIndex || fromIndex < 0 || toIndex < 0) return items;
  const next = items.slice();
  const [moved] = next.splice(fromIndex, 1);
  if (moved === undefined) return items;
  next.splice(toIndex, 0, moved);
  return next;
}

function resolveGridLayout(cameras: CameraSummary[], mode: FixedGridMode, savedLayout?: Array<number | null>) {
  const capacity = GRID_MODE_CAPACITY[mode];
  const byId = new Map(cameras.map((camera) => [camera.camera_id, camera]));
  const used = new Set<number>();
  const layout = Array.from({ length: capacity }, (_, index) => {
    const candidate = savedLayout?.[index];
    if (Number.isInteger(candidate) && byId.has(Number(candidate)) && !used.has(Number(candidate))) {
      const normalized = Number(candidate);
      used.add(normalized);
      return normalized;
    }
    return null;
  });

  for (const camera of cameras) {
    if (used.has(camera.camera_id)) continue;
    const emptyIndex = layout.indexOf(null);
    if (emptyIndex === -1) break;
    layout[emptyIndex] = camera.camera_id;
    used.add(camera.camera_id);
  }

  return layout;
}

function getCameraPtzCapabilities(detail: CameraDetail | null): CameraPtzCapabilities {
  return (
    detail?.ptz_capabilities ?? {
      pan_tilt: Boolean(detail?.supports_ptz),
      zoom: false,
      home: false,
      presets: Boolean(detail?.presets?.length),
    }
  );
}

const LivePage: React.FC = () => {
  const { token, user } = useAuth();
  const [cameras, setCameras] = useState<CameraSummary[]>([]);
  const [groups, setGroups] = useState<GroupOut[]>([]);
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null);
  const [gridMode, setGridMode] = useState<LiveGridMode>(() => readGridMode());
  const [gridLayouts, setGridLayouts] = useState<LiveGridLayouts>(() => readGridLayouts());
  const [draggedCameraId, setDraggedCameraId] = useState<number | null>(null);
  const [draggedSlotIndex, setDraggedSlotIndex] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [streamErrorMap, setStreamErrorMap] = useState<Record<number, boolean>>({});
  const [streamRetryMap, setStreamRetryMap] = useState<Record<number, number>>({});
  const [fullscreenCameraId, setFullscreenCameraId] = useState<number | null>(null);
  const [fullscreenDetail, setFullscreenDetail] = useState<CameraDetail | null>(null);
  const [fullscreenBusy, setFullscreenBusy] = useState(false);
  const [fullscreenError, setFullscreenError] = useState<string | null>(null);
  const [presetName, setPresetName] = useState("");
  const [zoomState, setZoomState] = useState<ZoomState>(DEFAULT_ZOOM);
  const containerRefs = useRef<Record<number, HTMLElement | null>>({});
  const activePtzMoveRef = useRef<string | null>(null);
  const uiSettings = loadUiSettings();
  const isAdmin = user?.role_id === 1;

  const densityStyle =
    uiSettings.liveDensity === "focus"
      ? { min: 420, max: 540, label: "Крупно" }
      : uiSettings.liveDensity === "comfortable"
        ? { min: 320, max: 430, label: "Стандартно" }
        : { min: 260, max: 340, label: "Компактно" };

  useEffect(() => {
    localStorage.setItem(GRID_STORAGE_KEY, gridMode);
  }, [gridMode]);

  useEffect(() => {
    saveGridLayouts(gridLayouts);
  }, [gridLayouts]);

  useEffect(() => {
    if (!token) return;
    Promise.all([getCameras(token), listGroups(token)])
      .then(([cameraItems, groupItems]) => {
        setCameras(mergeOrder(cameraItems, readCameraOrder()));
        setGroups(groupItems);
      })
      .catch((event) => setError(event?.message || "Не удалось загрузить камеры"));
  }, [token]);

  useEffect(() => {
    const handleFullscreenChange = () => {
      const element = document.fullscreenElement as HTMLElement | null;
      const nextCameraId = element?.dataset.cameraId ? Number(element.dataset.cameraId) : null;
      setFullscreenCameraId(Number.isFinite(nextCameraId) ? nextCameraId : null);
      if (!nextCameraId) {
        setFullscreenDetail(null);
        setFullscreenError(null);
        setPresetName("");
        setZoomState(DEFAULT_ZOOM);
      }
    };
    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", handleFullscreenChange);
  }, []);

  useEffect(() => {
    if (!token || !fullscreenCameraId || !isAdmin) {
      if (!isAdmin) {
        setFullscreenDetail(null);
        setFullscreenError(null);
      }
      return;
    }
    let cancelled = false;
    setFullscreenBusy(true);
    setFullscreenError(null);
    getAdminCamera(token, fullscreenCameraId)
      .then((detail) => {
        if (!cancelled) {
          setFullscreenDetail(detail);
        }
      })
      .catch((event: any) => {
        if (!cancelled) {
          setFullscreenError(event?.message || "Не удалось загрузить параметры ONVIF");
          setFullscreenDetail(null);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setFullscreenBusy(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [fullscreenCameraId, isAdmin, token]);

  const filteredCameras = useMemo(
    () => (selectedGroupId ? cameras.filter((camera) => camera.group_id === selectedGroupId) : cameras),
    [cameras, selectedGroupId]
  );

  const selectedGroupName = useMemo(
    () => groups.find((group) => group.group_id === selectedGroupId)?.name || "Все группы",
    [groups, selectedGroupId]
  );

  const gridStyle = useMemo(() => {
    if (gridMode === "1x1") return { gridTemplateColumns: "repeat(1, minmax(0, 1fr))" };
    if (gridMode === "2x2") return { gridTemplateColumns: "repeat(2, minmax(0, 1fr))" };
    if (gridMode === "3x3") return { gridTemplateColumns: "repeat(3, minmax(0, 1fr))" };
    return {
      gridTemplateColumns: `repeat(auto-fit, minmax(${densityStyle.min}px, ${densityStyle.max}px))`,
    };
  }, [densityStyle.max, densityStyle.min, gridMode]);

  const filteredCameraMap = useMemo(
    () => new Map(filteredCameras.map((camera) => [camera.camera_id, camera])),
    [filteredCameras]
  );

  const fixedGridLayout = useMemo(() => {
    if (gridMode === "auto") return null;
    return resolveGridLayout(filteredCameras, gridMode, gridLayouts[gridMode]);
  }, [filteredCameras, gridLayouts, gridMode]);

  const gridItems = useMemo<LiveGridItem[]>(() => {
    if (gridMode === "auto") {
      return filteredCameras.map((camera, slotIndex) => ({ slotIndex, camera }));
    }
    return (fixedGridLayout ?? []).map((cameraId, slotIndex) => {
      const camera = cameraId ? filteredCameraMap.get(cameraId) : null;
      return camera
        ? { slotIndex, camera }
        : { slotIndex, placeholderId: `${gridMode}-${slotIndex}` };
    });
  }, [filteredCameraMap, filteredCameras, fixedGridLayout, gridMode]);

  const activeCamera = useMemo(
    () => cameras.find((camera) => camera.camera_id === fullscreenCameraId) ?? null,
    [cameras, fullscreenCameraId]
  );

  const ptzCapabilities = getCameraPtzCapabilities(fullscreenDetail);
  const showPtzPanel = Boolean(
    fullscreenCameraId &&
      document.fullscreenElement &&
      activeCamera?.onvif_enabled &&
      isAdmin &&
      fullscreenDetail
  );

  const persistOrder = (next: CameraSummary[]) => {
    setCameras(next);
    saveCameraOrder(next.map((camera) => camera.camera_id));
  };

  const handleAutoDrop = (targetCameraId: number) => {
    if (draggedCameraId === null || draggedCameraId === targetCameraId) {
      setDraggedCameraId(null);
      setDraggedSlotIndex(null);
      return;
    }
    const fromIndex = cameras.findIndex((camera) => camera.camera_id === draggedCameraId);
    const toIndex = cameras.findIndex((camera) => camera.camera_id === targetCameraId);
    if (fromIndex === -1 || toIndex === -1) {
      setDraggedCameraId(null);
      setDraggedSlotIndex(null);
      return;
    }
    persistOrder(reorder(cameras, fromIndex, toIndex));
    setDraggedCameraId(null);
    setDraggedSlotIndex(null);
  };

  const handleFixedDrop = (targetSlotIndex: number) => {
    if (gridMode === "auto" || draggedCameraId === null || draggedSlotIndex === null || !fixedGridLayout) {
      setDraggedCameraId(null);
      setDraggedSlotIndex(null);
      return;
    }
    if (targetSlotIndex === draggedSlotIndex) {
      setDraggedCameraId(null);
      setDraggedSlotIndex(null);
      return;
    }

    const nextLayout = fixedGridLayout.slice();
    [nextLayout[draggedSlotIndex], nextLayout[targetSlotIndex]] = [nextLayout[targetSlotIndex], nextLayout[draggedSlotIndex]];
    setGridLayouts((prev) => ({ ...prev, [gridMode]: nextLayout }));
    setDraggedCameraId(null);
    setDraggedSlotIndex(null);
  };

  const handleDropToSlot = (targetSlotIndex: number, targetCameraId?: number) => {
    if (gridMode === "auto") {
      if (typeof targetCameraId === "number") {
        handleAutoDrop(targetCameraId);
      }
      return;
    }
    handleFixedDrop(targetSlotIndex);
  };

  const toggleFullscreen = async (cameraId: number) => {
    const node = containerRefs.current[cameraId];
    if (!node) return;
    if (document.fullscreenElement === node) {
      await document.exitFullscreen?.();
      return;
    }
    setFullscreenDetail(null);
    setFullscreenError(null);
    setPresetName("");
    setZoomState(DEFAULT_ZOOM);
    await node.requestFullscreen?.();
  };

  const resetDigitalZoom = () => setZoomState(DEFAULT_ZOOM);

  const handleDigitalZoom = (cameraId: number, event: WheelEvent<HTMLDivElement>) => {
    if (!event.ctrlKey || fullscreenCameraId !== cameraId) return;
    event.preventDefault();
    const rect = event.currentTarget.getBoundingClientRect();
    const originX = ((event.clientX - rect.left) / rect.width) * 100;
    const originY = ((event.clientY - rect.top) / rect.height) * 100;
    setZoomState((prev) => {
      const delta = event.deltaY < 0 ? 0.16 : -0.16;
      const nextScale = Number(Math.min(4, Math.max(1, prev.scale + delta)).toFixed(2));
      if (nextScale <= 1) {
        return DEFAULT_ZOOM;
      }
      return {
        scale: nextScale,
        originX,
        originY,
      };
    });
  };

  const reloadFullscreenDetail = async (cameraId: number) => {
    if (!token || !isAdmin) return;
    setFullscreenBusy(true);
    setFullscreenError(null);
    try {
      setFullscreenDetail(await getAdminCamera(token, cameraId));
    } catch (event: any) {
      setFullscreenError(event?.message || "Не удалось обновить данные камеры");
    } finally {
      setFullscreenBusy(false);
    }
  };

  const getMoveKey = (payload: PtzMovePayload) => JSON.stringify(payload);

  const sendContinuousMove = async (payload: PtzMovePayload) => {
    if (!token || !fullscreenCameraId) return;
    try {
      await ptzContinuous(token, fullscreenCameraId, payload);
    } catch (event: any) {
      setFullscreenError(event?.message || "Не удалось отправить PTZ-команду");
    }
  };

  const stopMove = async (force = false) => {
    if (!force && !activePtzMoveRef.current) return;
    activePtzMoveRef.current = null;
    if (!token || !fullscreenCameraId) return;
    try {
      await ptzStop(token, fullscreenCameraId);
    } catch (event: any) {
      setFullscreenError(event?.message || "Не удалось остановить камеру");
    }
  };

  const startHoldMove = async (payload: PtzMovePayload) => {
    const moveKey = getMoveKey(payload);
    if (activePtzMoveRef.current === moveKey) return;
    if (activePtzMoveRef.current) {
      await stopMove(true);
    }
    activePtzMoveRef.current = moveKey;
    await sendContinuousMove(payload);
  };

  const bindHoldMove = (payload: PtzMovePayload) => ({
    onPointerDown: (event: PointerEvent<HTMLButtonElement>) => {
      event.preventDefault();
      event.currentTarget.setPointerCapture?.(event.pointerId);
      void startHoldMove(payload);
    },
    onPointerUp: (event: PointerEvent<HTMLButtonElement>) => {
      if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
      }
      void stopMove();
    },
    onPointerCancel: (event: PointerEvent<HTMLButtonElement>) => {
      if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
      }
      void stopMove();
    },
    onPointerLeave: () => {
      void stopMove();
    },
  });

  const moveHome = async () => {
    if (!token || !fullscreenCameraId) return;
    try {
      await ptzHome(token, fullscreenCameraId);
    } catch (event: any) {
      setFullscreenError(event?.message || "Не удалось вернуть камеру в домашнее положение");
    }
  };

  const syncOnvifDetail = async () => {
    if (!token || !fullscreenCameraId) return;
    setFullscreenBusy(true);
    setFullscreenError(null);
    try {
      setFullscreenDetail(await refreshOnvifCamera(token, fullscreenCameraId));
    } catch (event: any) {
      setFullscreenError(event?.message || "Не удалось синхронизировать данные ONVIF");
    } finally {
      setFullscreenBusy(false);
    }
  };

  const syncPresets = async () => {
    if (!token || !fullscreenCameraId) return;
    setFullscreenBusy(true);
    setFullscreenError(null);
    try {
      await refreshCameraPresets(token, fullscreenCameraId);
      await reloadFullscreenDetail(fullscreenCameraId);
    } catch (event: any) {
      setFullscreenError(event?.message || "Не удалось обновить пресеты");
    } finally {
      setFullscreenBusy(false);
    }
  };

  const createPreset = async () => {
    if (!token || !fullscreenCameraId || !presetName.trim()) return;
    setFullscreenBusy(true);
    setFullscreenError(null);
    try {
      await createCameraPreset(token, fullscreenCameraId, { name: presetName.trim() });
      setPresetName("");
      await reloadFullscreenDetail(fullscreenCameraId);
    } catch (event: any) {
      setFullscreenError(event?.message || "Не удалось создать точку патруля");
    } finally {
      setFullscreenBusy(false);
    }
  };

  const removePreset = async (presetId: number) => {
    if (!token || !fullscreenCameraId) return;
    setFullscreenBusy(true);
    setFullscreenError(null);
    try {
      await deleteCameraPreset(token, fullscreenCameraId, presetId);
      await reloadFullscreenDetail(fullscreenCameraId);
    } catch (event: any) {
      setFullscreenError(event?.message || "Не удалось удалить точку патруля");
    } finally {
      setFullscreenBusy(false);
    }
  };

  const gotoPreset = async (presetId: number) => {
    if (!token || !fullscreenCameraId) return;
    try {
      await gotoCameraPreset(token, fullscreenCameraId, presetId);
    } catch (event: any) {
      setFullscreenError(event?.message || "Не удалось перейти к точке патруля");
    }
  };

  useEffect(() => {
    if (!showPtzPanel) return;

    const handlePointerRelease = () => {
      void stopMove();
    };

    window.addEventListener("pointerup", handlePointerRelease);
    window.addEventListener("pointercancel", handlePointerRelease);
    window.addEventListener("blur", handlePointerRelease);

    return () => {
      window.removeEventListener("pointerup", handlePointerRelease);
      window.removeEventListener("pointercancel", handlePointerRelease);
      window.removeEventListener("blur", handlePointerRelease);
      void stopMove(true);
    };
  }, [showPtzPanel]);

  return (
    <div className="stack">
      <section className="toolbar-card">
        <div className="stack live-toolbar-meta" style={{ gap: 4 }}>
          <h2 className="title">Live</h2>
          <div className="muted">
            {selectedGroupName} · {filteredCameras.length} камер · {densityStyle.label}
          </div>
        </div>

        <div className="page-actions live-toolbar-actions">
          <div className="live-grid-presets" role="group" aria-label="Сетка камер">
            {(Object.keys(GRID_MODE_LABELS) as LiveGridMode[]).map((mode) => (
              <button
                key={mode}
                type="button"
                className={gridMode === mode ? "btn" : "btn secondary"}
                onClick={() => setGridMode(mode)}
              >
                {GRID_MODE_LABELS[mode]}
              </button>
            ))}
          </div>

          {groups.length > 0 && (
            <label className="field live-group-filter">
              <span className="label">Группа камер</span>
              <select
                className="input"
                value={selectedGroupId ?? ""}
                onChange={(event) => setSelectedGroupId(event.target.value ? Number(event.target.value) : null)}
              >
                <option value="">Все камеры</option>
                {groups.map((group) => (
                  <option key={group.group_id} value={group.group_id}>
                    {group.name}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      </section>

      {error && <div className="danger">{error}</div>}

      <section className="live-grid live-grid--cards" style={gridStyle}>
        {gridItems.map((item) => {
          if ("placeholderId" in item) {
            return (
              <div
                key={item.placeholderId}
                className="live-stream-card live-stream-card--placeholder"
                onDragOver={(event: DragEvent<HTMLElement>) => event.preventDefault()}
                onDrop={() => handleDropToSlot(item.slotIndex)}
              >
                <div className="live-placeholder">+</div>
              </div>
            );
          }

          const { camera, slotIndex } = item;
          const isFullscreenCamera = fullscreenCameraId === camera.camera_id;
          const zoomed = isFullscreenCamera && zoomState.scale > 1;

          return (
            <article
              key={camera.camera_id}
              className={`live-stream-card${draggedCameraId === camera.camera_id ? " live-stream-card--dragging" : ""}`}
              ref={(element) => {
                containerRefs.current[camera.camera_id] = element;
              }}
              data-camera-id={camera.camera_id}
              draggable
              onDragStart={(event) => {
                event.dataTransfer.effectAllowed = "move";
                event.dataTransfer.setData("text/plain", String(camera.camera_id));
                setDraggedCameraId(camera.camera_id);
                setDraggedSlotIndex(slotIndex);
              }}
              onDragEnd={() => {
                setDraggedCameraId(null);
                setDraggedSlotIndex(null);
              }}
              onDragOver={(event: DragEvent<HTMLElement>) => event.preventDefault()}
              onDrop={() => handleDropToSlot(slotIndex, camera.camera_id)}
            >
              <div className="live-stream-card__meta">
                <div>
                  <h3 className="live-stream-card__title">{camera.name}</h3>
                  <div className="live-stream-card__location">{camera.location || "Локация не указана"}</div>
                </div>

                <div className="page-actions">
                  {camera.onvif_enabled && <span className="pill">ONVIF</span>}
                  <button
                    className="btn icon"
                    title="Развернуть"
                    onClick={() => void toggleFullscreen(camera.camera_id)}
                    type="button"
                  >
                    ⤢
                  </button>
                </div>
              </div>

              <div
                className={`live-stream-stage${zoomed ? " is-zoomed" : ""}`}
                onWheel={(event) => handleDigitalZoom(camera.camera_id, event)}
                onDoubleClick={() => isFullscreenCamera && resetDigitalZoom()}
              >
                {token &&
                  (streamErrorMap[camera.camera_id] ? (
                    <div className="live-stream-empty">
                      <div style={{ fontWeight: 700 }}>Нет live-потока</div>
                      <div className="muted" style={{ lineHeight: 1.55 }}>
                        Назначьте камеру на Processor и убедитесь, что сам Processor запущен и находится онлайн.
                      </div>
                      <div>
                        <button
                          className="btn secondary"
                          onClick={() => {
                            setStreamErrorMap((prev) => ({ ...prev, [camera.camera_id]: false }));
                            setStreamRetryMap((prev) => ({ ...prev, [camera.camera_id]: (prev[camera.camera_id] || 0) + 1 }));
                          }}
                          type="button"
                        >
                          Повторить
                        </button>
                      </div>
                    </div>
                  ) : (
                    <img
                      src={`${API_URL}/cameras/${camera.camera_id}/stream?token=${encodeURIComponent(token)}&r=${streamRetryMap[camera.camera_id] || 0}`}
                      alt={camera.name}
                      loading="lazy"
                      decoding="async"
                      style={
                        isFullscreenCamera
                          ? {
                              transform: `scale(${zoomState.scale})`,
                              transformOrigin: `${zoomState.originX}% ${zoomState.originY}%`,
                            }
                          : undefined
                      }
                      onLoad={() => {
                        setStreamErrorMap((prev) => (prev[camera.camera_id] ? { ...prev, [camera.camera_id]: false } : prev));
                      }}
                      onError={() => {
                        setStreamErrorMap((prev) => ({ ...prev, [camera.camera_id]: true }));
                      }}
                    />
                  ))}

                {isFullscreenCamera && (
                  <div className="live-fullscreen-overlay">
                    <div className="live-fullscreen-topbar">
                      <div className="stack" style={{ gap: 4 }}>
                        <div className="live-fullscreen-title">{camera.name}</div>
                        <div className="row" style={{ gap: 8 }}>
                          <span className="pill">В реальном времени</span>
                          {camera.location && <span className="pill">{camera.location}</span>}
                          {zoomState.scale > 1 && <span className="pill">Цифровой zoom x{zoomState.scale.toFixed(1)}</span>}
                        </div>
                      </div>

                      <div className="page-actions">
                        {zoomState.scale > 1 && (
                          <button className="btn secondary" type="button" onClick={resetDigitalZoom}>
                            Сбросить zoom
                          </button>
                        )}
                        <button className="btn secondary" type="button" onClick={() => document.exitFullscreen?.()}>
                          Закрыть
                        </button>
                      </div>
                    </div>

                    {showPtzPanel && (
                      <aside className="live-ptz-panel">
                        <div className="live-ptz-panel__header">
                          <div>
                            <div className="page-hero__eyebrow">ONVIF</div>
                            <div className="panel-card__title">Управление камерой</div>
                          </div>
                          {fullscreenBusy && <span className="pill">Синхронизация...</span>}
                        </div>

                        {fullscreenError && <div className="danger">{fullscreenError}</div>}

                        {fullscreenDetail?.device_metadata && (
                          <div className="live-ptz-info">
                            <span className="pill">{String(fullscreenDetail.device_metadata.manufacturer || "ONVIF")}</span>
                            <span className="pill">{String(fullscreenDetail.device_metadata.model || "Камера")}</span>
                            {String(fullscreenDetail.device_metadata.firmware_version || "").trim() && (
                              <span className="pill">{String(fullscreenDetail.device_metadata.firmware_version)}</span>
                            )}
                          </div>
                        )}

                        <div className="page-actions">
                          <button className="btn secondary" type="button" onClick={syncOnvifDetail} disabled={fullscreenBusy}>
                            Синхронизировать
                          </button>
                          <button className="btn secondary" type="button" onClick={syncPresets} disabled={fullscreenBusy}>
                            Обновить пресеты
                          </button>
                        </div>

                        {ptzCapabilities.pan_tilt && (
                          <div className="live-ptz-dpad">
                            <div />
                            <button className="btn" type="button" {...bindHoldMove({ tilt: 0.7 })}>
                              Вверх
                            </button>
                            <div />
                            <button className="btn" type="button" {...bindHoldMove({ pan: -0.7 })}>
                              Влево
                            </button>
                            <button className="btn secondary" type="button" onClick={() => void stopMove(true)}>
                              Стоп
                            </button>
                            <button className="btn" type="button" {...bindHoldMove({ pan: 0.7 })}>
                              Вправо
                            </button>
                            <div />
                            <button className="btn" type="button" {...bindHoldMove({ tilt: -0.7 })}>
                              Вниз
                            </button>
                            <div />
                          </div>
                        )}

                        {(ptzCapabilities.zoom || ptzCapabilities.home) && (
                          <div className="page-actions">
                            {ptzCapabilities.zoom && (
                              <>
                                <button className="btn secondary" type="button" {...bindHoldMove({ zoom: 0.45 })}>
                                  Zoom +
                                </button>
                                <button className="btn secondary" type="button" {...bindHoldMove({ zoom: -0.45 })}>
                                  Zoom -
                                </button>
                              </>
                            )}
                            {ptzCapabilities.home && (
                              <button className="btn secondary" type="button" onClick={moveHome}>
                                Домой
                              </button>
                            )}
                          </div>
                        )}

                        <div className="live-ptz-hint">
                          Цифровой zoom: удерживайте <strong>Ctrl</strong> и крутите колесо мыши по кадру. Масштабирование идёт в точку под курсором.
                        </div>

                        {(Boolean(fullscreenDetail?.supports_ptz) || (fullscreenDetail?.presets?.length ?? 0) > 0) && (
                          <div className="stack" style={{ gap: 10 }}>
                            <div className="panel-card__title">Точки патруля</div>
                            <div className="muted">
                              Сохраните текущий ракурс как точку патруля. Если камера не поддерживает ONVIF-пресеты,
                              backend вернёт ошибку и точка не будет создана.
                            </div>
                            <div className="row" style={{ gap: 8 }}>
                              <input
                                className="input"
                                value={presetName}
                                onChange={(event) => setPresetName(event.target.value)}
                                placeholder="Название точки"
                              />
                              <button className="btn" type="button" onClick={createPreset} disabled={fullscreenBusy || !presetName.trim()}>
                                Добавить
                              </button>
                            </div>

                            <div className="live-preset-list">
                              {(fullscreenDetail?.presets ?? []).length === 0 ? (
                                <div className="muted">Точки патруля пока не созданы.</div>
                              ) : (
                                fullscreenDetail!.presets.map((preset) => (
                                  <div key={preset.camera_preset_id} className="live-preset-item">
                                    <div>
                                      <div className="live-preset-item__title">{preset.name}</div>
                                      <div className="muted">token: {preset.preset_token || "не задан"}</div>
                                    </div>
                                    <div className="page-actions">
                                      {preset.preset_token && (
                                        <button className="btn secondary" type="button" onClick={() => void gotoPreset(preset.camera_preset_id)}>
                                          Перейти
                                        </button>
                                      )}
                                      <button className="btn secondary" type="button" onClick={() => void removePreset(preset.camera_preset_id)}>
                                        Удалить
                                      </button>
                                    </div>
                                  </div>
                                ))
                              )}
                            </div>
                          </div>
                        )}
                      </aside>
                    )}
                  </div>
                )}
              </div>
            </article>
          );
        })}

        {filteredCameras.length === 0 && (
          <div className="panel-card">
            <div className="panel-card__header">
              <div>
                <h3 className="panel-card__title">Нет камер в выбранном срезе</h3>
                <div className="panel-card__lead">Смените фильтр группы или добавьте камеры в backend.</div>
              </div>
            </div>
          </div>
        )}
      </section>
    </div>
  );
};

export default LivePage;
