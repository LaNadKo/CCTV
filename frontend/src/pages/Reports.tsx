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
    } catch (event: any) {
      setError(event?.message || "Ошибка загрузки отчёта.");
    } finally {
      setLoading(false);
    }
  };

  const exportReport = async (format: "pdf" | "xlsx" | "docx") => {
    if (!token) return;
    const url = appearanceExportUrl(token, format, params);
    try {
      const response = await fetch(url, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) {
        throw new Error("Не удалось сформировать экспорт.");
      }
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = `report.${format}`;
      link.click();
      URL.revokeObjectURL(objectUrl);
    } catch (event: any) {
      alert(event?.message || "Ошибка экспорта.");
    }
  };

  return (
    <div className="stack">
      <section className="page-hero">
        <div className="page-hero__content">
          <div className="page-hero__eyebrow">Analytics</div>
          <h2 className="title">Отчёты</h2>
        </div>

        <div className="page-actions">
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
      </section>

      <section className="toolbar-card">
        <label className="field">
          <span className="label">Дата от</span>
          <input className="input" type="datetime-local" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
        </label>
        <label className="field">
          <span className="label">Дата до</span>
          <input className="input" type="datetime-local" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
        </label>
        <div className="field" style={{ position: "relative" }}>
          <span className="label">Персона</span>
          <input
            className="input"
            value={selectedPerson ? personLabel(selectedPerson) : personQuery}
            onFocus={() => setPersonOpen(true)}
            onChange={(event) => {
              setSelectedPerson(null);
              setPersonQuery(event.target.value);
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
        <button className="btn" onClick={loadReport} disabled={loading}>
          {loading ? "Формируем..." : "Сформировать"}
        </button>
      </section>

      {error && <div className="danger">{error}</div>}

      <section className="summary-grid">
        <div className="summary-card">
          <div className="summary-card__label">Записей в отчёте</div>
          <div className="summary-card__value">{report?.total ?? "—"}</div>
          <div className="summary-card__hint">После фильтрации по датам и выбранной персоне.</div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">Фильтр по персоне</div>
          <div className="summary-card__value">{selectedPerson ? personLabel(selectedPerson) : "Все"}</div>
          <div className="summary-card__hint">Используется неточный поиск, поэтому искать можно не только точное ФИО.</div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">Период</div>
          <div className="summary-card__value">{dateFrom || dateTo ? "Выбран" : "Весь"}</div>
          <div className="summary-card__hint">Если период не указан, отчёт строится по всем доступным подтверждённым событиям.</div>
        </div>
      </section>

      {report && (
        <section className="panel-card">
          <div className="panel-card__header">
            <div>
              <h3 className="panel-card__title">Подтверждённые появления</h3>
              <div className="panel-card__lead">
                Таблица сразу пригодна для просмотра оператором и для экспорта без отдельной постобработки.
              </div>
            </div>
            <span className="pill">{report.total} записей</span>
          </div>

          {report.items.length === 0 ? (
            <div className="muted">За указанный период подтверждённых появлений не найдено.</div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table className="soft-table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Время</th>
                    <th>Камера</th>
                    <th>Локация</th>
                    <th>Группа</th>
                    <th>Персона</th>
                    <th style={{ textAlign: "right" }}>Уверенность</th>
                  </tr>
                </thead>
                <tbody>
                  {report.items.map((item, index) => (
                    <tr key={item.event_id}>
                      <td>{index + 1}</td>
                      <td>{new Date(item.event_ts).toLocaleString()}</td>
                      <td>{item.camera_name || `#${item.camera_id}`}</td>
                      <td>{item.camera_location || "-"}</td>
                      <td>{item.group_name || "-"}</td>
                      <td>{item.person_label || (item.person_id ? `ID ${item.person_id}` : "-")}</td>
                      <td style={{ textAlign: "right" }}>
                        {item.confidence != null ? `${Number(item.confidence).toFixed(1)}%` : "-"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </div>
  );
};

export default ReportsPage;
