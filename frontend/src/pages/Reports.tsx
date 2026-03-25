import { useState } from "react";
import { appearanceExportUrl, getAppearanceReport, type AppearanceReport } from "../lib/api";
import { useAuth } from "../context/AuthContext";

const ReportsPage: React.FC = () => {
  const { token } = useAuth();
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [personId, setPersonId] = useState("");
  const [report, setReport] = useState<AppearanceReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const params = {
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    person_id: personId ? Number(personId) : undefined,
  };

  const loadReport = async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const result = await getAppearanceReport(token, params);
      setReport(result);
    } catch (e: any) {
      setError(e?.message || "Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  };

  const exportReport = async (format: "pdf" | "xlsx" | "docx") => {
    if (!token) return;
    const url = appearanceExportUrl(token, format, params);
    try {
      const res = await fetch(url, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        throw new Error("Не удалось сформировать экспорт");
      }
      const blob = await res.blob();
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = `report.${format}`;
      link.click();
      URL.revokeObjectURL(objectUrl);
    } catch (e: any) {
      alert(e?.message || "Ошибка экспорта");
    }
  };

  return (
    <div className="stack" style={{ marginTop: 18 }}>
      <h2 className="title">Отчёты</h2>
      <div className="muted">Отчёт строится только по подтвержденным появлениям и показывает, где стояла камера и в какой группе она состоит.</div>

      <div className="card">
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 8 }}>
          <label className="field">
            <span className="label">Дата от</span>
            <input className="input" type="datetime-local" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          </label>
          <label className="field">
            <span className="label">Дата до</span>
            <input className="input" type="datetime-local" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
          </label>
          <label className="field">
            <span className="label">ID персоны</span>
            <input className="input" type="number" value={personId} onChange={(e) => setPersonId(e.target.value)} placeholder="Все" />
          </label>
        </div>
        <div className="row" style={{ gap: 8, marginTop: 12 }}>
          <button className="btn" onClick={loadReport} disabled={loading}>
            {loading ? "Загрузка..." : "Сформировать"}
          </button>
          <button className="btn secondary" onClick={() => exportReport("pdf")}>
            PDF
          </button>
          <button className="btn secondary" onClick={() => exportReport("xlsx")}>
            XLSX
          </button>
          <button className="btn secondary" onClick={() => exportReport("docx")}>
            DOCX
          </button>
        </div>
      </div>

      {error && <div className="danger">{error}</div>}

      {report && (
        <div className="card">
          <div className="row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
            <h3 style={{ margin: 0 }}>Результат</h3>
            <span className="muted">Всего: {report.total}</span>
          </div>

          {report.items.length === 0 ? (
            <div className="muted">За указанный период данных нет.</div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid var(--border)" }}>
                    <th style={{ padding: "6px 8px", textAlign: "left" }}>#</th>
                    <th style={{ padding: "6px 8px", textAlign: "left" }}>Время</th>
                    <th style={{ padding: "6px 8px", textAlign: "left" }}>Камера</th>
                    <th style={{ padding: "6px 8px", textAlign: "left" }}>Локация</th>
                    <th style={{ padding: "6px 8px", textAlign: "left" }}>Группа</th>
                    <th style={{ padding: "6px 8px", textAlign: "left" }}>Персона</th>
                    <th style={{ padding: "6px 8px", textAlign: "right" }}>Уверенность</th>
                  </tr>
                </thead>
                <tbody>
                  {report.items.map((item, index) => (
                    <tr key={item.event_id} style={{ borderBottom: "1px solid var(--border)" }}>
                      <td style={{ padding: "6px 8px" }}>{index + 1}</td>
                      <td style={{ padding: "6px 8px" }}>{new Date(item.event_ts).toLocaleString()}</td>
                      <td style={{ padding: "6px 8px" }}>{item.camera_name || `#${item.camera_id}`}</td>
                      <td style={{ padding: "6px 8px" }}>{item.camera_location || "-"}</td>
                      <td style={{ padding: "6px 8px" }}>{item.group_name || "-"}</td>
                      <td style={{ padding: "6px 8px" }}>{item.person_label || (item.person_id ? `ID ${item.person_id}` : "-")}</td>
                      <td style={{ padding: "6px 8px", textAlign: "right" }}>
                        {item.confidence != null ? item.confidence.toFixed(2) : "-"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default ReportsPage;
