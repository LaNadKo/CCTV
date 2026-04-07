import { useEffect, useState, useCallback } from "react";
import {
  View, Text, TextInput, TouchableOpacity, ScrollView, Image, Alert, RefreshControl,
} from "react-native";
import * as ImagePicker from "expo-image-picker";
import { useAuth } from "../../src/context/AuthContext";
import {
  listPersons, createPerson, updatePerson, addPersonEmbeddingFromUri, PersonOut,
} from "../../src/lib/api";
import { colors } from "../../src/theme/colors";
import { shared } from "../../src/theme/styles";

export default function PersonsScreen() {
  const { token } = useAuth();
  const [persons, setPersons] = useState<PersonOut[]>([]);
  const [selected, setSelected] = useState<PersonOut | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ first_name: "", last_name: "", middle_name: "" });
  const [editForm, setEditForm] = useState({ first_name: "", last_name: "", middle_name: "" });
  const [refreshing, setRefreshing] = useState(false);
  const [uploading, setUploading] = useState(false);

  const load = useCallback(async () => {
    if (!token) return;
    const ps = await listPersons(token);
    setPersons(ps);
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const onRefresh = async () => { setRefreshing(true); await load(); setRefreshing(false); };

  const handleCreate = async () => {
    if (!form.first_name.trim() || !token) return;
    try {
      await createPerson(token, {
        first_name: form.first_name.trim(),
        last_name: form.last_name.trim() || undefined,
        middle_name: form.middle_name.trim() || undefined,
      });
      setForm({ first_name: "", last_name: "", middle_name: "" });
      setCreating(false);
      await load();
    } catch (e: any) {
      Alert.alert("Error", e.message);
    }
  };

  const handleUpdate = async () => {
    if (!selected || !token) return;
    try {
      await updatePerson(token, selected.person_id, {
        first_name: editForm.first_name.trim() || undefined,
        last_name: editForm.last_name.trim() || undefined,
        middle_name: editForm.middle_name.trim() || undefined,
      });
      await load();
      Alert.alert("Updated");
    } catch (e: any) {
      Alert.alert("Error", e.message);
    }
  };

  const handlePickPhoto = async () => {
    if (!selected || !token) return;
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ["images"],
      quality: 0.8,
    });
    if (result.canceled || !result.assets[0]) return;
    setUploading(true);
    try {
      await addPersonEmbeddingFromUri(token, selected.person_id, result.assets[0].uri);
      await load();
      Alert.alert("Success", "Embedding added from photo");
    } catch (e: any) {
      Alert.alert("Error", e.message);
    } finally {
      setUploading(false);
    }
  };

  const handleTakePhoto = async () => {
    if (!selected || !token) return;
    const perm = await ImagePicker.requestCameraPermissionsAsync();
    if (!perm.granted) { Alert.alert("Permission required", "Camera access needed"); return; }
    const result = await ImagePicker.launchCameraAsync({ quality: 0.8 });
    if (result.canceled || !result.assets[0]) return;
    setUploading(true);
    try {
      await addPersonEmbeddingFromUri(token, selected.person_id, result.assets[0].uri);
      await load();
      Alert.alert("Success", "Embedding added from camera");
    } catch (e: any) {
      Alert.alert("Error", e.message);
    } finally {
      setUploading(false);
    }
  };

  const selectPerson = (p: PersonOut) => {
    setSelected(p);
    setEditForm({ first_name: p.first_name ?? "", last_name: p.last_name ?? "", middle_name: p.middle_name ?? "" });
  };

  return (
    <ScrollView style={shared.scroll} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />}>
      <View style={[shared.row, { justifyContent: "space-between", marginBottom: 12 }]}>
        <Text style={shared.title}>Persons</Text>
        <TouchableOpacity style={[shared.btn, shared.btnPrimary, { paddingVertical: 8 }]} onPress={() => setCreating(!creating)}>
          <Text style={shared.btnText}>{creating ? "Cancel" : "+ Add"}</Text>
        </TouchableOpacity>
      </View>

      {creating && (
        <View style={shared.card}>
          <Text style={shared.subtitle}>New Person</Text>
          <TextInput style={[shared.input, { marginBottom: 8 }]} placeholder="First name *" placeholderTextColor={colors.muted} value={form.first_name} onChangeText={(t) => setForm((p) => ({ ...p, first_name: t }))} />
          <TextInput style={[shared.input, { marginBottom: 8 }]} placeholder="Last name" placeholderTextColor={colors.muted} value={form.last_name} onChangeText={(t) => setForm((p) => ({ ...p, last_name: t }))} />
          <TextInput style={[shared.input, { marginBottom: 8 }]} placeholder="Middle name" placeholderTextColor={colors.muted} value={form.middle_name} onChangeText={(t) => setForm((p) => ({ ...p, middle_name: t }))} />
          <TouchableOpacity style={[shared.btn, shared.btnPrimary]} onPress={handleCreate}>
            <Text style={shared.btnText}>Create</Text>
          </TouchableOpacity>
        </View>
      )}

      {/* Person list */}
      {persons.map((p) => (
        <TouchableOpacity
          key={p.person_id}
          style={[shared.card, selected?.person_id === p.person_id && { borderColor: colors.accent }]}
          onPress={() => selectPerson(p)}
        >
          <View style={[shared.row, { justifyContent: "space-between" }]}>
            <Text style={shared.subtitle}>
              {[p.last_name, p.first_name, p.middle_name].filter(Boolean).join(" ") || `Person #${p.person_id}`}
            </Text>
            <View style={shared.pill}>
              <Text style={shared.pillText}>{p.embeddings_count} emb.</Text>
            </View>
          </View>

          {selected?.person_id === p.person_id && (
            <View style={{ marginTop: 12 }}>
              <View style={shared.divider} />
              <Text style={shared.label}>Edit Name</Text>
              <TextInput style={[shared.input, { marginBottom: 6 }]} placeholder="First name" placeholderTextColor={colors.muted} value={editForm.first_name} onChangeText={(t) => setEditForm((prev) => ({ ...prev, first_name: t }))} />
              <TextInput style={[shared.input, { marginBottom: 6 }]} placeholder="Last name" placeholderTextColor={colors.muted} value={editForm.last_name} onChangeText={(t) => setEditForm((prev) => ({ ...prev, last_name: t }))} />
              <TextInput style={[shared.input, { marginBottom: 8 }]} placeholder="Middle name" placeholderTextColor={colors.muted} value={editForm.middle_name} onChangeText={(t) => setEditForm((prev) => ({ ...prev, middle_name: t }))} />
              <TouchableOpacity style={[shared.btn, shared.btnSecondary, { marginBottom: 8 }]} onPress={handleUpdate}>
                <Text style={shared.btnTextSecondary}>Save Changes</Text>
              </TouchableOpacity>

              <Text style={[shared.label, { marginTop: 8 }]}>Add Face Embedding</Text>
              <View style={[shared.row, { gap: 8 }]}>
                <TouchableOpacity style={[shared.btn, shared.btnSecondary, { flex: 1 }]} onPress={handlePickPhoto} disabled={uploading}>
                  <Text style={shared.btnTextSecondary}>{uploading ? "..." : "Gallery"}</Text>
                </TouchableOpacity>
                <TouchableOpacity style={[shared.btn, shared.btnSecondary, { flex: 1 }]} onPress={handleTakePhoto} disabled={uploading}>
                  <Text style={shared.btnTextSecondary}>{uploading ? "..." : "Camera"}</Text>
                </TouchableOpacity>
              </View>
            </View>
          )}
        </TouchableOpacity>
      ))}
      {persons.length === 0 && !creating && <Text style={shared.muted}>No persons registered</Text>}
      <View style={{ height: 40 }} />
    </ScrollView>
  );
}
