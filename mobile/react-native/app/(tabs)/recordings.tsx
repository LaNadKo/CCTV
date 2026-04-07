import { useEffect, useState, useCallback } from "react";
import { View, Text, TouchableOpacity, ScrollView, RefreshControl, Dimensions } from "react-native";
import { Video, ResizeMode } from "expo-av";
import { useAuth } from "../../src/context/AuthContext";
import {
  getCameras, listRecordings, getTimeline, recordingUrl,
  Camera, Recording, TimelineEvent,
} from "../../src/lib/api";
import { colors } from "../../src/theme/colors";
import { shared } from "../../src/theme/styles";

export default function RecordingsScreen() {
  const { token } = useAuth();
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [cameraId, setCameraId] = useState<number | undefined>();
  const [records, setRecords] = useState<Recording[]>([]);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [selectedDate, setSelectedDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [playingId, setPlayingId] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    if (!token) return;
    getCameras(token).then((c) => {
      setCameras(c);
      if (c.length > 0 && !cameraId) setCameraId(c[0].camera_id);
    });
  }, [token]);

  const load = useCallback(async () => {
    if (!token || !cameraId) return;
    const [recs, tl] = await Promise.all([
      listRecordings(token, cameraId),
      getTimeline(token, cameraId, `${selectedDate}T00:00:00`, `${selectedDate}T23:59:59`),
    ]);
    setRecords(recs.filter((r) => r.started_at.startsWith(selectedDate)));
    setTimeline(tl);
  }, [token, cameraId, selectedDate]);

  useEffect(() => { load(); }, [load]);

  const onRefresh = async () => { setRefreshing(true); await load(); setRefreshing(false); };

  const byHour: Record<number, Recording[]> = {};
  records.forEach((r) => {
    const h = new Date(r.started_at).getHours();
    (byHour[h] = byHour[h] || []).push(r);
  });

  const screenW = Dimensions.get("window").width - 32;

  return (
    <ScrollView style={shared.scroll} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />}>
      <Text style={shared.title}>Записи</Text>

      {/* Выбор камеры */}
      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginBottom: 12 }}>
        {cameras.map((c) => (
          <TouchableOpacity
            key={c.camera_id}
            style={[shared.pill, { marginRight: 8 }, cameraId === c.camera_id && { borderColor: colors.accent, backgroundColor: "rgba(101,255,160,0.1)" }]}
            onPress={() => setCameraId(c.camera_id)}
          >
            <Text style={[shared.pillText, cameraId === c.camera_id && { color: colors.accent }]}>{c.name}</Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      {/* Навигация по датам */}
      <View style={[shared.row, { justifyContent: "center", marginBottom: 16, gap: 16 }]}>
        <TouchableOpacity onPress={() => {
          const d = new Date(selectedDate);
          d.setDate(d.getDate() - 1);
          setSelectedDate(d.toISOString().slice(0, 10));
        }}>
          <Text style={{ color: colors.accent, fontSize: 18 }}>{"<"}</Text>
        </TouchableOpacity>
        <Text style={{ color: colors.text, fontSize: 16, fontWeight: "600" }}>{selectedDate}</Text>
        <TouchableOpacity onPress={() => {
          const d = new Date(selectedDate);
          d.setDate(d.getDate() + 1);
          setSelectedDate(d.toISOString().slice(0, 10));
        }}>
          <Text style={{ color: colors.accent, fontSize: 18 }}>{">"}</Text>
        </TouchableOpacity>
      </View>

      {/* Шкала событий */}
      {timeline.length > 0 && (
        <View style={[shared.card, { padding: 8, marginBottom: 12 }]}>
          <Text style={[shared.label, { marginBottom: 4 }]}>События: {timeline.length}</Text>
          <View style={{ flexDirection: "row", height: 12, borderRadius: 4, overflow: "hidden", backgroundColor: colors.inputBg }}>
            {timeline.map((ev) => {
              const h = new Date(ev.event_ts).getHours();
              const left = (h / 24) * 100;
              const color = ev.event_type === "face_recognized" ? colors.success : ev.event_type === "face_unknown" ? colors.warning : colors.accent2;
              return <View key={ev.event_id} style={{ position: "absolute", left: `${left}%`, width: 4, height: 12, backgroundColor: color }} />;
            })}
          </View>
        </View>
      )}

      {/* Записи по часам */}
      {Array.from({ length: 24 }, (_, h) => h).map((h) => {
        const recs = byHour[h];
        if (!recs) return null;
        return (
          <View key={h} style={shared.card}>
            <Text style={shared.subtitle}>{String(h).padStart(2, "0")}:00</Text>
            {recs.map((rec) => (
              <View key={rec.recording_file_id} style={{ marginTop: 8 }}>
                <TouchableOpacity onPress={() => setPlayingId(playingId === rec.recording_file_id ? null : rec.recording_file_id)}>
                  <Text style={{ color: colors.accent, fontSize: 13 }}>
                    {new Date(rec.started_at).toLocaleTimeString()} — {rec.duration_seconds ? `${Math.round(rec.duration_seconds)}с` : "..."}
                    {rec.file_size_bytes ? ` (${(rec.file_size_bytes / 1048576).toFixed(1)} МБ)` : ""}
                  </Text>
                </TouchableOpacity>
                {playingId === rec.recording_file_id && (
                  <View style={{ height: screenW * 0.5625, marginTop: 8, borderRadius: 8, overflow: "hidden" }}>
                    <Video
                      source={{ uri: recordingUrl(rec.recording_file_id, token!), headers: { Authorization: `Bearer ${token}` } }}
                      style={{ flex: 1 }}
                      useNativeControls
                      resizeMode={ResizeMode.CONTAIN}
                      shouldPlay
                    />
                  </View>
                )}
              </View>
            ))}
          </View>
        );
      })}

      {records.length === 0 && <Text style={shared.muted}>Нет записей за эту дату</Text>}
      <View style={{ height: 40 }} />
    </ScrollView>
  );
}
