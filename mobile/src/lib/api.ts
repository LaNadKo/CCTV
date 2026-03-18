import { getApiUrl as loadApiUrl } from "./storage";

let _apiUrl: string = "http://192.168.50.62";

export async function initApiUrl() {
  const saved = await loadApiUrl();
  if (saved) _apiUrl = saved;
}

export function getApiUrl(): string {
  return _apiUrl;
}

export function setApiUrlSync(url: string) {
  _apiUrl = url.replace(/\/+$/, "");
}

type HTTPMethod = "GET" | "POST" | "PATCH" | "DELETE";

async function request<T>(
  path: string,
  method: HTTPMethod = "GET",
  token?: string | null,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${_apiUrl}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const msg = await res.text();
    const err: any = new Error(msg || res.statusText);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

// ── Auth ──
export async function loginApi(login: string, password: string, totp_code?: string) {
  return request<{ access_token: string; token_type: string; must_change_password: boolean }>(
    "/auth/login", "POST", undefined, { login, password, totp_code },
  );
}
export async function meApi(token: string) {
  return request<{ user_id: number; login: string; role_id: number; face_login_enabled: boolean; must_change_password: boolean }>(
    "/auth/me", "GET", token,
  );
}
export async function changePassword(token: string, current_password: string, new_password: string) {
  return request<{ ok: boolean }>("/auth/change-password", "POST", token, { current_password, new_password });
}

// ── Cameras ──
export async function getCameras(token: string, groupId?: number | null) {
  const qs = groupId ? `?group_id=${groupId}` : "";
  return request<Camera[]>(`/cameras${qs}`, "GET", token);
}
export async function createCamera(token: string, payload: Partial<Camera>) {
  return request<{ camera_id: number }>("/admin/cameras", "POST", token, payload);
}
export async function updateCamera(token: string, id: number, payload: Partial<Camera>) {
  return request<{ camera_id: number }>(`/admin/cameras/${id}`, "PATCH", token, payload);
}

// ── Groups ──
export async function listGroups(token: string) {
  return request<GroupOut[]>("/groups", "GET", token);
}
export async function createGroup(token: string, name: string, description?: string) {
  return request<GroupOut>("/groups", "POST", token, { name, description });
}
export async function getGroup(token: string, groupId: number) {
  return request<GroupDetail>(`/groups/${groupId}`, "GET", token);
}
export async function updateGroup(token: string, groupId: number, payload: { name?: string; description?: string }) {
  return request<GroupOut>(`/groups/${groupId}`, "PATCH", token, payload);
}
export async function deleteGroup(token: string, groupId: number) {
  return request(`/groups/${groupId}`, "DELETE", token);
}
export async function assignCameraToGroup(token: string, groupId: number, cameraId: number) {
  return request(`/groups/${groupId}/cameras/${cameraId}`, "POST", token);
}
export async function unassignCameraFromGroup(token: string, groupId: number, cameraId: number) {
  return request(`/groups/${groupId}/cameras/${cameraId}`, "DELETE", token);
}

// ── Detections ──
export async function getPending(token: string) {
  return request<PendingEvent[]>("/detections/pending", "GET", token);
}
export async function reviewEvent(token: string, eventId: number, status: "approved" | "rejected", person_id?: number) {
  return request(`/detections/events/${eventId}/review`, "POST", token, { status, person_id });
}
export async function getTimeline(token: string, camera_id?: number, date_from?: string, date_to?: string) {
  const params = new URLSearchParams();
  if (camera_id !== undefined) params.append("camera_id", String(camera_id));
  if (date_from) params.append("date_from", date_from);
  if (date_to) params.append("date_to", date_to);
  return request<TimelineEvent[]>(`/detections/timeline?${params}`, "GET", token);
}

// ── Recordings ──
export async function listRecordings(token: string, camera_id?: number) {
  const qs = camera_id ? `?camera_id=${camera_id}` : "";
  return request<Recording[]>(`/recordings${qs}`, "GET", token);
}
export function recordingUrl(recordingId: number, token: string) {
  return `${_apiUrl}/recordings/file/${recordingId}?token=${encodeURIComponent(token)}`;
}
export function snapshotUrl(recordingId: number, token: string, ts?: number) {
  const extra = ts ? `&ts=${ts}` : "";
  return `${_apiUrl}/recordings/snapshot/${recordingId}?token=${encodeURIComponent(token)}${extra}`;
}

// ── Persons ──
export async function listPersons(token: string) {
  return request<PersonOut[]>("/persons", "GET", token);
}
export async function createPerson(token: string, data: { first_name?: string; last_name?: string; middle_name?: string }) {
  return request<PersonOut>("/persons", "POST", token, data);
}
export async function updatePerson(token: string, personId: number, data: { first_name?: string; last_name?: string; middle_name?: string }) {
  return request<PersonOut>(`/persons/${personId}`, "PATCH", token, data);
}
export async function addPersonEmbeddingFromUri(token: string, personId: number, uri: string) {
  const form = new FormData();
  form.append("file", { uri, type: "image/jpeg", name: "photo.jpg" } as any);
  const res = await fetch(`${_apiUrl}/persons/${personId}/embeddings/photo`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ── Processors ──
export async function listProcessors(token: string) {
  return request<ProcessorOut[]>("/processors", "GET", token);
}
export async function generateProcessorCode(token: string) {
  return request<{ code: string; expires_at: string }>("/processors/generate-code", "POST", token);
}
export async function assignCamerasToProcessor(token: string, processorId: number, camera_ids: number[]) {
  return request(`/processors/${processorId}/assign`, "POST", token, { camera_ids });
}
export async function unassignCameraFromProcessor(token: string, processorId: number, cameraId: number) {
  return request(`/processors/${processorId}/assign/${cameraId}`, "DELETE", token);
}
export async function deleteProcessor(token: string, processorId: number) {
  return request(`/processors/${processorId}`, "DELETE", token);
}

// ── API Keys ──
export async function createApiKey(token: string, description: string, scopes: string[]) {
  return request<{ api_key: string; api_key_id: number }>("/api-keys", "POST", token, { description, scopes });
}
export async function listApiKeys(token: string) {
  return request<ApiKeyOut[]>("/api-keys", "GET", token);
}

// ── Reports ──
export async function getAppearanceReport(
  token: string,
  params?: { date_from?: string; date_to?: string; person_id?: number },
) {
  const qs = new URLSearchParams();
  if (params?.date_from) qs.append("date_from", params.date_from);
  if (params?.date_to) qs.append("date_to", params.date_to);
  if (params?.person_id !== undefined) qs.append("person_id", String(params.person_id));
  return request<AppearanceReport>(`/reports/appearances?${qs}`, "GET", token);
}
export function appearanceExportUrl(format: "pdf" | "xlsx" | "docx", params?: { date_from?: string; date_to?: string; person_id?: number }) {
  const qs = new URLSearchParams();
  qs.append("format", format);
  if (params?.date_from) qs.append("date_from", params.date_from);
  if (params?.date_to) qs.append("date_to", params.date_to);
  if (params?.person_id !== undefined) qs.append("person_id", String(params.person_id));
  return `${_apiUrl}/reports/appearances/export?${qs}`;
}

// ── Admin: Users ──
export async function adminListUsers(token: string) {
  return request<UserOut[]>("/admin/users", "GET", token);
}
export async function adminCreateUser(token: string, login: string, password: string, role_id: number) {
  return request<UserOut>("/admin/users", "POST", token, { login, password, role_id });
}
export async function adminDeleteUser(token: string, userId: number) {
  return request(`/admin/users/${userId}`, "DELETE", token);
}
export async function adminSetUserRole(token: string, userId: number, role_id: number) {
  return request(`/admin/users/${userId}/role?role_id=${role_id}`, "POST", token);
}

// ── Stream URLs ──
export function cameraStreamUrl(cameraId: number, token: string) {
  return `${_apiUrl}/cameras/${cameraId}/stream?token=${encodeURIComponent(token)}`;
}

// ── Types ──
export type Camera = {
  camera_id: number; name: string; location?: string; permission: string;
  ip_address?: string; stream_url?: string; detection_enabled: boolean;
  recording_mode: string; group_id?: number | null;
};
export type GroupOut = {
  group_id: number; name: string; description?: string | null;
  created_at: string; camera_count: number;
};
export type GroupCameraOut = { camera_id: number; name: string; location?: string | null };
export type GroupDetail = GroupOut & { cameras: GroupCameraOut[] };
export type PendingEvent = {
  event_id: number; camera_id: number; event_type_id: number; event_ts: string;
  person_id?: number; person_label?: string; recording_file_id?: number;
  confidence?: number | null; snapshot_url?: string | null;
};
export type TimelineEvent = { event_id: number; camera_id: number; event_ts: string; person_id?: number | null; event_type: string };
export type Recording = {
  recording_file_id: number; camera_id: number; video_stream_id: number;
  file_kind: string; file_path: string; started_at: string; ended_at?: string;
  duration_seconds?: number; file_size_bytes?: number;
};
export type PersonOut = {
  person_id: number; first_name: string | null; last_name: string | null;
  middle_name: string | null; embeddings_count: number; created_at: string | null;
};
export type ProcessorOut = {
  processor_id: number; name: string; status: string; last_heartbeat?: string | null;
  capabilities?: Record<string, unknown> | null; ip_address?: string | null;
  os_info?: string | null; version?: string | null; created_at: string;
  camera_count: number; assigned_cameras: { camera_id: number; name: string }[];
};
export type ApiKeyOut = { api_key_id: number; description?: string; scopes: string[]; is_active: boolean };
export type AppearanceItem = {
  event_id: number; event_ts: string; camera_id: number; camera_name?: string | null;
  person_id?: number | null; person_label?: string | null; confidence?: number | null;
};
export type AppearanceReport = {
  date_from?: string | null; date_to?: string | null; person_id?: number | null;
  total: number; items: AppearanceItem[];
};
export type UserOut = {
  user_id: number; login: string; role_id: number;
  face_login_enabled: boolean; must_change_password: boolean;
};
