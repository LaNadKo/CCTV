import { useEffect, useMemo, useState, type MouseEvent } from "react";
import { API_URL, getCameras, getTimeline, listRecordings, recordingSnapshotUrl } from "../lib/api";
import { useAuth } from "../context/AuthContext";

type DbRec = {
  recording_file_id: number;
  camera_id: number;
  video_stream_id: number;
  file_kind: string;
  file_path: string;
  started_at: string;
  ended_at?: string;
  duration_seconds?: number;
  file_size_bytes?: number;
  checksum?: string;
};

type TimelineEvent = {
  event_id: number;
  camera_id: number;
  event_ts: string;
  person_id?: number | null;
  event_type: string;
};

type CameraOption = {
  camera_id: number;
  name: string;
  location?: string;
};

type ViewMode = "overview" | "archive" | "hour";
type EventFilter = "all" | "human" | "recognized" | "unknown" | "motion";

type EventVisual = {
  label: string;
  short: string;
  color: string;
};

const HOURS_ASC = Array.from({ length: 24 }, (_, index) => index);
const HOURS_DESC = [...HOURS_ASC].reverse();
const DAY_SECONDS = 24 * 60 * 60;

const EVENT_META: Record<string, EventVisual> = {
  face_recognized: { label: "Известная персона", short: "✓", color: "#22c55e" },
  face_unknown: { label: "Движущийся человек", short: "🧍", color: "#f97316" },
  motion_detected: { label: "Обнаружено движение", short: "⚡", color: "#fbbf24" },
  person_detected: { label: "Обнаружен человек", short: "👤", color: "#38bdf8" },
};

function toLocalDateKey(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function shiftDate(value: string, deltaDays: number): string {
  const base = new Date(`${value}T12:00:00`);
  base.setDate(base.getDate() + deltaDays);
  return toLocalDateKey(base);
}

function formatDayLabel(value: string): string {
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);

  if (value === toLocalDateKey(today)) return "Сегодня";
  if (value === toLocalDateKey(yesterday)) return "Вчера";

  return new Date(`${value}T00:00:00`).toLocaleDateString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

function formatDuration(value?: number): string {
  if (!value) return "до 1 мин";
  if (value < 60) return `${Math.max(Math.round(value), 1)} с`;
  const minutes = Math.floor(value / 60);
  const seconds = Math.round(value % 60);
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function formatBytes(value?: number): string {
  if (!value) return "-";
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} КБ`;
  if (value < 1024 * 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} МБ`;
  return `${(value / (1024 * 1024 * 1024)).toFixed(2)} ГБ`;
}

function getRecordingStart(record: DbRec): Date {
  return new Date(record.started_at);
}

function getRecordingEnd(record: DbRec): Date {
  if (record.ended_at) {
    return new Date(record.ended_at);
  }
  if (record.duration_seconds) {
    return new Date(getRecordingStart(record).getTime() + record.duration_seconds * 1000);
  }
  return new Date(getRecordingStart(record).getTime() + 60 * 1000);
}

function secondsSinceDayStart(value: Date): number {
  return value.getHours() * 3600 + value.getMinutes() * 60 + value.getSeconds();
}

function formatClipRange(record: DbRec): string {
  const start = getRecordingStart(record);
  const end = getRecordingEnd(record);
  const startLabel = start.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  const endLabel = end.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  return `${startLabel}-${endLabel}`;
}

function getSnapshotTimestamp(record: DbRec): number | undefined {
  if (!record.duration_seconds) return undefined;
  return Math.max(Math.floor(record.duration_seconds / 2), 1);
}

function recordingMjpegUrl(recordingId: number, token: string): string {
  return `${API_URL}/recordings/file/${recordingId}/mjpeg?token=${encodeURIComponent(token)}`;
}

function clampDateToToday(value: string, today: string): string {
  if (!value) return today;
  return value > today ? today : value;
}

function eventMatchesFilter(event: TimelineEvent, filter: EventFilter): boolean {
  if (filter === "all") return true;
  if (filter === "human") return event.event_type === "face_recognized" || event.event_type === "face_unknown" || event.event_type === "person_detected";
  if (filter === "recognized") return event.event_type === "face_recognized";
  if (filter === "unknown") return event.event_type === "face_unknown";
  if (filter === "motion") return event.event_type === "motion_detected";
  return true;
}

function collectEventBadges(events: TimelineEvent[]): EventVisual[] {
  const seen = new Set<string>();
  const badges: EventVisual[] = [];
  for (const event of events) {
    const meta = EVENT_META[event.event_type];
    if (!meta || seen.has(event.event_type)) continue;
    seen.add(event.event_type);
    badges.push(meta);
  }
  return badges;
}

const RecordingsPage: React.FC = () => {
  const { token } = useAuth();
  const [records, setRecords] = useState<DbRec[]>([]);
  const [cameras, setCameras] = useState<CameraOption[]>([]);
  const [cameraId, setCameraId] = useState<number | null>(null);
  const [selectedDate, setSelectedDate] = useState<string>(() => toLocalDateKey(new Date()));
  const [selectedRecordingId, setSelectedRecordingId] = useState<number | null>(null);
  const [selectedHour, setSelectedHour] = useState<number | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("overview");
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [eventFilter, setEventFilter] = useState<EventFilter>("all");
  const [snapshotMissingMap, setSnapshotMissingMap] = useState<Record<number, boolean>>({});
  const [videoFallbackMap, setVideoFallbackMap] = useState<Record<number, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const todayKey = toLocalDateKey(new Date());
  const canMoveForward = selectedDate < todayKey;

  const load = async () => {
    if (!token) return;
    setLoading(true);
    setError(null);

    try {
      const cameraItems = await getCameras(token);
      const mapped = cameraItems.map((camera) => ({
        camera_id: camera.camera_id,
        name: camera.name,
        location: camera.location,
      }));
      setCameras(mapped);

      const activeCameraId = cameraId ?? mapped[0]?.camera_id ?? null;
      if (activeCameraId !== null) {
        setCameraId(activeCameraId);
      }

      const dateFrom = `${selectedDate}T00:00:00`;
      const dateTo = `${selectedDate}T23:59:59`;
      const [recordingItems, timelineItems] = await Promise.all([
        listRecordings(token, activeCameraId ?? undefined, dateFrom, dateTo, 500),
        getTimeline(token, activeCameraId ?? undefined, dateFrom, dateTo),
      ]);

      const sorted = [...recordingItems].sort(
        (left, right) => getRecordingStart(left).getTime() - getRecordingStart(right).getTime()
      );

      setRecords(sorted);
      setTimeline(timelineItems);

      const fallbackRecordingId = sorted.length ? sorted[sorted.length - 1].recording_file_id : null;
      setSelectedRecordingId((current) =>
        current && sorted.some((record) => record.recording_file_id === current) ? current : fallbackRecordingId
      );

      setSelectedHour((current) => {
        if (current !== null && sorted.some((record) => getRecordingStart(record).getHours() === current)) {
          return current;
        }
        return sorted.length ? getRecordingStart(sorted[sorted.length - 1]).getHours() : null;
      });
    } catch (e: any) {
      setError(e?.message || "Не удалось загрузить записи.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [token, cameraId, selectedDate]);

  const activeCamera = useMemo(
    () => cameras.find((camera) => camera.camera_id === cameraId) || null,
    [cameraId, cameras]
  );

  const recordsByHour = useMemo(() => {
    const map: Record<number, DbRec[]> = {};
    for (const hour of HOURS_ASC) {
      map[hour] = [];
    }
    for (const record of records) {
      map[getRecordingStart(record).getHours()].push(record);
    }
    return map;
  }, [records]);

  const recordingEventsMap = useMemo(() => {
    const map: Record<number, TimelineEvent[]> = {};
    for (const record of records) {
      const startMs = getRecordingStart(record).getTime();
      const endMs = getRecordingEnd(record).getTime();
      map[record.recording_file_id] = timeline.filter((event) => {
        const eventMs = new Date(event.event_ts).getTime();
        return eventMs >= startMs && eventMs <= endMs;
      });
    }
    return map;
  }, [records, timeline]);

  const eventsByHour = useMemo(() => {
    const map: Record<number, TimelineEvent[]> = {};
    for (const hour of HOURS_ASC) {
      map[hour] = timeline.filter((event) => new Date(event.event_ts).getHours() === hour);
    }
    return map;
  }, [timeline]);

  const selectedRecording = useMemo(
    () => records.find((record) => record.recording_file_id === selectedRecordingId) || null,
    [records, selectedRecordingId]
  );

  const selectedRecordingUrl = selectedRecording
    ? `${API_URL}/recordings/file/${selectedRecording.recording_file_id}?token=${encodeURIComponent(token || "")}`
    : null;

  const selectedRecordingSnapshotUrl = selectedRecording
    ? recordingSnapshotUrl(selectedRecording.recording_file_id, token || "", getSnapshotTimestamp(selectedRecording))
    : null;
  const selectedRecordingMjpegUrl =
    selectedRecording && token ? recordingMjpegUrl(selectedRecording.recording_file_id, token) : null;

  const selectedRecordingEvents = selectedRecording ? recordingEventsMap[selectedRecording.recording_file_id] || [] : [];

  const summaryChips = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const event of timeline) {
      counts[event.event_type] = (counts[event.event_type] || 0) + 1;
    }
    return Object.entries(counts)
      .map(([eventType, count]) => {
        const meta = EVENT_META[eventType];
        if (!meta) return null;
        return { ...meta, count };
      })
      .filter((item): item is EventVisual & { count: number } => item !== null)
      .sort((left, right) => right.count - left.count);
  }, [timeline]);

  const daySegments = useMemo(() => {
    return records.map((record) => {
      const start = secondsSinceDayStart(getRecordingStart(record));
      const end = secondsSinceDayStart(getRecordingEnd(record));
      const widthSeconds = Math.max(end - start, Math.max(record.duration_seconds || 60, 30));
      const left = (start / DAY_SECONDS) * 100;
      const width = Math.max((widthSeconds / DAY_SECONDS) * 100, 0.45);
      const right = Math.min(left + width, 100);
      return {
        recordingId: record.recording_file_id,
        hour: getRecordingStart(record).getHours(),
        left,
        width: right - left,
        right,
        center: left + (right - left) / 2,
      };
    });
  }, [records]);

  const timelineMarks = useMemo(() => {
    return timeline.map((event) => {
      const seconds = secondsSinceDayStart(new Date(event.event_ts));
      const meta = EVENT_META[event.event_type];
      return {
        eventId: event.event_id,
        left: (seconds / DAY_SECONDS) * 100,
        color: meta?.color || "#38bdf8",
      };
    });
  }, [timeline]);

  const hourRecords = useMemo(() => {
    if (selectedHour === null) return [];
    return recordsByHour[selectedHour] || [];
  }, [recordsByHour, selectedHour]);

  const filteredHourRecords = useMemo(() => {
    if (eventFilter === "all") return hourRecords;
    return hourRecords.filter((record) => {
      const events = recordingEventsMap[record.recording_file_id] || [];
      return events.some((event) => eventMatchesFilter(event, eventFilter));
    });
  }, [eventFilter, hourRecords, recordingEventsMap]);

  const overviewSelectedHour = selectedRecording ? getRecordingStart(selectedRecording).getHours() : selectedHour;

  const openArchive = () => {
    setViewMode("archive");
  };

  const openHour = (hour: number) => {
    setSelectedHour(hour);
    const items = recordsByHour[hour] || [];
    if (items.length) {
      setSelectedRecordingId(items[0].recording_file_id);
    }
    setViewMode("hour");
  };

  const handleTimelineClick = (event: MouseEvent<HTMLDivElement>) => {
    if (!daySegments.length) return;

    const bounds = event.currentTarget.getBoundingClientRect();
    if (!bounds.width) return;

    const percent = ((event.clientX - bounds.left) / bounds.width) * 100;
    const matchedSegments = daySegments
      .filter((segment) => percent >= segment.left && percent <= segment.right)
      .sort((left, right) => Math.abs(left.center - percent) - Math.abs(right.center - percent));

    const target = matchedSegments[0];
    if (!target) return;

    setSelectedRecordingId(target.recordingId);
    setSelectedHour(target.hour);
  };

  const renderEmptyState = (
    <div className="card recordings-empty-state">
      <h3 style={{ margin: 0 }}>Записей за выбранный день пока нет</h3>
      <div className="muted">
        Проверьте, что камера назначена на Processor, у неё включена запись и выбран правильный день архива.
      </div>
    </div>
  );

  return (
    <div className="stack recordings-page" style={{ marginTop: 18 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-end" }}>
        <div className="stack" style={{ gap: 4 }}>
          <h2 className="title">Записи</h2>
          <div className="muted">Архив хранится на Processor и подтягивается через backend-прокси.</div>
        </div>
          <div className="row recordings-toolbar">
          <select
            className="input"
            value={cameraId ?? ""}
            onChange={(e) => setCameraId(e.target.value ? Number(e.target.value) : null)}
            style={{ minWidth: 220 }}
          >
            {cameras.map((camera) => (
              <option key={camera.camera_id} value={camera.camera_id}>
                {camera.name} (#{camera.camera_id})
              </option>
            ))}
          </select>
          <div className="recordings-date-switcher">
            <button className="btn secondary" onClick={() => setSelectedDate((current) => shiftDate(current, -1))}>
              ←
            </button>
            <input
              type="date"
              className="input"
              max={todayKey}
              value={selectedDate}
              onChange={(e) => setSelectedDate(clampDateToToday(e.target.value, todayKey))}
            />
            <button
              className="btn secondary"
              onClick={() => setSelectedDate((current) => clampDateToToday(shiftDate(current, 1), todayKey))}
              disabled={!canMoveForward}
            >
              →
            </button>
          </div>
          <button className="btn secondary" onClick={load}>
            Обновить
          </button>
        </div>
      </div>

      {error && <div className="danger">{error}</div>}
      {loading && <div className="card">Загрузка...</div>}

      {!loading && records.length === 0 && renderEmptyState}

      {!loading && records.length > 0 && viewMode === "overview" && selectedRecording && (
        <>
          <div className="card recordings-overview-card stack">
            <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
              <div className="stack" style={{ gap: 4 }}>
                <h3 style={{ margin: 0 }}>{activeCamera?.name || "Камера"}</h3>
                <div className="muted">
                  {formatDayLabel(selectedDate)} · {activeCamera?.location || "Локация не указана"}
                </div>
              </div>
              <button className="btn" onClick={openArchive}>
                Воспроизведение всех видео
              </button>
            </div>

            {videoFallbackMap[selectedRecording.recording_file_id] ? (
              <img
                key={`mjpeg-${selectedRecording.recording_file_id}`}
                className="recordings-hero-video"
                src={selectedRecordingMjpegUrl || undefined}
                alt={`recording-${selectedRecording.recording_file_id}`}
              />
            ) : (
              <video
                key={selectedRecording.recording_file_id}
                className="recordings-hero-video"
                src={selectedRecordingUrl || undefined}
                controls
                preload="metadata"
                playsInline
                onLoadedData={() =>
                  setVideoFallbackMap((prev) =>
                    prev[selectedRecording.recording_file_id]
                      ? { ...prev, [selectedRecording.recording_file_id]: false }
                      : prev
                  )
                }
                onError={() =>
                  setVideoFallbackMap((prev) => ({
                    ...prev,
                    [selectedRecording.recording_file_id]: true,
                  }))
                }
              />
            )}

            <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
              <div className="stack" style={{ gap: 2 }}>
                <div className="recordings-hero-time">{formatClipRange(selectedRecording)}</div>
                <div className="muted">
                  {formatDuration(selectedRecording.duration_seconds)} · {formatBytes(selectedRecording.file_size_bytes)}
                </div>
              </div>
              <div className="row" style={{ gap: 8 }}>
                <button
                  className="btn secondary"
                  onClick={() => {
                    const index = records.findIndex((record) => record.recording_file_id === selectedRecording.recording_file_id);
                    if (index > 0) setSelectedRecordingId(records[index - 1].recording_file_id);
                  }}
                  disabled={records[0]?.recording_file_id === selectedRecording.recording_file_id}
                >
                  Предыдущий
                </button>
                <button
                  className="btn secondary"
                  onClick={() => {
                    const index = records.findIndex((record) => record.recording_file_id === selectedRecording.recording_file_id);
                    if (index >= 0 && index < records.length - 1) setSelectedRecordingId(records[index + 1].recording_file_id);
                  }}
                  disabled={records[records.length - 1]?.recording_file_id === selectedRecording.recording_file_id}
                >
                  Следующий
                </button>
              </div>
            </div>

            <div className="recordings-strip">
              <div className="recordings-strip-track" onClick={handleTimelineClick} role="presentation">
                {daySegments.map((segment) => (
                  <button
                    key={segment.recordingId}
                    type="button"
                    className={
                      segment.recordingId === selectedRecording.recording_file_id
                        ? "recordings-strip-segment active"
                        : "recordings-strip-segment"
                    }
                    style={{ left: `${segment.left}%`, width: `${segment.width}%` }}
                    onClick={(event) => {
                      event.stopPropagation();
                      setSelectedRecordingId(segment.recordingId);
                      setSelectedHour(segment.hour);
                    }}
                    title={`Клип #${segment.recordingId}`}
                  />
                ))}
                {timelineMarks.map((mark) => (
                  <span
                    key={mark.eventId}
                    className="recordings-strip-mark"
                    style={{ left: `${mark.left}%`, background: mark.color }}
                  />
                ))}
              </div>
              <div className="recordings-strip-scale">
                <span>00:00</span>
                <span>06:00</span>
                <span>12:00</span>
                <span>18:00</span>
                <span>24:00</span>
              </div>
              <div className="recordings-strip-hours">
                {HOURS_ASC.map((hour) => {
                  const count = recordsByHour[hour]?.length || 0;
                  const isActive = overviewSelectedHour === hour;
                  return (
                    <button
                      key={hour}
                      type="button"
                      className={`recordings-strip-hour${count ? " has-records" : ""}${isActive ? " active" : ""}`}
                      onClick={() => count && openHour(hour)}
                      disabled={!count}
                      title={count ? `${count} клипов в ${String(hour).padStart(2, "0")}:00` : "Нет записей"}
                    >
                      <span>{String(hour).padStart(2, "0")}</span>
                      <strong>{count || "·"}</strong>
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="recordings-chip-row">
              {summaryChips.map((chip) => (
                <span
                  key={chip.label}
                  className="recordings-chip"
                  style={{ background: `${chip.color}22`, borderColor: `${chip.color}55` }}
                >
                  <span className="recordings-chip-icon">{chip.short}</span>
                  <span>{chip.label}</span>
                  <strong>{chip.count}</strong>
                </span>
              ))}
            </div>

            {selectedRecordingEvents.length > 0 && (
              <div className="recordings-chip-row">
                {collectEventBadges(selectedRecordingEvents).map((badge) => (
                  <span
                    key={badge.label}
                    className="recordings-chip"
                    style={{ background: `${badge.color}18`, borderColor: `${badge.color}40` }}
                  >
                    <span className="recordings-chip-icon">{badge.short}</span>
                    <span>{badge.label}</span>
                  </span>
                ))}
              </div>
            )}
          </div>
        </>
      )}

      {!loading && records.length > 0 && viewMode === "archive" && (
        <div className="card stack">
          <div className="recordings-breadcrumbs">
            <button className="btn secondary" onClick={() => setViewMode("overview")}>
              ← Назад к ленте дня
            </button>
            <span className="muted">{formatDayLabel(selectedDate)}</span>
          </div>

          <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
            <div className="stack" style={{ gap: 4 }}>
              <h3 style={{ margin: 0 }}>Все видео</h3>
              <div className="muted">
                {activeCamera?.name || "Камера"} · {records.length} клипов за день
              </div>
            </div>
            <span className="pill">{formatDayLabel(selectedDate)}</span>
          </div>

          <div className="recordings-archive-grid">
            {HOURS_DESC.map((hour) => {
              const hourItems = recordsByHour[hour] || [];
              const preview = hourItems.length ? hourItems[hourItems.length - 1] : null;
              const hourEvents = eventsByHour[hour] || [];
              const badges = collectEventBadges(hourEvents);

              return (
                <button
                  key={hour}
                  type="button"
                  className={`recordings-hour-folder${preview ? " has-content" : ""}`}
                  onClick={() => preview && openHour(hour)}
                  disabled={!preview}
                >
                  {preview ? (
                    <img
                      src={recordingSnapshotUrl(preview.recording_file_id, token || "", getSnapshotTimestamp(preview))}
                      alt={`hour-${hour}`}
                      className="recordings-hour-thumb"
                      loading="lazy"
                      onError={() =>
                        setSnapshotMissingMap((prev) => ({
                          ...prev,
                          [preview.recording_file_id]: true,
                        }))
                      }
                    />
                  ) : (
                    <div className="recordings-hour-thumb recordings-hour-thumb-empty">Нет записей</div>
                  )}

                  <div className="recordings-hour-footer">
                    <div className="recordings-hour-title">{String(hour).padStart(2, "0")}:00</div>
                    <div className="muted">{preview ? `${hourItems.length} клипов` : "Пусто"}</div>
                  </div>

                  {badges.length > 0 && (
                    <div className="recordings-marker-row">
                      {badges.map((badge) => (
                        <span key={badge.label} className="recordings-marker-badge" style={{ color: badge.color }}>
                          {badge.short} {badge.label}
                        </span>
                      ))}
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {!loading && records.length > 0 && viewMode === "hour" && selectedHour !== null && (
        <div className="stack">
          <div className="card stack">
            <div className="recordings-breadcrumbs">
              <button className="btn secondary" onClick={() => setViewMode("archive")}>
                ← Назад к часам
              </button>
              <span className="muted">
                {formatDayLabel(selectedDate)} · {String(selectedHour).padStart(2, "0")}:00
              </span>
            </div>

            <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
              <div className="stack" style={{ gap: 4 }}>
                <h3 style={{ margin: 0 }}>
                  {new Date(`${selectedDate}T${String(selectedHour).padStart(2, "0")}:00:00`).toLocaleDateString("ru-RU")}{" "}
                  {String(selectedHour).padStart(2, "0")}:00
                </h3>
                <div className="muted">Поминутные клипы за выбранный час.</div>
              </div>
              <select
                className="input"
                value={eventFilter}
                onChange={(e) => setEventFilter(e.target.value as EventFilter)}
                style={{ minWidth: 220 }}
              >
                <option value="all">Все события</option>
                <option value="human">Любой человек</option>
                <option value="recognized">Известная персона</option>
                <option value="unknown">Неизвестное лицо</option>
                <option value="motion">Движение</option>
              </select>
            </div>

            {selectedRecording && (
              <div className="recordings-hour-preview">
                <div className="recordings-hour-preview-media">
                  {snapshotMissingMap[selectedRecording.recording_file_id] && selectedRecordingSnapshotUrl ? (
                    <div className="recordings-thumb recordings-thumb-empty">Превью недоступно</div>
                  ) : (
                    videoFallbackMap[selectedRecording.recording_file_id] ? (
                      <img
                        key={`mjpeg-${selectedRecording.recording_file_id}`}
                        className="recordings-hero-video"
                        src={selectedRecordingMjpegUrl || undefined}
                        alt={`recording-${selectedRecording.recording_file_id}`}
                      />
                    ) : (
                      <video
                        key={selectedRecording.recording_file_id}
                        className="recordings-hero-video"
                        src={selectedRecordingUrl || undefined}
                        controls
                        preload="metadata"
                        playsInline
                        poster={selectedRecordingSnapshotUrl || undefined}
                        onLoadedData={() =>
                          setVideoFallbackMap((prev) =>
                            prev[selectedRecording.recording_file_id]
                              ? { ...prev, [selectedRecording.recording_file_id]: false }
                              : prev
                          )
                        }
                        onError={() =>
                          setVideoFallbackMap((prev) => ({
                            ...prev,
                            [selectedRecording.recording_file_id]: true,
                          }))
                        }
                      />
                    )
                  )}
                </div>
                <div className="stack" style={{ gap: 8 }}>
                  <div style={{ fontWeight: 700 }}>{formatClipRange(selectedRecording)}</div>
                  <div className="muted">
                    {formatDuration(selectedRecording.duration_seconds)} · {formatBytes(selectedRecording.file_size_bytes)}
                  </div>
                  <div className="recordings-marker-row">
                    {collectEventBadges(selectedRecordingEvents).map((badge) => (
                      <span key={badge.label} className="recordings-marker-badge" style={{ color: badge.color }}>
                        {badge.short} {badge.label}
                      </span>
                    ))}
                  </div>
                  <a className="btn secondary" href={selectedRecordingUrl || undefined} target="_blank" rel="noreferrer">
                    Оригинальный файл
                  </a>
                </div>
              </div>
            )}
          </div>

          <div className="card stack">
            <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
              <h3 style={{ margin: 0 }}>Клипы</h3>
              <span className="pill">{filteredHourRecords.length}</span>
            </div>

            {filteredHourRecords.length === 0 ? (
              <div className="muted">Клипов под выбранный фильтр нет.</div>
            ) : (
              <div className="recordings-minute-grid">
                {filteredHourRecords.map((record) => {
                  const recordEvents = recordingEventsMap[record.recording_file_id] || [];
                  const badges = collectEventBadges(recordEvents);
                  const isActive = selectedRecordingId === record.recording_file_id;
                  const thumbMissing = snapshotMissingMap[record.recording_file_id];

                  return (
                    <button
                      key={record.recording_file_id}
                      type="button"
                      className={`recordings-minute-card${isActive ? " active" : ""}`}
                      onClick={() => setSelectedRecordingId(record.recording_file_id)}
                    >
                      {thumbMissing ? (
                        <div className="recordings-thumb recordings-thumb-empty">Нет превью</div>
                      ) : (
                        <img
                          src={recordingSnapshotUrl(record.recording_file_id, token || "", getSnapshotTimestamp(record))}
                          alt={`record-${record.recording_file_id}`}
                          className="recordings-thumb"
                          loading="lazy"
                          onError={() =>
                            setSnapshotMissingMap((prev) => ({
                              ...prev,
                              [record.recording_file_id]: true,
                            }))
                          }
                        />
                      )}

                      <div className="recordings-minute-time">{formatClipRange(record)}</div>

                      {badges.length > 0 ? (
                        <div className="recordings-marker-row">
                          {badges.map((badge) => (
                            <span key={badge.label} className="recordings-marker-badge" style={{ color: badge.color }}>
                              {badge.short} {badge.label}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <div className="muted">Без событий</div>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default RecordingsPage;
