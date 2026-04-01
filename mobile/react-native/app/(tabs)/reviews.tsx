import { useEffect, useState, useCallback } from "react";
import { View, Text, TextInput, TouchableOpacity, ScrollView, Image, Alert, RefreshControl } from "react-native";
import { useAuth } from "../../src/context/AuthContext";
import {
  getPending, reviewEvent, listPersons, createPerson, PendingEvent, PersonOut, getApiUrl,
} from "../../src/lib/api";
import { colors } from "../../src/theme/colors";
import { shared } from "../../src/theme/styles";

export default function ReviewsScreen() {
  const { token } = useAuth();
  const [events, setEvents] = useState<PendingEvent[]>([]);
  const [persons, setPersons] = useState<PersonOut[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [enrollForm, setEnrollForm] = useState<Record<number, { first_name: string; last_name: string; middle_name: string }>>({});
  const [assignMap, setAssignMap] = useState<Record<number, number | undefined>>({});

  const load = useCallback(async () => {
    if (!token) return;
    const [ev, ps] = await Promise.all([getPending(token), listPersons(token)]);
    setEvents(ev);
    setPersons(ps);
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const onRefresh = async () => { setRefreshing(true); await load(); setRefreshing(false); };

  const handleReview = async (eventId: number, status: "approved" | "rejected") => {
    if (!token) return;
    try {
      await reviewEvent(token, eventId, status, assignMap[eventId]);
      setEvents((prev) => prev.filter((e) => e.event_id !== eventId));
    } catch (e: any) {
      Alert.alert("Error", e.message);
    }
  };

  const handleEnroll = async (eventId: number) => {
    if (!token) return;
    const f = enrollForm[eventId];
    if (!f?.first_name?.trim()) { Alert.alert("Error", "First name required"); return; }
    try {
      const person = await createPerson(token, { first_name: f.first_name.trim(), last_name: f.last_name?.trim(), middle_name: f.middle_name?.trim() });
      setAssignMap((prev) => ({ ...prev, [eventId]: person.person_id }));
      await handleReview(eventId, "approved");
      await load();
    } catch (e: any) {
      Alert.alert("Error", e.message);
    }
  };

  const apiUrl = getApiUrl();

  return (
    <ScrollView style={shared.scroll} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />}>
      <Text style={shared.title}>Pending Reviews</Text>
      <Text style={[shared.muted, { marginBottom: 16 }]}>{events.length} events</Text>

      {events.map((ev) => {
        const snap = ev.snapshot_url ? (ev.snapshot_url.startsWith("http") ? ev.snapshot_url : `${apiUrl}${ev.snapshot_url}`) : null;
        return (
          <View key={ev.event_id} style={shared.card}>
            {snap && (
              <Image
                source={{ uri: `${snap}${snap.includes("?") ? "&" : "?"}token=${token}`, headers: { Authorization: `Bearer ${token}` } }}
                style={{ width: "100%", height: 200, borderRadius: 8, marginBottom: 10, backgroundColor: colors.inputBg }}
                resizeMode="cover"
              />
            )}
            <Text style={{ color: colors.text, marginBottom: 4 }}>Camera #{ev.camera_id} — {new Date(ev.event_ts).toLocaleString()}</Text>
            {ev.confidence != null && <Text style={shared.muted}>Confidence: {(ev.confidence * 100).toFixed(1)}%</Text>}
            {ev.person_label && <Text style={{ color: colors.accent, marginBottom: 4 }}>Match: {ev.person_label}</Text>}

            {/* Assign to existing person */}
            <Text style={[shared.label, { marginTop: 8 }]}>Assign to person:</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginBottom: 8 }}>
              {persons.map((p) => (
                <TouchableOpacity
                  key={p.person_id}
                  style={[shared.pill, { marginRight: 6 }, assignMap[ev.event_id] === p.person_id && { borderColor: colors.accent }]}
                  onPress={() => setAssignMap((prev) => ({ ...prev, [ev.event_id]: p.person_id }))}
                >
                  <Text style={[shared.pillText, assignMap[ev.event_id] === p.person_id && { color: colors.accent }]}>
                    {[p.last_name, p.first_name].filter(Boolean).join(" ") || `#${p.person_id}`}
                  </Text>
                </TouchableOpacity>
              ))}
            </ScrollView>

            {/* Enroll new person */}
            <TouchableOpacity onPress={() => setEnrollForm((prev) => prev[ev.event_id] ? { ...prev, [ev.event_id]: undefined as any } : { ...prev, [ev.event_id]: { first_name: "", last_name: "", middle_name: "" } })}>
              <Text style={{ color: colors.accent2, fontSize: 13, marginBottom: 6 }}>
                {enrollForm[ev.event_id] ? "Cancel enroll" : "Enroll as new person"}
              </Text>
            </TouchableOpacity>

            {enrollForm[ev.event_id] && (
              <View style={{ marginBottom: 8 }}>
                <TextInput style={[shared.input, { marginBottom: 6, minHeight: 36, paddingVertical: 6 }]} placeholder="First name *" placeholderTextColor={colors.muted} value={enrollForm[ev.event_id].first_name} onChangeText={(t) => setEnrollForm((prev) => ({ ...prev, [ev.event_id]: { ...prev[ev.event_id], first_name: t } }))} />
                <TextInput style={[shared.input, { marginBottom: 6, minHeight: 36, paddingVertical: 6 }]} placeholder="Last name" placeholderTextColor={colors.muted} value={enrollForm[ev.event_id].last_name} onChangeText={(t) => setEnrollForm((prev) => ({ ...prev, [ev.event_id]: { ...prev[ev.event_id], last_name: t } }))} />
                <TouchableOpacity style={[shared.btn, shared.btnSecondary, { paddingVertical: 8 }]} onPress={() => handleEnroll(ev.event_id)}>
                  <Text style={shared.btnTextSecondary}>Create & Assign</Text>
                </TouchableOpacity>
              </View>
            )}

            <View style={[shared.row, { marginTop: 8, gap: 10 }]}>
              <TouchableOpacity style={[shared.btn, shared.btnPrimary, { flex: 1, paddingVertical: 10 }]} onPress={() => handleReview(ev.event_id, "approved")}>
                <Text style={shared.btnText}>Approve</Text>
              </TouchableOpacity>
              <TouchableOpacity style={[shared.btn, shared.btnDanger, { flex: 1, paddingVertical: 10 }]} onPress={() => handleReview(ev.event_id, "rejected")}>
                <Text style={shared.btnDangerText}>Reject</Text>
              </TouchableOpacity>
            </View>
          </View>
        );
      })}

      {events.length === 0 && <Text style={shared.muted}>No pending events</Text>}
      <View style={{ height: 40 }} />
    </ScrollView>
  );
}
