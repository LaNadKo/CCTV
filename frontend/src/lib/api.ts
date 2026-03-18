const envApi = import.meta.env.VITE_API_URL as string | undefined;
// dev: keep explicit backend (8000) unless env override; prod (served вместе с API): same-origin
const runtimeOrigin = typeof window !== "undefined" ? window.location.origin : "";
// Capacitor native app or PWA: check localStorage for user-configured server
const savedUrl = typeof window !== "undefined" ? localStorage.getItem("cctv_api_url") : null;
export const API_URL =
  savedUrl ||
  envApi ||
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

  const res = await fetch(`${API_URL}${path}`, {
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

export async function loginApi(login: string, password: string, totp_code?: string) {
  return request<{ access_token: string; token_type: string }>(
    "/auth/login",
    "POST",
    undefined,
    { login, password, totp_code }
  );
}

export async function me(token: string) {
  return request<{ user_id: number; login: string; role_id: number; face_login_enabled: boolean }>(
    "/auth/me",
    "GET",
    token
  );
}

export async function registerUser(login: string, password: string) {
  return request<{ user_id: number; login: string; role_id: number; face_login_enabled: boolean }>(
    "/users/register",
    "POST",
    undefined,
    { login, password }
  );
}

export async function getCameras(token: string, homeId?: number | null) {
  const qs = homeId ? `?home_id=${homeId}` : "";
  return request<
    {
      camera_id: number;
      name: string;
      location?: string;
      permission: string;
      ip_address?: string;
      stream_url?: string;
      detection_enabled: boolean;
      recording_mode: string;
    }[]
  >(`/cameras${qs}`, "GET", token);
}

export async function getPending(token: string) {
  return request<
    {
      event_id: number;
      camera_id: number;
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
  return request<{ api_key_id: number; description?: string; scopes: string[]; is_active: boolean }[]>(
    "/api-keys",
    "GET",
    token
  );
}

export async function listGroups(token: string) {
  return request<{ group_id: number; name: string; description?: string; membership_role?: string }[]>(
    "/groups",
    "GET",
    token
  );
}

export async function createGroup(token: string, name: string, description?: string) {
  return request("/groups", "POST", token, { name, description, camera_permissions: [], user_ids: [] });
}

export async function inviteToGroup(token: string, groupId: number, login: string, password?: string) {
  return request(`/groups/${groupId}/invite`, "POST", token, { login, password });
}

export async function transferOwner(token: string, groupId: number, login: string) {
  return request(`/groups/${groupId}/transfer_owner`, "POST", token, { login });
}

export async function getGroup(token: string, groupId: number) {
  return request<{ group_id: number; name: string; description?: string; cameras: any[]; membership_role?: string }>(
    `/groups/${groupId}`,
    "GET",
    token
  );
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
  }>
) {
  return request<{ camera_id: number }>(`/admin/cameras/${camera_id}`, "PATCH", token, payload);
}

export async function listRecordings(token: string, camera_id?: number) {
  const search = camera_id ? `?camera_id=${camera_id}` : "";
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
  >(`/recordings${search}`, "GET", token);
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

export async function addPersonEmbeddingFromPhoto(token: string, personId: number, file: File) {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_URL}/persons/${personId}/embeddings/photo`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  if (!res.ok) {
    const msg = await res.text();
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

export type ProcessorOut = {
  processor_id: number;
  name: string;
  status: string;
  last_heartbeat?: string | null;
  capabilities?: Record<string, unknown> | null;
  created_at: string;
  camera_count: number;
  assigned_cameras: AssignedCameraInfo[];
};

export async function listProcessors(token: string) {
  return request<ProcessorOut[]>("/processors", "GET", token);
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

// ── Homes ──

export type HomeOut = {
  home_id: number;
  name: string;
  description?: string | null;
  created_at: string;
  member_count: number;
  room_count: number;
  my_role?: string | null;
};

export type RoomCameraOut = {
  room_id: number;
  camera_id: number;
  camera_name: string;
  added_at: string;
};

export type RoomOut = {
  room_id: number;
  home_id: number;
  name: string;
  order_index: number;
  created_at: string;
  cameras: RoomCameraOut[];
};

export type MemberOut = {
  user_id: number;
  login: string;
  role: string;
  joined_at: string;
};

export type HomeDetailOut = {
  home_id: number;
  name: string;
  description?: string | null;
  created_at: string;
  my_role?: string | null;
  rooms: RoomOut[];
  members: MemberOut[];
};

export type InviteOut = {
  invitation_id: number;
  invite_code: string;
  invite_type: string;
  role: string;
  expires_at?: string | null;
};

export type ActivityOut = {
  activity_id: number;
  user_id?: number | null;
  user_login?: string | null;
  action: string;
  details?: Record<string, unknown> | null;
  created_at: string;
};

export async function listHomes(token: string) {
  return request<HomeOut[]>("/homes", "GET", token);
}

export async function createHome(token: string, name: string, description?: string) {
  return request<HomeOut>("/homes", "POST", token, { name, description });
}

export async function getHome(token: string, homeId: number) {
  return request<HomeDetailOut>(`/homes/${homeId}`, "GET", token);
}

export async function updateHome(token: string, homeId: number, payload: { name?: string; description?: string }) {
  return request<HomeOut>(`/homes/${homeId}`, "PATCH", token, payload);
}

export async function deleteHome(token: string, homeId: number) {
  return request(`/homes/${homeId}`, "DELETE", token);
}

export async function createRoom(token: string, homeId: number, name: string, order_index?: number) {
  return request<RoomOut>(`/homes/${homeId}/rooms`, "POST", token, { name, order_index: order_index ?? 0 });
}

export async function updateRoom(token: string, homeId: number, roomId: number, payload: { name?: string; order_index?: number }) {
  return request<RoomOut>(`/homes/${homeId}/rooms/${roomId}`, "PATCH", token, payload);
}

export async function deleteRoom(token: string, homeId: number, roomId: number) {
  return request(`/homes/${homeId}/rooms/${roomId}`, "DELETE", token);
}

export async function addCameraToRoom(token: string, homeId: number, roomId: number, cameraId: number) {
  return request(`/homes/${homeId}/rooms/${roomId}/cameras/${cameraId}`, "POST", token);
}

export async function removeCameraFromRoom(token: string, homeId: number, roomId: number, cameraId: number) {
  return request(`/homes/${homeId}/rooms/${roomId}/cameras/${cameraId}`, "DELETE", token);
}

export async function createHomeInvite(token: string, homeId: number, role?: string, expires_hours?: number) {
  return request<InviteOut>(`/homes/${homeId}/invite`, "POST", token, { role: role ?? "member", expires_hours: expires_hours ?? 72 });
}

export async function joinHomeByCode(token: string, invite_code: string) {
  return request(`/homes/join/${invite_code}`, "POST", token);
}

export async function updateHomeMemberRole(token: string, homeId: number, userId: number, role: string) {
  return request(`/homes/${homeId}/members/${userId}/role`, "PATCH", token, { role });
}

export async function removeHomeMember(token: string, homeId: number, userId: number) {
  return request(`/homes/${homeId}/members/${userId}`, "DELETE", token);
}

export async function transferHomeOwnership(token: string, homeId: number, newOwnerUserId: number) {
  return request(`/homes/${homeId}/transfer`, "POST", token, { new_owner_user_id: newOwnerUserId });
}

export async function getHomeActivity(token: string, homeId: number, limit?: number, offset?: number) {
  const params = new URLSearchParams();
  if (limit) params.append("limit", String(limit));
  if (offset) params.append("offset", String(offset));
  return request<ActivityOut[]>(`/homes/${homeId}/activity?${params}`, "GET", token);
}
