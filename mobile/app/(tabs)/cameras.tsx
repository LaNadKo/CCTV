import { useEffect, useState, useCallback } from "react";
import {
  View, Text, TextInput, TouchableOpacity, ScrollView, Alert, RefreshControl, Switch,
} from "react-native";
import { useAuth } from "../../src/context/AuthContext";
import { getCameras, createCamera, updateCamera, Camera } from "../../src/lib/api";
import { colors } from "../../src/theme/colors";
import { shared } from "../../src/theme/styles";

export default function CamerasScreen() {
  const { token, user } = useAuth();
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [selected, setSelected] = useState<Camera | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ name: "", location: "", ip_address: "", stream_url: "", detection_enabled: false, recording_mode: "continuous" });
  const [refreshing, setRefreshing] = useState(false);

  const isAdmin = user?.role_id === 1;

  const load = useCallback(async () => {
    if (!token) return;
    const c = await getCameras(token);
    setCameras(c);
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const onRefresh = async () => { setRefreshing(true); await load(); setRefreshing(false); };

  const handleCreate = async () => {
    if (!form.name.trim() || !token) return;
    try {
      await createCamera(token, {
        name: form.name.trim(),
        location: form.location.trim() || undefined,
        ip_address: form.ip_address.trim() || undefined,
        stream_url: form.stream_url.trim() || undefined,
        detection_enabled: form.detection_enabled,
        recording_mode: form.recording_mode,
      });
      setForm({ name: "", location: "", ip_address: "", stream_url: "", detection_enabled: false, recording_mode: "continuous" });
      setCreating(false);
      await load();
    } catch (e: any) {
      Alert.alert("Ошибка", e.message);
    }
  };

  const handleUpdate = async (id: number, patch: Partial<Camera>) => {
    if (!token) return;
    try {
      await updateCamera(token, id, patch);
      await load();
      const updated = cameras.find((c) => c.camera_id === id);
      if (updated) setSelected({ ...updated, ...patch });
    } catch (e: any) {
      Alert.alert("Ошибка", e.message);
    }
  };

  if (!isAdmin) {
    return (
      <View style={[shared.scroll, { justifyContent: "center", alignItems: "center", flex: 1 }]}>
        <Text style={shared.muted}>Доступ только для администраторов</Text>
      </View>
    );
  }

  return (
    <ScrollView style={shared.scroll} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />}>
      <View style={[shared.row, { justifyContent: "space-between", marginBottom: 12 }]}>
        <Text style={shared.title}>Камеры</Text>
        <TouchableOpacity style={[shared.btn, shared.btnPrimary, { paddingVertical: 8 }]} onPress={() => setCreating(!creating)}>
          <Text style={shared.btnText}>{creating ? "Отмена" : "+ Добавить"}</Text>
        </TouchableOpacity>
      </View>

      {creating && (
        <View style={shared.card}>
          <Text style={shared.subtitle}>Новая камера</Text>
          <TextInput style={[shared.input, { marginBottom: 8 }]} placeholder="Название *" placeholderTextColor={colors.muted} value={form.name} onChangeText={(t) => setForm((p) => ({ ...p, name: t }))} />
          <TextInput style={[shared.input, { marginBottom: 8 }]} placeholder="Расположение" placeholderTextColor={colors.muted} value={form.location} onChangeText={(t) => setForm((p) => ({ ...p, location: t }))} />
          <TextInput style={[shared.input, { marginBottom: 8 }]} placeholder="IP-адрес" placeholderTextColor={colors.muted} autoCapitalize="none" value={form.ip_address} onChangeText={(t) => setForm((p) => ({ ...p, ip_address: t }))} />
          <TextInput style={[shared.input, { marginBottom: 8 }]} placeholder="URL потока (RTSP)" placeholderTextColor={colors.muted} autoCapitalize="none" value={form.stream_url} onChangeText={(t) => setForm((p) => ({ ...p, stream_url: t }))} />
          <View style={[shared.row, { justifyContent: "space-between", marginBottom: 8 }]}>
            <Text style={{ color: colors.text }}>Детекция</Text>
            <Switch value={form.detection_enabled} onValueChange={(v) => setForm((p) => ({ ...p, detection_enabled: v }))} trackColor={{ true: colors.accent }} />
          </View>
          <TouchableOpacity style={[shared.btn, shared.btnPrimary]} onPress={handleCreate}>
            <Text style={shared.btnText}>Создать камеру</Text>
          </TouchableOpacity>
        </View>
      )}

      {cameras.map((cam) => (
        <TouchableOpacity key={cam.camera_id} style={[shared.card, selected?.camera_id === cam.camera_id && { borderColor: colors.accent }]} onPress={() => setSelected(selected?.camera_id === cam.camera_id ? null : cam)}>
          <View style={[shared.row, { justifyContent: "space-between" }]}>
            <Text style={shared.subtitle}>{cam.name}</Text>
            <View style={shared.pill}>
              <Text style={shared.pillText}>{cam.recording_mode}</Text>
            </View>
          </View>
          {cam.location ? <Text style={shared.muted}>{cam.location}</Text> : null}
          {cam.ip_address ? <Text style={[shared.muted, { fontSize: 12 }]}>IP: {cam.ip_address}</Text> : null}

          {selected?.camera_id === cam.camera_id && (
            <View style={{ marginTop: 12 }}>
              <View style={shared.divider} />
              <View style={[shared.row, { justifyContent: "space-between", marginBottom: 8 }]}>
                <Text style={{ color: colors.text }}>Детекция</Text>
                <Switch
                  value={cam.detection_enabled}
                  onValueChange={(v) => handleUpdate(cam.camera_id, { detection_enabled: v })}
                  trackColor={{ true: colors.accent }}
                />
              </View>
              <View style={[shared.row, { marginBottom: 8, flexWrap: "wrap" }]}>
                {["continuous", "motion", "off"].map((mode) => (
                  <TouchableOpacity
                    key={mode}
                    style={[shared.pill, cam.recording_mode === mode && { borderColor: colors.accent, backgroundColor: "rgba(101,255,160,0.1)" }]}
                    onPress={() => handleUpdate(cam.camera_id, { recording_mode: mode })}
                  >
                    <Text style={[shared.pillText, cam.recording_mode === mode && { color: colors.accent }]}>{mode}</Text>
                  </TouchableOpacity>
                ))}
              </View>
            </View>
          )}
        </TouchableOpacity>
      ))}
      {cameras.length === 0 && <Text style={shared.muted}>Нет камер</Text>}
    </ScrollView>
  );
}
