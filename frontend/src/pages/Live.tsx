import { useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "../context/AuthContext";
import { API_URL, getCameras, listGroups, type GroupOut } from "../lib/api";
import { loadUiSettings } from "../lib/uiSettings";

type CameraItem = {
  camera_id: number;
  name: string;
  location?: string;
  group_id?: number | null;
};

const LivePage: React.FC = () => {
  const { token } = useAuth();
  const [cameras, setCameras] = useState<CameraItem[]>([]);
  const [groups, setGroups] = useState<GroupOut[]>([]);
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [streamErrorMap, setStreamErrorMap] = useState<Record<number, boolean>>({});
  const [streamRetryMap, setStreamRetryMap] = useState<Record<number, number>>({});
  const containerRefs = useRef<Record<number, HTMLElement | null>>({});
  const uiSettings = loadUiSettings();

  const densityStyle =
    uiSettings.liveDensity === "focus"
      ? { min: 420, max: 540, label: "Крупно" }
      : uiSettings.liveDensity === "comfortable"
        ? { min: 320, max: 430, label: "Стандартно" }
        : { min: 260, max: 340, label: "Компактно" };

  useEffect(() => {
    if (!token) return;
    Promise.all([getCameras(token), listGroups(token)])
      .then(([cameraItems, groupItems]) => {
        setCameras(cameraItems);
        setGroups(groupItems);
      })
      .catch((event) => setError(event?.message || "Не удалось загрузить камеры"));
  }, [token]);

  const filteredCameras = useMemo(
    () => (selectedGroupId ? cameras.filter((camera) => camera.group_id === selectedGroupId) : cameras),
    [cameras, selectedGroupId]
  );

  const selectedGroupName = useMemo(
    () => groups.find((group) => group.group_id === selectedGroupId)?.name || "Все группы",
    [groups, selectedGroupId]
  );

  return (
    <div className="stack">
      <section className="toolbar-card">
        <div className="stack" style={{ gap: 4 }}>
          <h2 className="title">Live</h2>
          <div className="muted">
            {selectedGroupName} · {filteredCameras.length} камер · {densityStyle.label}
          </div>
        </div>

        <div className="page-actions">
          {groups.length > 0 && (
            <label className="field" style={{ minWidth: 220 }}>
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

      <section
        className="live-grid live-grid--cards"
        style={{
          gridTemplateColumns: `repeat(auto-fit, minmax(${densityStyle.min}px, ${densityStyle.max}px))`,
        }}
      >
        {filteredCameras.map((camera) => (
          <article
            key={camera.camera_id}
            className="live-stream-card"
            ref={(element) => {
              containerRefs.current[camera.camera_id] = element;
            }}
          >
            <div className="live-stream-card__meta">
              <div>
                <h3 className="live-stream-card__title">{camera.name}</h3>
                <div className="live-stream-card__location">{camera.location || "Локация не указана"}</div>
              </div>

              <button
                className="btn icon"
                title="На весь экран"
                onClick={() => {
                  const node = containerRefs.current[camera.camera_id];
                  if (!node) return;
                  if (!document.fullscreenElement) {
                    node.requestFullscreen?.();
                  } else {
                    document.exitFullscreen?.();
                  }
                }}
                type="button"
              >
                ⤢
              </button>
            </div>

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
                  alt={`camera-${camera.camera_id}`}
                  loading="lazy"
                  decoding="async"
                  onLoad={() => {
                    setStreamErrorMap((prev) => (prev[camera.camera_id] ? { ...prev, [camera.camera_id]: false } : prev));
                  }}
                  onError={() => {
                    setStreamErrorMap((prev) => ({ ...prev, [camera.camera_id]: true }));
                  }}
                />
              ))}
          </article>
        ))}

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
