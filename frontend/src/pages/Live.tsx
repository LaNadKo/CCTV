import { useEffect, useRef, useState } from "react";
import { API_URL, getCameras, listGroups, type GroupOut } from "../lib/api";
import { useAuth } from "../context/AuthContext";

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
  const containerRefs = useRef<Record<number, HTMLDivElement | null>>({});

  useEffect(() => {
    if (!token) return;
    Promise.all([getCameras(token), listGroups(token)])
      .then(([cameraItems, groupItems]) => {
        setCameras(cameraItems);
        setGroups(groupItems);
      })
      .catch((e) => setError(e?.message || "Не удалось загрузить камеры"));
  }, [token]);

  const filteredCameras = selectedGroupId ? cameras.filter((camera) => camera.group_id === selectedGroupId) : cameras;

  return (
    <div className="stack" style={{ marginTop: 18 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <h2 className="title">Live</h2>
        {groups.length > 0 && (
          <select
            className="input"
            style={{ fontSize: 13, padding: "4px 8px" }}
            value={selectedGroupId ?? ""}
            onChange={(e) => setSelectedGroupId(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">Все камеры</option>
            {groups.map((group) => (
              <option key={group.group_id} value={group.group_id}>
                {group.name}
              </option>
            ))}
          </select>
        )}
      </div>

      {error && <div className="danger">{error}</div>}

      <div
        className="grid"
        style={{
          gridTemplateColumns: "repeat(auto-fit, minmax(280px, 360px))",
          justifyContent: "start",
        }}
      >
        {filteredCameras.map((camera) => (
          <div
            key={camera.camera_id}
            className="card live-card"
            ref={(element) => {
              containerRefs.current[camera.camera_id] = element;
            }}
          >
            <div className="row" style={{ justifyContent: "space-between" }}>
              <div>
                <h3 style={{ margin: 0 }}>{camera.name}</h3>
                <div className="muted">{camera.location || "Локация не указана"}</div>
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
              >
                ⤢
              </button>
            </div>

            {token &&
              (streamErrorMap[camera.camera_id] ? (
                <div
                  style={{
                    marginTop: 8,
                    padding: 14,
                    minHeight: 180,
                    borderRadius: 8,
                    background: "#0d1b2a",
                    border: "1px solid rgba(255,255,255,0.06)",
                    display: "flex",
                    flexDirection: "column",
                    justifyContent: "center",
                    gap: 8,
                  }}
                >
                  <div style={{ fontWeight: 700 }}>Нет live-потока</div>
                  <div className="muted" style={{ lineHeight: 1.45 }}>
                    Назначьте камеру на Processor во вкладке «Процессоры» и убедитесь, что сам Processor запущен и находится онлайн.
                  </div>
                  <div>
                    <button
                      className="btn secondary"
                      onClick={() => {
                        setStreamErrorMap((prev) => ({ ...prev, [camera.camera_id]: false }));
                        setStreamRetryMap((prev) => ({ ...prev, [camera.camera_id]: (prev[camera.camera_id] || 0) + 1 }));
                      }}
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
                  style={{ width: "100%", borderRadius: 8, background: "#0d1b2a", marginTop: 8 }}
                />
              ))}
          </div>
        ))}
        {filteredCameras.length === 0 && <div className="card">Нет камер.</div>}
      </div>
    </div>
  );
};

export default LivePage;
