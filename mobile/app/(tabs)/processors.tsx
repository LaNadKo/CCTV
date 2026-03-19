import { useEffect, useState, useCallback } from "react";
import { View, Text, TouchableOpacity, ScrollView, Alert, RefreshControl } from "react-native";
import { useAuth } from "../../src/context/AuthContext";
import {
  listProcessors, deleteProcessor, assignCamerasToProcessor, unassignCameraFromProcessor,
  getCameras, generateProcessorCode, ProcessorOut, Camera,
} from "../../src/lib/api";
import { colors } from "../../src/theme/colors";
import { shared } from "../../src/theme/styles";

export default function ProcessorsScreen() {
  const { token } = useAuth();
  const [procs, setProcs] = useState<ProcessorOut[]>([]);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [connectCode, setConnectCode] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    const [p, c] = await Promise.all([listProcessors(token), getCameras(token)]);
    setProcs(p);
    setCameras(c);
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const onRefresh = async () => { setRefreshing(true); await load(); setRefreshing(false); };

  const handleDelete = (id: number, name: string) => {
    Alert.alert("Удалить процессор", `Удалить "${name}"?`, [
      { text: "Отмена", style: "cancel" },
      { text: "Удалить", style: "destructive", onPress: async () => { await deleteProcessor(token!, id); await load(); } },
    ]);
  };

  const handleGenerateCode = async () => {
    if (!token) return;
    try {
      const res = await generateProcessorCode(token);
      setConnectCode(res.code);
    } catch (e: any) {
      Alert.alert("Ошибка", e.message || "Не удалось сгенерировать код");
    }
  };

  return (
    <ScrollView style={shared.scroll} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />}>
      <Text style={shared.title}>Процессоры</Text>

      <TouchableOpacity style={[shared.btn, shared.btnPrimary, { marginBottom: 16 }]} onPress={handleGenerateCode}>
        <Text style={shared.btnText}>Сгенерировать код подключения</Text>
      </TouchableOpacity>

      {connectCode && (
        <View style={[shared.card, { borderColor: colors.accent }]}>
          <Text style={shared.label}>Код подключения</Text>
          <Text style={{ color: colors.accent, fontSize: 20, fontWeight: "700", textAlign: "center", marginVertical: 8 }}>{connectCode}</Text>
          <Text style={shared.muted}>Введите этот код в Processor при первом запуске</Text>
        </View>
      )}

      {procs.map((proc) => {
        const isSelected = selected === proc.processor_id;
        const assignedIds = new Set(proc.assigned_cameras.map((c) => c.camera_id));
        const available = cameras.filter((c) => !assignedIds.has(c.camera_id));
        const isOnline = proc.status === "online";

        return (
          <TouchableOpacity
            key={proc.processor_id}
            style={[shared.card, isSelected && { borderColor: colors.accent }]}
            onPress={() => setSelected(isSelected ? null : proc.processor_id)}
          >
            <View style={[shared.row, { justifyContent: "space-between", marginBottom: 4 }]}>
              <Text style={shared.subtitle}>{proc.name}</Text>
              <View style={[shared.pill, { borderColor: isOnline ? colors.success : colors.danger }]}>
                <Text style={[shared.pillText, { color: isOnline ? colors.success : colors.danger }]}>{proc.status}</Text>
              </View>
            </View>
            {proc.ip_address && <Text style={shared.muted}>IP: {proc.ip_address}</Text>}
            {proc.last_heartbeat && <Text style={shared.muted}>Последняя активность: {new Date(proc.last_heartbeat).toLocaleString()}</Text>}
            <Text style={shared.muted}>{proc.camera_count} камер назначено</Text>

            {isSelected && (
              <View style={{ marginTop: 12 }}>
                <View style={shared.divider} />

                <Text style={shared.label}>Назначенные камеры</Text>
                {proc.assigned_cameras.map((c) => (
                  <View key={c.camera_id} style={[shared.row, { justifyContent: "space-between", paddingVertical: 6 }]}>
                    <Text style={{ color: colors.text }}>{c.name}</Text>
                    <TouchableOpacity onPress={async () => { await unassignCameraFromProcessor(token!, proc.processor_id, c.camera_id); await load(); }}>
                      <Text style={{ color: colors.danger, fontSize: 13 }}>Убрать</Text>
                    </TouchableOpacity>
                  </View>
                ))}
                {proc.assigned_cameras.length === 0 && <Text style={shared.muted}>Нет</Text>}

                {available.length > 0 && (
                  <>
                    <Text style={[shared.label, { marginTop: 8 }]}>Назначить камеру</Text>
                    {available.map((c) => (
                      <TouchableOpacity
                        key={c.camera_id}
                        style={[shared.pill, { alignSelf: "flex-start", marginBottom: 4 }]}
                        onPress={async () => { await assignCamerasToProcessor(token!, proc.processor_id, [c.camera_id]); await load(); }}
                      >
                        <Text style={shared.pillText}>+ {c.name}</Text>
                      </TouchableOpacity>
                    ))}
                  </>
                )}

                <TouchableOpacity style={[shared.btn, shared.btnDanger, { marginTop: 12 }]} onPress={() => handleDelete(proc.processor_id, proc.name)}>
                  <Text style={shared.btnDangerText}>Удалить процессор</Text>
                </TouchableOpacity>
              </View>
            )}
          </TouchableOpacity>
        );
      })}

      {procs.length === 0 && <Text style={shared.muted}>Нет зарегистрированных процессоров</Text>}
      <View style={{ height: 40 }} />
    </ScrollView>
  );
}
