import { useEffect, useMemo, useState } from "react";
import { appearanceExportUrl, getAppearanceReport, listPersons, type AppearanceReport, type PersonOut } from "../lib/api";
import { fuzzyFilter } from "../lib/fuzzy";
import { useAuth } from "../context/AuthContext";

function personLabel(person: PersonOut): string {
  return [person.last_name, person.first_name, person.middle_name].filter(Boolean).join(" ") || `ID ${person.person_id}`;
}

const ReportsPage: React.FC = () => {
  const { token } = useAuth();
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [personQuery, setPersonQuery] = useState("");
  const [personOpen, setPersonOpen] = useState(false);
  const [selectedPerson, setSelectedPerson] = useState<PersonOut | null>(null);
  const [persons, setPersons] = useState<PersonOut[]>([]);
  const [report, setReport] = useState<AppearanceReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    listPersons(token)
      .then(setPersons)
      .catch(() => setPersons([]));
  }, [token]);

  const personOptions = useMemo(
    () => fuzzyFilter(persons, personQuery, (person) => [personLabel(person), String(person.person_id)]),
    [persons, personQuery]
  );

  const params = {
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    person_id: selectedPerson?.person_id,
  };

  const loadReport = async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      setReport(await getAppearanceReport(token, params));
    } catch (e: any) {
      setError(e?.message || "Ошибка загрузки отчёта.");
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
        throw new Error("Не удалось сформировать экспорт.");
      }
      const blob = await res.blob();
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = `report.${format}`;
      link.click();
      URL.revokeObjectURL(objectUrl);
    } catch (e: any) {
      alert(e?.message || "Ошибка экспорта.");
    }
  };

  return (
    <div className="stack" style={{ marginTop: 18 }}>
      <h2 className="title">Отчёты</h2>
      <div className="muted">
        Отчёт строится только по подтверждённым появлениям и показывает, где стоит камера и в какой группе она состоит.
      </div>

      <div className="card stack">
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
          <label className="field">
            <span className="label">Дата от</span>
            <input className="input" type="datetime-local" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          </label>
          <label className="field">
            <span className="label">Дата до</span>
            <input className="input" type="datetime-local" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
          </label>
          <div className="field" style={{ position: "relative" }}>
            <span className="label">Персона</span>
            <input
              className="input"
              value={selectedPerson ? personLabel(selectedPerson) : personQuery}
              onFocus={() => setPersonOpen(true)}
              onChange={(e) => {
                setSelectedPerson(null);
                setPersonQuery(e.target.value);
                setPersonOpen(true);
              }}
              placeholder="Все персоны"
            />
            {personOpen && (
              <div className="menu-dropdown" style={{ left: 0, right: 0, top: "calc(100% + 6px)", maxHeight: 260, overflowY: "auto" }}>
                <button
                  type="button"
                  className="menu-link"
                  onClick={() => {
                    setSelectedPerson(null);
                    setPersonQuery("");
                    setPersonOpen(false);
                  }}
                >
                  Все персоны
                </button>
                {personOptions.slice(0, 10).map((person) => (
                  <button
                    key={person.person_id}
                    type="button"
                    className="menu-link"
                    onClick={() => {
                      setSelectedPerson(person);
                      setPersonQuery("");
                      setPersonOpen(false);
                    }}
                  >
                    {personLabel(person)}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
        <div className="row" style={{ gap: 8 }}>
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
            <div className="muted">За указанный период подтверждённых появлений нет.</div>
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
                        {item.confidence != null ? `${Number(item.confidence).toFixed(1)}%` : "-"}
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
