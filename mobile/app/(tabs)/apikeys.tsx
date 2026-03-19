import { useEffect, useState, useCallback } from "react";
import { View, Text, TextInput, TouchableOpacity, ScrollView, Alert, RefreshControl } from "react-native";
import * as Clipboard from "expo-clipboard";
import { useAuth } from "../../src/context/AuthContext";
import { listApiKeys, createApiKey, ApiKeyOut } from "../../src/lib/api";
import { colors } from "../../src/theme/colors";
import { shared } from "../../src/theme/styles";

const PRESETS: Record<string, string[]> = {
  Processor: ["processor:register", "processor:heartbeat", "cameras:read", "detections:write"],
  "Detection Writer": ["detections:write"],
};

export default function ApiKeysScreen() {
  const { token } = useAuth();
  const [keys, setKeys] = useState<ApiKeyOut[]>([]);
  const [creating, setCreating] = useState(false);
  const [desc, setDesc] = useState("");
  const [scopes, setScopes] = useState("");
  const [newKey, setNewKey] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    if (!token) return;
    setKeys(await listApiKeys(token));
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const onRefresh = async () => { setRefreshing(true); await load(); setRefreshing(false); };

  const handleCreate = async (scopeList: string[]) => {
    if (!token || !desc.trim()) { Alert.alert("Error", "Description required"); return; }
    try {
      const res = await createApiKey(token, desc.trim(), scopeList);
      setNewKey(res.api_key);
      setDesc("");
      setScopes("");
      await load();
    } catch (e: any) {
      Alert.alert("Error", e.message);
    }
  };

  const copyKey = async () => {
    if (!newKey) return;
    try {
      await Clipboard.setStringAsync(newKey);
      Alert.alert("Copied!");
    } catch {
      Alert.alert("Key", newKey);
    }
  };

  return (
    <ScrollView style={shared.scroll} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />}>
      <Text style={shared.title}>API Keys</Text>

      <TouchableOpacity style={[shared.btn, shared.btnPrimary, { marginBottom: 16 }]} onPress={() => setCreating(!creating)}>
        <Text style={shared.btnText}>{creating ? "Cancel" : "+ Create Key"}</Text>
      </TouchableOpacity>

      {creating && (
        <View style={shared.card}>
          <Text style={shared.subtitle}>New API Key</Text>
          <TextInput style={[shared.input, { marginBottom: 8 }]} placeholder="Description *" placeholderTextColor={colors.muted} value={desc} onChangeText={setDesc} />

          <Text style={shared.label}>Quick presets:</Text>
          <View style={[shared.row, { marginBottom: 10, flexWrap: "wrap" }]}>
            {Object.entries(PRESETS).map(([name, sc]) => (
              <TouchableOpacity key={name} style={[shared.pill, { marginRight: 8, marginBottom: 4 }]} onPress={() => handleCreate(sc)}>
                <Text style={shared.pillText}>{name}</Text>
              </TouchableOpacity>
            ))}
          </View>

          <Text style={shared.label}>Or custom scopes (comma-separated):</Text>
          <TextInput style={[shared.input, { marginBottom: 8 }]} placeholder="scope1, scope2" placeholderTextColor={colors.muted} autoCapitalize="none" value={scopes} onChangeText={setScopes} />
          <TouchableOpacity style={[shared.btn, shared.btnSecondary]} onPress={() => handleCreate(scopes.split(",").map((s) => s.trim()).filter(Boolean))}>
            <Text style={shared.btnTextSecondary}>Create with Custom Scopes</Text>
          </TouchableOpacity>
        </View>
      )}

      {newKey && (
        <TouchableOpacity style={[shared.card, { borderColor: colors.accent }]} onPress={copyKey}>
          <Text style={shared.label}>New key (tap to copy):</Text>
          <Text style={{ color: colors.accent, fontFamily: "monospace", fontSize: 12 }} numberOfLines={3}>{newKey}</Text>
        </TouchableOpacity>
      )}

      {keys.map((k) => (
        <View key={k.api_key_id} style={shared.card}>
          <View style={[shared.row, { justifyContent: "space-between" }]}>
            <Text style={{ color: colors.text }}>{k.description || `Key #${k.api_key_id}`}</Text>
            <View style={[shared.pill, { borderColor: k.is_active ? colors.success : colors.danger }]}>
              <Text style={[shared.pillText, { color: k.is_active ? colors.success : colors.danger }]}>
                {k.is_active ? "active" : "revoked"}
              </Text>
            </View>
          </View>
          <Text style={[shared.muted, { fontSize: 11, marginTop: 4 }]}>{k.scopes.join(", ")}</Text>
        </View>
      ))}

      {keys.length === 0 && !creating && <Text style={shared.muted}>No API keys</Text>}
      <View style={{ height: 40 }} />
    </ScrollView>
  );
}
