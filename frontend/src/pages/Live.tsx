import { useEffect, useRef, useState } from "react";
import { API_URL, getCameras, listGroups, type GroupOut } from "../lib/api";
import { useAuth } from "../context/AuthContext";

type Cam = { camera_id: number; name: string; location?: string; group_id?: number | null };

const LivePage: React.FC = () => {
  const { token } = useAuth();
  const [cams, setCams] = useState<Cam[]>([]);
  const [groups, setGroups] = useState<GroupOut[]>([]);
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [streamErrorMap, setStreamErrorMap] = useState<Record<number, boolean>>({});
  const [streamRetryMap, setStreamRetryMap] = useState<Record<number, number>>({});
  const containerRefs = useRef<Record<number, HTMLDivElement | null>>({});

  useEffect(() => {
    if (!token) return;
    Promise.all([getCameras(token), listGroups(token)])
      .then(([c, g]) => { setCams(c); setGroups(g); })
      .catch((e) => setError(e?.message || "Не удалось загрузить камеры"));
  }, [token]);

  const filteredCams = selectedGroupId
    ? cams.filter((c) => c.group_id === selectedGroupId)
    : cams;

  return (
    <div className="stack" style={{ marginTop: 18 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <h2 className="title">Live</h2>
        <div className="row" style={{ gap: 8 }}>
          {groups.length > 0 && (
            <select
              className="input"
              style={{ fontSize: 13, padding: "4px 8px" }}
              value={selectedGroupId ?? ""}
              onChange={(e) => setSelectedGroupId(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">Все камеры</option>
              {groups.map((g) => (
                <option key={g.group_id} value={g.group_id}>{g.name}</option>
              ))}
            </select>
          )}
        </div>
      </div>
      {error && <div className="danger">{error}</div>}
      <div
        className="grid"
        style={{
          gridTemplateColumns: "repeat(auto-fit, minmax(320px, 420px))",
          justifyContent: "start",
        }}
      >
        {filteredCams.map((c) => (
          <div
            key={c.camera_id}
            className="card live-card"
            ref={(el) => { containerRefs.current[c.camera_id] = el; }}
          >
            <div className="row" style={{ justifyContent: "space-between" }}>
              <div>
                <h3 style={{ margin: 0 }}>{c.name}</h3>
                <div className="muted">{c.location || "Без локации"}</div>
              </div>
              <button
                className="btn icon"
                title="На весь экран"
                onClick={() => {
                  const node = containerRefs.current[c.camera_id];
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
            {token && (
              streamErrorMap[c.camera_id] ? (
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
                    Назначьте камеру на `Processor` во вкладке «Процессоры» и убедитесь, что сам
                    `Processor` запущен и находится онлайн.
                  </div>
                  <div>
                    <button
                      className="btn secondary"
                      onClick={() => {
                        setStreamErrorMap((prev) => ({ ...prev, [c.camera_id]: false }));
                        setStreamRetryMap((prev) => ({ ...prev, [c.camera_id]: (prev[c.camera_id] || 0) + 1 }));
                      }}
                    >
                      Повторить
                    </button>
                  </div>
                </div>
              ) : (
                <img
                  src={`${API_URL}/cameras/${c.camera_id}/stream?token=${encodeURIComponent(token)}&r=${streamRetryMap[c.camera_id] || 0}`}
                  alt={`camera-${c.camera_id}`}
                  loading="lazy"
                  decoding="async"
                  onLoad={() => {
                    setStreamErrorMap((prev) => (prev[c.camera_id] ? { ...prev, [c.camera_id]: false } : prev));
                  }}
                  onError={() => {
                    setStreamErrorMap((prev) => ({ ...prev, [c.camera_id]: true }));
                  }}
                  style={{ width: "100%", borderRadius: 8, background: "#0d1b2a", marginTop: 8 }}
                />
              )
            )}
          </div>
        ))}
        {filteredCams.length === 0 && <div className="card">Нет камер.</div>}
      </div>
    </div>
  );
};

export default LivePage;
