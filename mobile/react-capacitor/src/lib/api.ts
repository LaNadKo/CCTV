const envApi = import.meta.env.VITE_API_URL as string | undefined;
const runtimeOrigin = typeof window !== "undefined" ? window.location.origin : "";
const savedUrl = typeof window !== "undefined" ? localStorage.getItem("cctv_api_url") : null;
const electronDefaultApi =
  typeof window !== "undefined" ? (window as any)?.electronAPI?.defaultApiUrl as string | undefined : undefined;
export const API_URL =
  savedUrl ||
  envApi ||
  electronDefaultApi ||
  (import.meta.env.DEV ? "http://127.0.0.1:8000" : runtimeOrigin || "http://127.0.0.1:8000");

export function setApiUrl(url: string) {
  localStorage.setItem("cctv_api_url", url.replace(/\/+$/, ""));
  window.location.reload();
}

export function getApiUrl(): string {
  return API_URL;
}

export function clearApiUrl() {
  localStorage.removeItem("cctv_api_url");
  window.location.reload();
}

type HTTPMethod = "GET" | "POST" | "PATCH" | "DELETE";

async function parseResponse<T>(res: Response): Promise<T> {
  if (res.status === 204 || res.status === 205) {
    return undefined as T;
  }

  const text = await res.text();
  if (!text.trim()) {
    return undefined as T;
  }

  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return JSON.parse(text) as T;
  }

  return text as T;
}

async function readErrorMessage(res: Response): Promise<string> {
  const text = await res.text();
  if (!text.trim()) {
    return res.statusText || "Request failed";
  }
  try {
    const parsed = JSON.parse(text);
    if (typeof parsed?.detail === "string" && parsed.detail.trim()) {
      return parsed.detail;
    }
  } catch {
    // ignore invalid JSON and return raw text below
  }
  return text;
}

async function request<T>(
  path: string,
  method: HTTPMethod = "GET",
  token?: string | null,
  body?: any
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (error: any) {
    const message = error?.message || "Network request failed";
    throw new Error(`Не удалось связаться с backend (${API_URL}): ${message}`);
  }
  if (!res.ok) {
    const msg = await readErrorMessage(res);
    const err: any = new Error(msg || res.statusText);
    err.status = res.status;
    throw err;
  }
  return parseResponse<T>(res);
}

export async function loginApi(login: string, password: string, totp_code?: string) {
  return request<{ access_token: string; token_type: string; must_change_password: boolean }>(
    "/auth/login",
    "POST",
    undefined,
    { login, password, totp_code }
  );
}

export type CurrentUser = {
  user_id: number;
  login: string;
  role_id: number;
  first_name: string | null;
  last_name: string | null;
  middle_name: string | null;
  face_login_enabled: boolean;
  must_change_password: boolean;
  totp_enabled: boolean;
};

export async function me(token: string) {
  return request<CurrentUser>("/auth/me", "GET", token);
}

export async function changePassword(token: string, current_password: string, new_password: string) {
  return request<{ ok: boolean }>("/auth/change-password", "POST", token, { current_password, new_password });
}

export async function updateProfile(
  token: string,
  payload: { first_name?: string | null; last_name?: string | null; middle_name?: string | null }
) {
  return request<CurrentUser>("/auth/profile", "PATCH", token, payload);
}

export async function getTotpStatus(token: string) {
  return request<{ enabled: boolean }>("/auth/totp/status", "GET", token);
}

export async function setupTotp(token: string) {
  return request<{ secret: string; provisioning_uri: string }>("/auth/totp/setup", "POST", token);
}

export async function activateTotp(token: string, code: string) {
  return request<{ enabled: boolean }>("/auth/totp/activate", "POST", token, { code });
}

export async function disableTotp(token: string) {
  return request<{ enabled: boolean }>("/auth/totp/disable", "POST", token);
}

export type CameraEndpointInfo = {
  camera_endpoint_id?: number | null;
  endpoint_kind: "onvif" | "rtsp" | "http";
  endpoint_url: string;
  username?: string | null;
  has_password?: boolean;
  is_primary?: boolean;
};

export type CameraPtzCapabilities = {
  pan_tilt: boolean;
  zoom: boolean;
  home: boolean;
  presets: boolean;
};

export type CameraSummary = {
  camera_id: number;
  name: string;
  location?: string;
  permission: string;
  ip_address?: string;
  stream_url?: string;
  detection_enabled: boolean;
  recording_mode: string;
  tracking_enabled?: boolean;
  tracking_mode?: string;
  tracking_target_person_id?: number | null;
  group_id?: number | null;
  connection_kind: "manual" | "onvif" | "rtsp" | "http";
  onvif_enabled: boolean;
  supports_ptz: boolean;
  ptz_capabilities: CameraPtzCapabilities;
  endpoint_kinds: string[];
  endpoints: CameraEndpointInfo[];
};

export type CameraDetail = CameraSummary & {
  onvif_profile_token?: string | null;
  device_metadata?: Record<string, unknown> | null;
  presets: {
    camera_preset_id: number;
    camera_id: number;
    name: string;
    preset_token?: string | null;
    order_index: number;
    dwell_seconds: number;
  }[];
  roi_zones: {
    roi_zone_id: number;
    camera_id: number;
    name: string;
    zone_type: string;
    polygon_points?: string | null;
  }[];
};

export type CameraDiscoveryDevice = {
  host?: string | null;
  port?: number | null;
  use_https: boolean;
  xaddrs: string[];
  types: string[];
  scopes: string[];
  name?: string | null;
};

export type CameraProbeResult = {
  name?: string | null;
  ip_address?: string | null;
  connection_kind: "manual" | "onvif" | "rtsp" | "http";
  protocols: string[];
  supports_ptz: boolean;
  ptz_capabilities?: CameraPtzCapabilities | null;
  onvif_profile_token?: string | null;
  endpoints: CameraEndpointInfo[];
  device_metadata?: Record<string, unknown> | null;
  presets: { name: string; preset_token?: string | null }[];
  warnings: string[];
};

export async function getCameras(token: string, groupId?: number | null) {
  const qs = groupId ? `?group_id=${groupId}` : "";
  return request<CameraSummary[]>(`/cameras${qs}`, "GET", token);
}

export async function getPending(token: string) {
  return request<
    {
      event_id: number;
      camera_id: number;
      camera_name?: string | null;
      camera_location?: string | null;
      event_type_id: number;
      event_ts: string;
      person_id?: number;
      person_label?: string;
      recording_file_id?: number;
      confidence?: number | null;
      snapshot_url?: string | null;
    }[]
  >("/detections/pending", "GET", token);
}

export async function reviewEvent(token: string, eventId: number, status: "approved" | "rejected", person_id?: number) {
  return request(`/detections/events/${eventId}/review`, "POST", token, { status, person_id });
}

export async function createApiKey(token: string, description: string, scopes: string[]) {
  return request<{ api_key: string; api_key_id: number }>("/api-keys", "POST", token, { description, scopes });
}

export async function listApiKeys(token: string) {
  return request<{ api_key_id: number; description?: string; scopes: string[]; is_active: boolean; expires_at?: string | null; created_at?: string | null }[]>(
    "/api-keys",
    "GET",
    token
  );
}

export async function updateApiKey(
  token: string,
  api_key_id: number,
  payload: { description?: string; scopes?: string[]; is_active?: boolean; expires_at?: string | null }
) {
  return request(`/api-keys/${api_key_id}`, "PATCH", token, payload);
}

export async function deleteApiKey(token: string, api_key_id: number) {
  return request(`/api-keys/${api_key_id}`, "DELETE", token);
}

// ── Groups (simplified) ──

export type GroupOut = {
  group_id: number;
  name: string;
  description?: string | null;
  created_at: string;
  camera_count: number;
};

export type GroupCameraOut = {
  camera_id: number;
  name: string;
  location?: string | null;
};

export type GroupDetail = GroupOut & {
  cameras: GroupCameraOut[];
};

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

export async function createDetectionWithApiKey(
  apiKey: string,
  payload: { camera_id: number; person_id?: number; recording_file_id?: number; confidence?: number }
) {
  const headers: Record<string, string> = { "Content-Type": "application/json", "X-Api-Key": apiKey };
  const res = await fetch(`${API_URL}/detections`, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getAdminCamera(token: string, camera_id: number) {
  return request<CameraDetail>(`/admin/cameras/${camera_id}`, "GET", token);
}

export async function scanCameraDiscovery(token: string, payload: { timeout?: number; interface?: string | null }) {
  return request<CameraDiscoveryDevice[]>("/admin/cameras/discovery/scan", "POST", token, payload);
}

export async function probeCameraDiscovery(
  token: string,
  payload: { host: string; username?: string; password?: string; port?: number | null; use_https?: boolean | null; timeout?: number }
) {
  return request<CameraProbeResult>("/admin/cameras/discovery/probe", "POST", token, payload);
}

export async function createCamera(
  token: string,
  payload: {
    name: string;
    ip_address?: string;
    stream_url?: string;
    status_id?: number;
    location?: string;
    detection_enabled?: boolean;
    recording_mode?: "continuous" | "event";
    connection_kind?: "manual" | "onvif" | "rtsp" | "http";
    supports_ptz?: boolean;
    onvif_profile_token?: string | null;
    device_metadata?: Record<string, unknown> | null;
    endpoints?: {
      endpoint_kind: "onvif" | "rtsp" | "http";
      endpoint_url: string;
      username?: string | null;
      password_secret?: string | null;
      is_primary?: boolean;
    }[];
  }
) {
  return request<{ camera_id: number }>("/admin/cameras", "POST", token, payload);
}

export async function updateCamera(
  token: string,
  camera_id: number,
  payload: Partial<{
    name: string;
    ip_address?: string;
    stream_url?: string;
    status_id?: number;
    location?: string;
    detection_enabled?: boolean;
    recording_mode?: "continuous" | "event";
    tracking_enabled?: boolean;
    tracking_mode?: "off" | "auto" | "patrol";
    tracking_target_person_id?: number | null;
    connection_kind?: "manual" | "onvif" | "rtsp" | "http";
    supports_ptz?: boolean;
    onvif_profile_token?: string | null;
    device_metadata?: Record<string, unknown> | null;
    endpoints?: {
      endpoint_kind: "onvif" | "rtsp" | "http";
      endpoint_url: string;
      username?: string | null;
      password_secret?: string | null;
      is_primary?: boolean;
    }[];
  }>
) {
  return request<{ camera_id: number }>(`/admin/cameras/${camera_id}`, "PATCH", token, payload);
}

export async function refreshOnvifCamera(token: string, camera_id: number) {
  return request<CameraDetail>(`/admin/cameras/${camera_id}/onvif/refresh`, "POST", token);
}

export async function refreshCameraPresets(token: string, camera_id: number) {
  return request<CameraDetail["presets"]>(`/admin/cameras/${camera_id}/presets/refresh`, "POST", token);
}

export async function createCameraPreset(
  token: string,
  camera_id: number,
  payload: { name: string; preset_token?: string | null; order_index?: number; dwell_seconds?: number }
) {
  return request<CameraDetail["presets"][number]>(`/admin/cameras/${camera_id}/presets`, "POST", token, payload);
}

export async function gotoCameraPreset(token: string, camera_id: number, preset_id: number) {
  return request<{ ok: boolean }>(`/admin/cameras/${camera_id}/presets/${preset_id}/goto`, "POST", token);
}

export async function deleteCameraPreset(token: string, camera_id: number, preset_id: number) {
  return request<void>(`/admin/cameras/${camera_id}/presets/${preset_id}`, "DELETE", token);
}

export async function ptzRelative(
  token: string,
  camera_id: number,
  payload: { pan?: number; tilt?: number; zoom?: number; speed?: number | null }
) {
  return request<{ ok: boolean }>(`/admin/cameras/${camera_id}/onvif/ptz/relative`, "POST", token, payload);
}

export async function ptzContinuous(
  token: string,
  camera_id: number,
  payload: { pan?: number; tilt?: number; zoom?: number; timeout_seconds?: number | null }
) {
  return request<{ ok: boolean }>(`/admin/cameras/${camera_id}/onvif/ptz/continuous`, "POST", token, payload);
}

export async function ptzAbsolute(
  token: string,
  camera_id: number,
  payload: { pan?: number | null; tilt?: number | null; zoom?: number | null; speed?: number | null }
) {
  return request<{ ok: boolean }>(`/admin/cameras/${camera_id}/onvif/ptz/absolute`, "POST", token, payload);
}

export async function ptzHome(token: string, camera_id: number) {
  return request<{ ok: boolean }>(`/admin/cameras/${camera_id}/onvif/ptz/home`, "POST", token);
}

export async function ptzStop(token: string, camera_id: number) {
  return request<{ ok: boolean }>(`/admin/cameras/${camera_id}/onvif/ptz/stop`, "POST", token);
}

export async function listRecordings(
  token: string,
  camera_id?: number,
  date_from?: string,
  date_to?: string,
  limit?: number
) {
  const params = new URLSearchParams();
  if (camera_id) params.append("camera_id", String(camera_id));
  if (date_from) params.append("date_from", date_from);
  if (date_to) params.append("date_to", date_to);
  if (limit) params.append("limit", String(limit));
  const search = params.toString();
  return request<
    {
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
    }[]
  >(`/recordings${search ? `?${search}` : ""}`, "GET", token);
}

// ── Persons ──

export interface PersonOut {
  person_id: number;
  first_name: string | null;
  last_name: string | null;
  middle_name: string | null;
  embeddings_count: number;
  created_at: string | null;
}

export async function listPersons(token: string) {
  return request<PersonOut[]>("/persons", "GET", token);
}

export async function createPerson(token: string, data: { first_name?: string; last_name?: string; middle_name?: string }) {
  return request<PersonOut>("/persons", "POST", token, data);
}

export async function updatePerson(token: string, personId: number, data: { first_name?: string; last_name?: string; middle_name?: string }) {
  return request<PersonOut>(`/persons/${personId}`, "PATCH", token, data);
}

export async function deletePerson(token: string, personId: number) {
  return request(`/persons/${personId}`, "DELETE", token);
}

export async function addPersonEmbeddingFromPhoto(
  token: string,
  personId: number,
  file: File,
  cameraId?: number | null
) {
  const form = new FormData();
  form.append("file", file);
  if (cameraId) {
    form.append("camera_id", String(cameraId));
  }
  const res = await fetch(`${API_URL}/persons/${personId}/embeddings/photo`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  if (!res.ok) {
    const msg = await readErrorMessage(res);
    throw new Error(msg || res.statusText);
  }
  return res.json() as Promise<{ person_id: number; embedding_len: number; status: string; max_similarity: number | null }>;
}

export async function enrollPersonFromPhoto(
  token: string,
  file: File,
  first_name?: string,
  last_name?: string,
  middle_name?: string
) {
  const form = new FormData();
  form.append("file", file);
  if (first_name) form.append("first_name", first_name);
  if (last_name) form.append("last_name", last_name);
  if (middle_name) form.append("middle_name", middle_name);
  const res = await fetch(`${API_URL}/auth/face/enroll-person-photo`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    body: form,
  });
  if (!res.ok) {
    const msg = await res.text();
    throw new Error(msg || res.statusText);
  }
  return res.json();
}

export async function getTimeline(
  token: string,
  camera_id?: number,
  date_from?: string,
  date_to?: string
) {
  const params = new URLSearchParams();
  if (camera_id !== undefined) params.append("camera_id", String(camera_id));
  if (date_from) params.append("date_from", date_from);
  if (date_to) params.append("date_to", date_to);
  return request<
    { event_id: number; camera_id: number; event_ts: string; person_id?: number | null; event_type: string }[]
  >(`/detections/timeline?${params.toString()}`, "GET", token);
}

export function recordingSnapshotUrl(recording_id: number, token: string, ts?: number) {
  const search = ts ? `&ts=${ts}` : "";
  return `${API_URL}/recordings/snapshot/${recording_id}?token=${encodeURIComponent(token)}${search}`;
}

export async function enrollPersonFromRecording(
  token: string,
  payload: { recording_id: number; ts?: number; first_name?: string; last_name?: string; middle_name?: string }
) {
  const form = new FormData();
  form.append("recording_id", String(payload.recording_id));
  if (payload.ts !== undefined) form.append("ts", String(payload.ts));
  if (payload.first_name) form.append("first_name", payload.first_name);
  if (payload.last_name) form.append("last_name", payload.last_name);
  if (payload.middle_name) form.append("middle_name", payload.middle_name);
  const res = await fetch(`${API_URL}/auth/face/enroll-from-recording`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    body: form,
  });
  if (!res.ok) {
    const msg = await res.text();
    throw new Error(msg || res.statusText);
  }
  return res.json();
}

export async function enrollPersonFromSnapshot(
  token: string,
  payload: { event_id: number; first_name?: string; last_name?: string; middle_name?: string }
) {
  const form = new FormData();
  form.append("event_id", String(payload.event_id));
  if (payload.first_name) form.append("first_name", payload.first_name);
  if (payload.last_name) form.append("last_name", payload.last_name);
  if (payload.middle_name) form.append("middle_name", payload.middle_name);
  const res = await fetch(`${API_URL}/auth/face/enroll-from-snapshot`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    body: form,
  });
  if (!res.ok) {
    const msg = await res.text();
    throw new Error(msg || res.statusText);
  }
  return res.json();
}

// ── Processors ──

export type AssignedCameraInfo = {
  camera_id: number;
  name: string;
};

export type SystemMetrics = {
  cpu_percent?: number;
  ram_total_gb?: number;
  ram_used_gb?: number;
  ram_percent?: number;
  gpu_name?: string;
  gpu_util_percent?: number;
  gpu_mem_used_mb?: number;
  gpu_mem_total_mb?: number;
  gpu_temp_c?: number;
  net_sent_mbps?: number;
  net_recv_mbps?: number;
  disk_used_gb?: number;
  disk_total_gb?: number;
  active_cameras?: number;
  uptime_seconds?: number;
};

export type ProcessorOut = {
  processor_id: number;
  name: string;
  status: string;
  last_heartbeat?: string | null;
  capabilities?: Record<string, unknown> | null;
  ip_address?: string | null;
  os_info?: string | null;
  version?: string | null;
  metrics?: SystemMetrics | null;
  created_at: string;
  camera_count: number;
  assigned_cameras: AssignedCameraInfo[];
};

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

// ── Reports ──

export type AppearanceItem = {
  event_id: number;
  event_ts: string;
  camera_id: number;
  camera_name?: string | null;
  camera_location?: string | null;
  group_name?: string | null;
  person_id?: number | null;
  person_label?: string | null;
  confidence?: number | null;
};

export type AppearanceReport = {
  date_from?: string | null;
  date_to?: string | null;
  person_id?: number | null;
  total: number;
  items: AppearanceItem[];
};

export type ReportValueLabel = {
  label: string;
  value: number;
};

export type ReportStorageStat = {
  storage_target_id: number;
  name: string;
  file_count: number;
  total_bytes: number;
};

export type UserActionActorStat = {
  user_id?: number | null;
  user_label: string;
  audit_actions: number;
  auth_success: number;
  auth_failures: number;
  review_actions: number;
  total_actions: number;
};

export type RecentUserAction = {
  action_kind: string;
  occurred_at: string;
  user_id?: number | null;
  user_label: string;
  action: string;
  details?: string | null;
  success?: boolean | null;
  source_ip?: string | null;
};

export type UserActionsReport = {
  active_users: number;
  total_audit_actions: number;
  total_auth_events: number;
  failed_auth_events: number;
  review_actions: number;
  totp_enabled_users: number;
  top_users: UserActionActorStat[];
  recent_actions: RecentUserAction[];
};

export type GroupReportItem = {
  group_id: number;
  name: string;
  camera_count: number;
  online_cameras: number;
  offline_cameras: number;
  event_count: number;
  recognized_count: number;
  pending_reviews: number;
  recordings_count: number;
  recordings_size_bytes: number;
};

export type CameraReportItem = {
  camera_id: number;
  name: string;
  location?: string | null;
  group_name?: string | null;
  connection_kind: string;
  assigned_processor?: string | null;
  detection_enabled: boolean;
  supports_ptz: boolean;
  is_online: boolean;
  event_count: number;
  recognized_count: number;
  unknown_count: number;
  motion_count: number;
  pending_reviews: number;
  recordings_count: number;
  recordings_size_bytes: number;
  last_event_ts?: string | null;
};

export type ProcessorReportItem = {
  processor_id: number;
  name: string;
  status: string;
  is_online: boolean;
  ip_address?: string | null;
  version?: string | null;
  last_heartbeat?: string | null;
  assigned_cameras: number;
  event_count: number;
  recordings_count: number;
  cpu_percent?: number | null;
  ram_percent?: number | null;
  gpu_util_percent?: number | null;
  uptime_seconds?: number | null;
};

export type ReviewerStat = {
  user_id?: number | null;
  user_label: string;
  approved: number;
  rejected: number;
  pending: number;
  total: number;
};

export type EventReviewReport = {
  total_events: number;
  recognized_events: number;
  unknown_events: number;
  motion_events: number;
  person_events: number;
  pending_reviews: number;
  approved_reviews: number;
  rejected_reviews: number;
  average_review_seconds?: number | null;
  events_by_type: ReportValueLabel[];
  top_reviewers: ReviewerStat[];
};

export type ArchiveCameraStat = {
  camera_id: number;
  camera_name: string;
  file_count: number;
  total_bytes: number;
  last_recording_at?: string | null;
};

export type ArchiveReport = {
  total_files: number;
  total_bytes: number;
  video_files: number;
  snapshot_files: number;
  by_camera: ArchiveCameraStat[];
  by_storage: ReportStorageStat[];
};

export type SecurityFailureItem = {
  occurred_at: string;
  user_id?: number | null;
  user_label: string;
  method: string;
  reason?: string | null;
  source_ip?: string | null;
};

export type SecurityReport = {
  total_users: number;
  totp_enabled_users: number;
  totp_coverage_percent: number;
  api_keys_total: number;
  api_keys_active: number;
  successful_logins: number;
  failed_logins: number;
  recent_failures: SecurityFailureItem[];
};

export type ReportsDashboard = {
  generated_at: string;
  date_from?: string | null;
  date_to?: string | null;
  group_id?: number | null;
  camera_id?: number | null;
  processor_id?: number | null;
  user_id?: number | null;
  user_actions: UserActionsReport;
  groups: GroupReportItem[];
  cameras: CameraReportItem[];
  processors: ProcessorReportItem[];
  events: EventReviewReport;
  archive: ArchiveReport;
  security: SecurityReport;
};

export async function getReportsDashboard(
  token: string,
  params?: {
    date_from?: string;
    date_to?: string;
    group_id?: number;
    camera_id?: number;
    processor_id?: number;
    user_id?: number;
  }
) {
  const qs = new URLSearchParams();
  if (params?.date_from) qs.append("date_from", params.date_from);
  if (params?.date_to) qs.append("date_to", params.date_to);
  if (params?.group_id !== undefined) qs.append("group_id", String(params.group_id));
  if (params?.camera_id !== undefined) qs.append("camera_id", String(params.camera_id));
  if (params?.processor_id !== undefined) qs.append("processor_id", String(params.processor_id));
  if (params?.user_id !== undefined) qs.append("user_id", String(params.user_id));
  const suffix = qs.toString();
  return request<ReportsDashboard>(`/reports/dashboard${suffix ? `?${suffix}` : ""}`, "GET", token);
}

export async function getAppearanceReport(
  token: string,
  params?: { date_from?: string; date_to?: string; person_id?: number }
) {
  const qs = new URLSearchParams();
  if (params?.date_from) qs.append("date_from", params.date_from);
  if (params?.date_to) qs.append("date_to", params.date_to);
  if (params?.person_id !== undefined) qs.append("person_id", String(params.person_id));
  return request<AppearanceReport>(`/reports/appearances?${qs}`, "GET", token);
}

export function appearanceExportUrl(
  _token: string,
  format: "pdf" | "xlsx" | "docx",
  params?: { date_from?: string; date_to?: string; person_id?: number }
) {
  const qs = new URLSearchParams();
  qs.append("format", format);
  if (params?.date_from) qs.append("date_from", params.date_from);
  if (params?.date_to) qs.append("date_to", params.date_to);
  if (params?.person_id !== undefined) qs.append("person_id", String(params.person_id));
  return `${API_URL}/reports/appearances/export?${qs}`;
}

export function dashboardSectionExportUrl(
  _token: string,
  section: "user-actions" | "groups" | "cameras" | "processors" | "events" | "archive" | "security",
  format: "pdf" | "xlsx" | "docx",
  params?: {
    date_from?: string;
    date_to?: string;
    group_id?: number;
    camera_id?: number;
    processor_id?: number;
    user_id?: number;
  }
) {
  const qs = new URLSearchParams();
  qs.append("section", section);
  qs.append("format", format);
  if (params?.date_from) qs.append("date_from", params.date_from);
  if (params?.date_to) qs.append("date_to", params.date_to);
  if (params?.group_id !== undefined) qs.append("group_id", String(params.group_id));
  if (params?.camera_id !== undefined) qs.append("camera_id", String(params.camera_id));
  if (params?.processor_id !== undefined) qs.append("processor_id", String(params.processor_id));
  if (params?.user_id !== undefined) qs.append("user_id", String(params.user_id));
  return `${API_URL}/reports/export?${qs}`;
}

// ── Admin: Users ──

export type UserOut = {
  user_id: number;
  login: string;
  role_id: number;
  first_name: string | null;
  last_name: string | null;
  middle_name: string | null;
  face_login_enabled: boolean;
  must_change_password: boolean;
};

export async function adminListUsers(token: string) {
  return request<UserOut[]>("/admin/users", "GET", token);
}

export async function adminCreateUser(
  token: string,
  payload: {
    login: string;
    password: string;
    role_id: number;
    first_name?: string;
    last_name?: string;
    middle_name?: string;
  }
) {
  return request<UserOut>("/admin/users", "POST", token, payload);
}

export async function adminDeleteUser(token: string, userId: number) {
  return request(`/admin/users/${userId}`, "DELETE", token);
}

export async function adminSetUserRole(token: string, userId: number, role_id: number) {
  return request(`/admin/users/${userId}/role?role_id=${role_id}`, "POST", token);
}

export async function deleteCamera(token: string, cameraId: number) {
  return request(`/admin/cameras/${cameraId}`, "DELETE", token);
}

export async function rejectAllPendingReviews(token: string) {
  return request<{ updated: number }>("/detections/review/reject-all", "POST", token);
}
