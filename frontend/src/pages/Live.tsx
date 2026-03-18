import { useEffect, useRef, useState } from "react";
import { API_URL, getCameras } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { useHome } from "../context/HomeContext";

type Cam = { camera_id: number; name: string; location?: string };

const LivePage: React.FC = () => {
  const { token } = useAuth();
  const { currentHome } = useHome();
  const [cams, setCams] = useState<Cam[]>([]);
  const [error, setError] = useState<string | null>(null);
  const containerRefs = useRef<Record<number, HTMLDivElement | null>>({});

  useEffect(() => {
    if (!token) return;
    getCameras(token, currentHome?.home_id)
      .then((res) => setCams(res))
      .catch((e) => setError(e?.message || "Не удалось загрузить камеры"));
  }, [token, currentHome]);

  return (
    <div className="stack" style={{ marginTop: 18 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <h2 className="title">Live</h2>
        {error && <div className="danger">{error}</div>}
      </div>
      <div className="grid">
        {cams.map((c) => (
          <div
            key={c.camera_id}
            className="card live-card"
            ref={(el) => {
              containerRefs.current[c.camera_id] = el;
            }}
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
              <img
                src={`${API_URL}/cameras/${c.camera_id}/stream?token=${encodeURIComponent(token)}`}
                alt={`camera-${c.camera_id}`}
                style={{ width: "100%", borderRadius: 8, background: "#0d1b2a", marginTop: 8 }}
              />
            )}
          </div>
        ))}
        {cams.length === 0 && <div className="card">Нет камер по вашим правам.</div>}
      </div>
    </div>
  );
};

export default LivePage;
