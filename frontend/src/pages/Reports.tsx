import { useEffect, useMemo, useState } from "react";
import {
  adminListUsers,
  appearanceExportUrl,
  dashboardSectionExportUrl,
  getAppearanceReport,
  getCameras,
  getReportsDashboard,
  listGroups,
  listPersons,
  listProcessors,
  type AppearanceItem,
  type AppearanceReport,
  type CameraSummary,
  type CurrentUser,
  type GroupOut,
  type PersonOut,
  type ProcessorOut,
  type ReportsDashboard,
  type UserOut,
} from "../lib/api";
import { useAuth } from "../context/AuthContext";

type DashboardSectionKey = "user-actions" | "groups" | "cameras" | "processors" | "events" | "archive" | "security";
type ReportTabKey = "overview" | DashboardSectionKey | "appearances";

const REPORT_TABS: Array<{ key: ReportTabKey; label: string; description: string }> = [
  { key: "overview", label: "Сводка", description: "Общая картина по пользователям, камерам, архиву, событиям и безопасности." },
  { key: "user-actions", label: "Пользователи", description: "Действия пользователей, входы, обзоры по ролям и операционной активности." },
  { key: "groups", label: "Группы", description: "Статистика по группам камер, покрытию, событиям и распределению нагрузки." },
  { key: "cameras", label: "Камеры", description: "Состояние камер, число событий, ошибки потоков и активность архива." },
  { key: "processors", label: "Процессоры", description: "Heartbeat, состояние Processor, загрузка и эффективность обработки камер." },
  { key: "events", label: "События", description: "Сводка по типам событий, ревью и подтверждённым результатам." },
  { key: "archive", label: "Архив", description: "Объёмы записей, интервалы хранения и динамика по архивным файлам." },
  { key: "security", label: "Безопасность", description: "Аутентификация, TOTP, API-ключи и другие показатели защищённости системы." },
  { key: "appearances", label: "Появления", description: "Подтверждённые появления персон за период с отдельным экспортом." },
];

function personLabel(person: PersonOut): string {
  return [person.last_name, person.first_name, person.middle_name].filter(Boolean).join(" ") || `ID ${person.person_id}`;
}

function userLabel(user: Pick<CurrentUser, "login" | "first_name" | "last_name" | "middle_name"> | UserOut): string {
  return [user.last_name, user.first_name, user.middle_name].filter(Boolean).join(" ") || user.login;
}

function formatDateTime(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function formatBytes(bytes?: number | null): string {
  const value = Number(bytes || 0);
  if (!Number.isFinite(value) || value <= 0) return "0 Б";
  const units = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
  let current = value;
  let unitIndex = 0;
  while (current >= 1024 && unitIndex < units.length - 1) {
    current /= 1024;
    unitIndex += 1;
  }
  return `${current.toFixed(current >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

function formatDuration(seconds?: number | null): string {
  if (!seconds || seconds <= 0) return "—";
  const total = Math.round(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours > 0) return `${hours} ч ${minutes} мин`;
  if (minutes > 0) return `${minutes} мин ${secs} с`;
  return `${secs} с`;
}

function aggregateAppearanceByCamera(items: AppearanceItem[]): Array<{ label: string; value: number }> {
  const counter = new Map<string, number>();
  for (const item of items) {
    const key = item.camera_name || `Камера #${item.camera_id}`;
    counter.set(key, (counter.get(key) || 0) + 1);
  }
  return [...counter.entries()]
    .map(([label, value]) => ({ label, value }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 6);
}

async function downloadBinary(url: string, token: string, filename: string, defaultError: string) {
  const response = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) throw new Error(defaultError);
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(objectUrl);
}

function ReportBarChart({
  title,
  items,
  formatter,
}: {
  title: string;
  items: { label: string; value: number }[];
  formatter?: (value: number) => string;
}) {
  const top = Math.max(...items.map((item) => item.value), 1);

  return (
    <div className="report-chart">
      <div className="report-chart__title">{title}</div>
      <div className="report-chart__bars">
        {items.length === 0 ? (
          <div className="muted">Нет данных для построения диаграммы.</div>
        ) : (
          items.map((item) => (
            <div key={item.label} className="report-chart__row">
              <div className="report-chart__meta">
                <span>{item.label}</span>
                <strong>{formatter ? formatter(item.value) : item.value}</strong>
              </div>
              <div className="report-chart__track">
                <div className="report-chart__fill" style={{ width: `${Math.max((item.value / top) * 100, 4)}%` }} />
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function SectionExports({ onExport }: { onExport: (format: "pdf" | "xlsx" | "docx") => void }) {
  return (
    <div className="page-actions">
      <button className="btn secondary" onClick={() => onExport("pdf")} type="button">PDF</button>
      <button className="btn secondary" onClick={() => onExport("xlsx")} type="button">XLSX</button>
      <button className="btn secondary" onClick={() => onExport("docx")} type="button">DOCX</button>
    </div>
  );
}

const ReportsPage: React.FC = () => {
  const { token } = useAuth();

  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [selectedGroupId, setSelectedGroupId] = useState("");
  const [selectedCameraId, setSelectedCameraId] = useState("");
  const [selectedProcessorId, setSelectedProcessorId] = useState("");
  const [selectedUserId, setSelectedUserId] = useState("");
  const [selectedPersonId, setSelectedPersonId] = useState("");
  const [activeTab, setActiveTab] = useState<ReportTabKey>("overview");

  const [groups, setGroups] = useState<GroupOut[]>([]);
  const [cameras, setCameras] = useState<CameraSummary[]>([]);
  const [processors, setProcessors] = useState<ProcessorOut[]>([]);
  const [users, setUsers] = useState<UserOut[]>([]);
  const [persons, setPersons] = useState<PersonOut[]>([]);

  const [dashboard, setDashboard] = useState<ReportsDashboard | null>(null);
  const [appearance, setAppearance] = useState<AppearanceReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedGroupValue = selectedGroupId ? Number(selectedGroupId) : undefined;
  const selectedCameraValue = selectedCameraId ? Number(selectedCameraId) : undefined;
  const selectedProcessorValue = selectedProcessorId ? Number(selectedProcessorId) : undefined;
  const selectedUserValue = selectedUserId ? Number(selectedUserId) : undefined;
  const selectedPersonValue = selectedPersonId ? Number(selectedPersonId) : undefined;
  const selectedPerson = persons.find((person) => person.person_id === selectedPersonValue) || null;

  const cameraOptions = useMemo(() => {
    if (!selectedGroupValue) return cameras;
    return cameras.filter((camera) => camera.group_id === selectedGroupValue);
  }, [cameras, selectedGroupValue]);

  useEffect(() => {
    if (!token) return;
    void (async () => {
      const [groupsResult, camerasResult, processorsResult, usersResult, personsResult] = await Promise.allSettled([
        listGroups(token),
        getCameras(token),
        listProcessors(token),
        adminListUsers(token),
        listPersons(token),
      ]);
      setGroups(groupsResult.status === "fulfilled" ? groupsResult.value : []);
      setCameras(camerasResult.status === "fulfilled" ? camerasResult.value : []);
      setProcessors(processorsResult.status === "fulfilled" ? processorsResult.value : []);
      setUsers(usersResult.status === "fulfilled" ? usersResult.value : []);
      setPersons(personsResult.status === "fulfilled" ? personsResult.value : []);
    })();
  }, [token]);

  useEffect(() => {
    if (!selectedCameraValue) return;
    const exists = cameraOptions.some((camera) => camera.camera_id === selectedCameraValue);
    if (!exists) setSelectedCameraId("");
  }, [cameraOptions, selectedCameraValue]);

  const loadReports = async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const params = {
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        group_id: selectedGroupValue,
        camera_id: selectedCameraValue,
        processor_id: selectedProcessorValue,
        user_id: selectedUserValue,
      };
      const appearanceParams = {
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        person_id: selectedPersonValue,
      };
      const [dashboardData, appearanceData] = await Promise.all([
        getReportsDashboard(token, params),
        getAppearanceReport(token, appearanceParams),
      ]);
      setDashboard(dashboardData);
      setAppearance(appearanceData);
    } catch (event: any) {
      setError(event?.message || "Не удалось загрузить отчёты.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!token) return;
    void loadReports();
  }, [token]);

  const resetFilters = () => {
    setDateFrom("");
    setDateTo("");
    setSelectedGroupId("");
    setSelectedCameraId("");
    setSelectedProcessorId("");
    setSelectedUserId("");
    setSelectedPersonId("");
  };

  const activeTabMeta = REPORT_TABS.find((tab) => tab.key === activeTab) || REPORT_TABS[0];

  const exportAppearance = async (format: "pdf" | "xlsx" | "docx") => {
    if (!token) return;
    const url = appearanceExportUrl(token, format, {
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      person_id: selectedPersonValue,
    });
    try {
      await downloadBinary(url, token, `appearances.${format}`, "Не удалось сформировать экспорт появлений.");
    } catch (event: any) {
      alert(event?.message || "Ошибка экспорта.");
    }
  };

  const exportSection = async (section: DashboardSectionKey, format: "pdf" | "xlsx" | "docx") => {
    if (!token) return;
    const url = dashboardSectionExportUrl(token, section, format, {
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      group_id: selectedGroupValue,
      camera_id: selectedCameraValue,
      processor_id: selectedProcessorValue,
      user_id: selectedUserValue,
    });
    try {
      await downloadBinary(url, token, `${section}.${format}`, "Не удалось сформировать экспорт раздела.");
    } catch (event: any) {
      alert(event?.message || "Ошибка экспорта.");
    }
  };

  const generatedAt = dashboard ? formatDateTime(dashboard.generated_at) : "—";
  const onlineProcessors = dashboard ? dashboard.processors.filter((processor) => processor.is_online).length : 0;
  const onlineCameras = dashboard ? dashboard.cameras.filter((camera) => camera.is_online).length : 0;
  const eventTypeChart = useMemo(
    () => (dashboard?.events.events_by_type ?? []).slice(0, 6).map((item) => ({ label: item.label, value: item.value })),
    [dashboard]
  );
  const groupChart = useMemo(
    () => (dashboard?.groups ?? []).slice(0, 6).map((item) => ({ label: item.name, value: item.event_count })),
    [dashboard]
  );
  const archiveChart = useMemo(
    () => (dashboard?.archive.by_storage ?? []).slice(0, 6).map((item) => ({ label: item.name, value: item.total_bytes })),
    [dashboard]
  );
  const processorChart = useMemo(
    () => (dashboard?.processors ?? []).slice(0, 6).map((item) => ({ label: item.name, value: item.event_count })),
    [dashboard]
  );
  const userActivityChart = useMemo(
    () => (dashboard?.user_actions.top_users ?? []).slice(0, 6).map((item) => ({ label: item.user_label, value: item.total_actions })),
    [dashboard]
  );
  const cameraChart = useMemo(
    () => (dashboard?.cameras ?? []).slice(0, 6).map((item) => ({ label: item.name, value: item.event_count })),
    [dashboard]
  );
  const securityChart = useMemo(
    () =>
      dashboard
        ? [
            { label: "Успешные входы", value: dashboard.security.successful_logins },
            { label: "Ошибки входа", value: dashboard.security.failed_logins },
            { label: "Пользователи с TOTP", value: dashboard.security.totp_enabled_users },
          ]
        : [],
    [dashboard]
  );
  const appearanceCameraChart = useMemo(() => aggregateAppearanceByCamera(appearance?.items ?? []), [appearance]);

  const renderOverview = () => (
    <div className="stack">
      <section className="summary-grid">
        <div className="summary-card">
          <div className="summary-card__label">Сформировано</div>
          <div className="summary-card__value" style={{ fontSize: "1.35rem" }}>{generatedAt}</div>
          <div className="summary-card__hint">Время последнего пересчёта dashboard.</div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">Пользовательские действия</div>
          <div className="summary-card__value">{dashboard?.user_actions.total_audit_actions ?? "—"}</div>
          <div className="summary-card__hint">Все зафиксированные действия из audit log.</div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">Камеры онлайн</div>
          <div className="summary-card__value">{dashboard ? `${onlineCameras}/${dashboard.cameras.length}` : "—"}</div>
          <div className="summary-card__hint">Камеры с активной связью через backend и processor.</div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">Процессоры онлайн</div>
          <div className="summary-card__value">{dashboard ? `${onlineProcessors}/${dashboard.processors.length}` : "—"}</div>
          <div className="summary-card__hint">Статус по heartbeat и состоянию processor.</div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">События</div>
          <div className="summary-card__value">{dashboard?.events.total_events ?? "—"}</div>
          <div className="summary-card__hint">Все события по текущему набору фильтров.</div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">Архив</div>
          <div className="summary-card__value">{dashboard ? formatBytes(dashboard.archive.total_bytes) : "—"}</div>
          <div className="summary-card__hint">Суммарный объём записей и снимков в архиве.</div>
        </div>
      </section>

      <section className="reports-chart-grid">
        <ReportBarChart title="События по типам" items={eventTypeChart} />
        <ReportBarChart title="Активность по группам камер" items={groupChart} />
        <ReportBarChart title="Нагрузка по процессорам" items={processorChart} />
        <ReportBarChart title="Архив по хранилищам" items={archiveChart} formatter={(value) => formatBytes(value)} />
      </section>
    </div>
  );

  const renderUserActions = () => (
    <section className="panel-card reports-tab-panel">
      <div className="panel-card__header">
        <div>
          <h3 className="panel-card__title">Действия пользователей</h3>
          <div className="panel-card__lead">Входы, действия в аудите и операции ревью событий.</div>
        </div>
        <div className="page-actions">
          <span className="pill">TOTP: {dashboard?.user_actions.totp_enabled_users ?? 0}</span>
          <SectionExports onExport={(format) => exportSection("user-actions", format)} />
        </div>
      </div>

      <div className="summary-grid" style={{ marginBottom: 16 }}>
        <div className="summary-card"><div className="summary-card__label">Активные пользователи</div><div className="summary-card__value">{dashboard?.user_actions.active_users ?? "—"}</div></div>
        <div className="summary-card"><div className="summary-card__label">События авторизации</div><div className="summary-card__value">{dashboard?.user_actions.total_auth_events ?? "—"}</div></div>
        <div className="summary-card"><div className="summary-card__label">Ошибки входа</div><div className="summary-card__value">{dashboard?.user_actions.failed_auth_events ?? "—"}</div></div>
        <div className="summary-card"><div className="summary-card__label">Действия ревью</div><div className="summary-card__value">{dashboard?.user_actions.review_actions ?? "—"}</div></div>
      </div>

      <div className="reports-chart-grid reports-chart-grid--single">
        <ReportBarChart title="Топ активности пользователей" items={userActivityChart} />
      </div>

      <div className="reports-two-column">
        <div style={{ overflowX: "auto" }}>
          <table className="soft-table">
            <thead><tr><th>Пользователь</th><th>Аудит</th><th>Входы</th><th>Ошибки</th><th>Ревью</th><th>Всего</th></tr></thead>
            <tbody>
              {(dashboard?.user_actions.top_users ?? []).map((item) => (
                <tr key={`${item.user_id ?? "system"}-${item.user_label}`}>
                  <td>{item.user_label}</td>
                  <td>{item.audit_actions}</td>
                  <td>{item.auth_success}</td>
                  <td>{item.auth_failures}</td>
                  <td>{item.review_actions}</td>
                  <td>{item.total_actions}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div style={{ overflowX: "auto" }}>
          <table className="soft-table">
            <thead><tr><th>Время</th><th>Тип</th><th>Пользователь</th><th>Действие</th><th>Детали</th></tr></thead>
            <tbody>
              {(dashboard?.user_actions.recent_actions ?? []).map((item, index) => (
                <tr key={`${item.occurred_at}-${index}`}>
                  <td>{formatDateTime(item.occurred_at)}</td>
                  <td>{item.action_kind}</td>
                  <td>{item.user_label}</td>
                  <td>{item.action}</td>
                  <td>{item.details || item.source_ip || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );

  const renderGroups = () => (
    <section className="panel-card reports-tab-panel">
      <div className="panel-card__header">
        <div>
          <h3 className="panel-card__title">Группы камер</h3>
          <div className="panel-card__lead">Состав групп, активность камер и накопленный архив.</div>
        </div>
        <SectionExports onExport={(format) => exportSection("groups", format)} />
      </div>

      <div className="reports-chart-grid reports-chart-grid--single">
        <ReportBarChart title="События по группам" items={groupChart} />
      </div>

      <div style={{ overflowX: "auto" }}>
        <table className="soft-table">
          <thead><tr><th>Группа</th><th>Камер</th><th>Онлайн</th><th>Оффлайн</th><th>Событий</th><th>Распознано</th><th>Pending review</th><th>Файлов</th><th>Объём</th></tr></thead>
          <tbody>
            {(dashboard?.groups ?? []).map((item) => (
              <tr key={item.group_id}>
                <td>{item.name}</td>
                <td>{item.camera_count}</td>
                <td>{item.online_cameras}</td>
                <td>{item.offline_cameras}</td>
                <td>{item.event_count}</td>
                <td>{item.recognized_count}</td>
                <td>{item.pending_reviews}</td>
                <td>{item.recordings_count}</td>
                <td>{formatBytes(item.recordings_size_bytes)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );

  const renderCameras = () => (
    <section className="panel-card reports-tab-panel">
      <div className="panel-card__header">
        <div>
          <h3 className="panel-card__title">Камеры</h3>
          <div className="panel-card__lead">Источники, PTZ, привязка к процессорам и объём событий.</div>
        </div>
        <SectionExports onExport={(format) => exportSection("cameras", format)} />
      </div>

      <div className="reports-chart-grid reports-chart-grid--single">
        <ReportBarChart title="События по камерам" items={cameraChart} />
      </div>

      <div style={{ overflowX: "auto" }}>
        <table className="soft-table">
          <thead><tr><th>Камера</th><th>Группа</th><th>Подключение</th><th>Процессор</th><th>Онлайн</th><th>PTZ</th><th>Событий</th><th>Motion</th><th>Unknown</th><th>Архив</th><th>Последнее событие</th></tr></thead>
          <tbody>
            {(dashboard?.cameras ?? []).map((item) => (
              <tr key={item.camera_id}>
                <td>{item.name}</td>
                <td>{item.group_name || "—"}</td>
                <td>{item.connection_kind}</td>
                <td>{item.assigned_processor || "—"}</td>
                <td>{item.is_online ? "Да" : "Нет"}</td>
                <td>{item.supports_ptz ? "Да" : "Нет"}</td>
                <td>{item.event_count}</td>
                <td>{item.motion_count}</td>
                <td>{item.unknown_count}</td>
                <td>{formatBytes(item.recordings_size_bytes)}</td>
                <td>{formatDateTime(item.last_event_ts)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );

  const renderProcessors = () => (
    <section className="panel-card reports-tab-panel">
      <div className="panel-card__header">
        <div>
          <h3 className="panel-card__title">Процессоры</h3>
          <div className="panel-card__lead">Heartbeat, загрузка, число назначенных камер и объём обработки.</div>
        </div>
        <SectionExports onExport={(format) => exportSection("processors", format)} />
      </div>

      <div className="reports-chart-grid reports-chart-grid--single">
        <ReportBarChart title="События по процессорам" items={processorChart} />
      </div>

      <div style={{ overflowX: "auto" }}>
        <table className="soft-table">
          <thead><tr><th>Процессор</th><th>Статус</th><th>IP</th><th>Версия</th><th>Камер</th><th>Событий</th><th>Файлов</th><th>CPU</th><th>RAM</th><th>GPU</th><th>Uptime</th></tr></thead>
          <tbody>
            {(dashboard?.processors ?? []).map((item) => (
              <tr key={item.processor_id}>
                <td>{item.name}</td>
                <td>{item.is_online ? "Онлайн" : item.status}</td>
                <td>{item.ip_address || "—"}</td>
                <td>{item.version || "—"}</td>
                <td>{item.assigned_cameras}</td>
                <td>{item.event_count}</td>
                <td>{item.recordings_count}</td>
                <td>{item.cpu_percent != null ? `${item.cpu_percent}%` : "—"}</td>
                <td>{item.ram_percent != null ? `${item.ram_percent}%` : "—"}</td>
                <td>{item.gpu_util_percent != null ? `${item.gpu_util_percent}%` : "—"}</td>
                <td>{formatDuration(item.uptime_seconds)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );

  const renderEvents = () => (
    <section className="panel-card reports-tab-panel">
      <div className="panel-card__header">
        <div>
          <h3 className="panel-card__title">События и ревью</h3>
          <div className="panel-card__lead">Распределение событий по типам и активность операторов в ревью.</div>
        </div>
        <SectionExports onExport={(format) => exportSection("events", format)} />
      </div>

      <div className="summary-grid" style={{ marginBottom: 16 }}>
        <div className="summary-card"><div className="summary-card__label">Распознанные</div><div className="summary-card__value">{dashboard?.events.recognized_events ?? "—"}</div></div>
        <div className="summary-card"><div className="summary-card__label">Неизвестные</div><div className="summary-card__value">{dashboard?.events.unknown_events ?? "—"}</div></div>
        <div className="summary-card"><div className="summary-card__label">Motion</div><div className="summary-card__value">{dashboard?.events.motion_events ?? "—"}</div></div>
        <div className="summary-card"><div className="summary-card__label">Pending review</div><div className="summary-card__value">{dashboard?.events.pending_reviews ?? "—"}</div></div>
        <div className="summary-card"><div className="summary-card__label">Среднее время ревью</div><div className="summary-card__value">{formatDuration(dashboard?.events.average_review_seconds)}</div></div>
      </div>

      <div className="reports-chart-grid reports-chart-grid--single">
        <ReportBarChart title="Распределение событий" items={eventTypeChart} />
      </div>

      <div className="reports-two-column">
        <div style={{ overflowX: "auto" }}>
          <table className="soft-table">
            <thead><tr><th>Тип события</th><th>Количество</th></tr></thead>
            <tbody>
              {(dashboard?.events.events_by_type ?? []).map((item) => (
                <tr key={item.label}>
                  <td>{item.label}</td>
                  <td>{item.value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div style={{ overflowX: "auto" }}>
          <table className="soft-table">
            <thead><tr><th>Ревьюер</th><th>Approved</th><th>Rejected</th><th>Pending</th><th>Всего</th></tr></thead>
            <tbody>
              {(dashboard?.events.top_reviewers ?? []).map((item) => (
                <tr key={`${item.user_id ?? "system"}-${item.user_label}`}>
                  <td>{item.user_label}</td>
                  <td>{item.approved}</td>
                  <td>{item.rejected}</td>
                  <td>{item.pending}</td>
                  <td>{item.total}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );

  const renderArchive = () => (
    <section className="panel-card reports-tab-panel">
      <div className="panel-card__header">
        <div>
          <h3 className="panel-card__title">Архив</h3>
          <div className="panel-card__lead">Объём и состав записей по камерам и хранилищам.</div>
        </div>
        <div className="page-actions">
          <span className="pill">{dashboard ? `${dashboard.archive.total_files} файлов` : "0 файлов"}</span>
          <SectionExports onExport={(format) => exportSection("archive", format)} />
        </div>
      </div>

      <div className="summary-grid" style={{ marginBottom: 16 }}>
        <div className="summary-card"><div className="summary-card__label">Видео</div><div className="summary-card__value">{dashboard?.archive.video_files ?? "—"}</div></div>
        <div className="summary-card"><div className="summary-card__label">Снимки</div><div className="summary-card__value">{dashboard?.archive.snapshot_files ?? "—"}</div></div>
        <div className="summary-card"><div className="summary-card__label">Общий объём</div><div className="summary-card__value">{dashboard ? formatBytes(dashboard.archive.total_bytes) : "—"}</div></div>
      </div>

      <div className="reports-chart-grid reports-chart-grid--single">
        <ReportBarChart title="Объём по хранилищам" items={archiveChart} formatter={(value) => formatBytes(value)} />
      </div>

      <div className="reports-two-column">
        <div style={{ overflowX: "auto" }}>
          <table className="soft-table">
            <thead><tr><th>Камера</th><th>Файлов</th><th>Объём</th><th>Последняя запись</th></tr></thead>
            <tbody>
              {(dashboard?.archive.by_camera ?? []).map((item) => (
                <tr key={item.camera_id}>
                  <td>{item.camera_name}</td>
                  <td>{item.file_count}</td>
                  <td>{formatBytes(item.total_bytes)}</td>
                  <td>{formatDateTime(item.last_recording_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div style={{ overflowX: "auto" }}>
          <table className="soft-table">
            <thead><tr><th>Хранилище</th><th>Файлов</th><th>Объём</th></tr></thead>
            <tbody>
              {(dashboard?.archive.by_storage ?? []).map((item) => (
                <tr key={item.storage_target_id}>
                  <td>{item.name}</td>
                  <td>{item.file_count}</td>
                  <td>{formatBytes(item.total_bytes)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );

  const renderSecurity = () => (
    <section className="panel-card reports-tab-panel">
      <div className="panel-card__header">
        <div>
          <h3 className="panel-card__title">Безопасность</h3>
          <div className="panel-card__lead">Покрытие TOTP, API-ключи и последние ошибки авторизации.</div>
        </div>
        <SectionExports onExport={(format) => exportSection("security", format)} />
      </div>

      <div className="summary-grid" style={{ marginBottom: 16 }}>
        <div className="summary-card"><div className="summary-card__label">Покрытие TOTP</div><div className="summary-card__value">{dashboard ? `${dashboard.security.totp_coverage_percent.toFixed(1)}%` : "—"}</div></div>
        <div className="summary-card"><div className="summary-card__label">Пользователей с TOTP</div><div className="summary-card__value">{dashboard?.security.totp_enabled_users ?? "—"}</div></div>
        <div className="summary-card"><div className="summary-card__label">API keys</div><div className="summary-card__value">{dashboard ? `${dashboard.security.api_keys_active}/${dashboard.security.api_keys_total}` : "—"}</div></div>
        <div className="summary-card"><div className="summary-card__label">Ошибки входа</div><div className="summary-card__value">{dashboard?.security.failed_logins ?? "—"}</div></div>
      </div>

      <div className="reports-chart-grid reports-chart-grid--single">
        <ReportBarChart title="События безопасности" items={securityChart} />
      </div>

      <div style={{ overflowX: "auto" }}>
        <table className="soft-table">
          <thead><tr><th>Время</th><th>Пользователь</th><th>Метод</th><th>Причина</th><th>IP</th></tr></thead>
          <tbody>
            {(dashboard?.security.recent_failures ?? []).map((item, index) => (
              <tr key={`${item.occurred_at}-${index}`}>
                <td>{formatDateTime(item.occurred_at)}</td>
                <td>{item.user_label}</td>
                <td>{item.method}</td>
                <td>{item.reason || "—"}</td>
                <td>{item.source_ip || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );

  const renderAppearances = () => (
    <section className="panel-card reports-tab-panel">
      <div className="panel-card__header">
        <div>
          <h3 className="panel-card__title">Подтверждённые появления</h3>
          <div className="panel-card__lead">Отдельный отчёт по подтверждённым распознаваниям с экспортом в PDF, XLSX и DOCX.</div>
        </div>
        <SectionExports onExport={exportAppearance} />
      </div>

      <div className="toolbar-card" style={{ marginBottom: 16 }}>
        <label className="field">
          <span className="label">Персона</span>
          <select className="select" value={selectedPersonId} onChange={(event) => setSelectedPersonId(event.target.value)}>
            <option value="">Все персоны</option>
            {persons.map((person) => (
              <option key={person.person_id} value={person.person_id}>{personLabel(person)}</option>
            ))}
          </select>
        </label>
        <div className="field">
          <span className="label">Фильтр</span>
          <div className="muted">Использует тот же период, что и основной dashboard. После смены фильтров нажмите «Обновить отчёты».</div>
        </div>
      </div>

      <div className="summary-grid" style={{ marginBottom: 16 }}>
        <div className="summary-card"><div className="summary-card__label">Записей</div><div className="summary-card__value">{appearance?.total ?? "—"}</div></div>
        <div className="summary-card"><div className="summary-card__label">Персона</div><div className="summary-card__value" style={{ fontSize: "1.1rem" }}>{selectedPerson ? personLabel(selectedPerson) : "Все"}</div></div>
      </div>

      <div className="reports-chart-grid reports-chart-grid--single">
        <ReportBarChart title="Подтверждённые появления по камерам" items={appearanceCameraChart} />
      </div>

      <div style={{ overflowX: "auto" }}>
        <table className="soft-table">
          <thead><tr><th>#</th><th>Время</th><th>Камера</th><th>Локация</th><th>Группа</th><th>Персона</th><th>Уверенность</th></tr></thead>
          <tbody>
            {(appearance?.items ?? []).map((item, index) => (
              <tr key={item.event_id}>
                <td>{index + 1}</td>
                <td>{formatDateTime(item.event_ts)}</td>
                <td>{item.camera_name || `#${item.camera_id}`}</td>
                <td>{item.camera_location || "—"}</td>
                <td>{item.group_name || "—"}</td>
                <td>{item.person_label || (item.person_id ? `ID ${item.person_id}` : "—")}</td>
                <td>{item.confidence != null ? `${Number(item.confidence).toFixed(1)}%` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );

  const renderTabContent = () => {
    switch (activeTab) {
      case "overview":
        return renderOverview();
      case "user-actions":
        return renderUserActions();
      case "groups":
        return renderGroups();
      case "cameras":
        return renderCameras();
      case "processors":
        return renderProcessors();
      case "events":
        return renderEvents();
      case "archive":
        return renderArchive();
      case "security":
        return renderSecurity();
      case "appearances":
        return renderAppearances();
      default:
        return null;
    }
  };

  return (
    <div className="stack">
      <section className="page-hero">
        <div className="page-hero__content">
          <div className="page-hero__eyebrow">Analytics</div>
          <h2 className="title">Отчёты</h2>
          <div className="page-hero__lead">Сводный dashboard по пользователям, камерам, процессорам, архиву и событиям.</div>
        </div>
        <div className="page-actions">
          <button className="btn secondary" onClick={resetFilters} type="button">Сбросить</button>
          <button className="btn" onClick={loadReports} disabled={loading} type="button">
            {loading ? "Обновляем..." : "Обновить отчёты"}
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
        <label className="field">
          <span className="label">Группа камер</span>
          <select className="select" value={selectedGroupId} onChange={(event) => setSelectedGroupId(event.target.value)}>
            <option value="">Все группы</option>
            {groups.map((group) => (
              <option key={group.group_id} value={group.group_id}>{group.name}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="label">Камера</span>
          <select className="select" value={selectedCameraId} onChange={(event) => setSelectedCameraId(event.target.value)}>
            <option value="">Все камеры</option>
            {cameraOptions.map((camera) => (
              <option key={camera.camera_id} value={camera.camera_id}>{camera.name}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="label">Процессор</span>
          <select className="select" value={selectedProcessorId} onChange={(event) => setSelectedProcessorId(event.target.value)}>
            <option value="">Все процессоры</option>
            {processors.map((processor) => (
              <option key={processor.processor_id} value={processor.processor_id}>{processor.name}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="label">Пользователь</span>
          <select className="select" value={selectedUserId} onChange={(event) => setSelectedUserId(event.target.value)}>
            <option value="">Все пользователи</option>
            {users.map((user) => (
              <option key={user.user_id} value={user.user_id}>{userLabel(user)}</option>
            ))}
          </select>
        </label>
      </section>

      {error && <div className="danger">{error}</div>}

      <section className="reports-tabbar">
        {REPORT_TABS.map((tab) => (
          <button
            key={tab.key}
            className={`reports-tab${activeTab === tab.key ? " active" : ""}`}
            onClick={() => setActiveTab(tab.key)}
            type="button"
          >
            {tab.label}
          </button>
        ))}
      </section>

      <section className="panel-card reports-tab-summary">
        <div className="page-hero__eyebrow">Активная подвкладка</div>
        <h3 className="panel-card__title" style={{ margin: 0 }}>{activeTabMeta.label}</h3>
        <div className="panel-card__lead">{activeTabMeta.description}</div>
      </section>

      {renderTabContent()}
    </div>
  );
};

export default ReportsPage;
