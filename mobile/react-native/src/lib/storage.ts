import AsyncStorage from "@react-native-async-storage/async-storage";

const KEYS = {
  token: "cctv_token",
  apiUrl: "cctv_api_url",
  user: "cctv_user",
};

export async function getToken(): Promise<string | null> {
  return AsyncStorage.getItem(KEYS.token);
}
export async function setToken(token: string): Promise<void> {
  await AsyncStorage.setItem(KEYS.token, token);
}
export async function clearToken(): Promise<void> {
  await AsyncStorage.removeItem(KEYS.token);
}

export async function getApiUrl(): Promise<string | null> {
  return AsyncStorage.getItem(KEYS.apiUrl);
}
export async function setApiUrl(url: string): Promise<void> {
  await AsyncStorage.setItem(KEYS.apiUrl, url.replace(/\/+$/, ""));
}

export async function getUser(): Promise<{ user_id: number; login: string; role_id: number } | null> {
  const raw = await AsyncStorage.getItem(KEYS.user);
  return raw ? JSON.parse(raw) : null;
}
export async function setUser(u: { user_id: number; login: string; role_id: number }): Promise<void> {
  await AsyncStorage.setItem(KEYS.user, JSON.stringify(u));
}
export async function clearUser(): Promise<void> {
  await AsyncStorage.removeItem(KEYS.user);
}
