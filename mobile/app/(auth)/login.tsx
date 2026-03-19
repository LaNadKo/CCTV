import { useState } from "react";
import {
  View, Text, TextInput, TouchableOpacity, ScrollView, KeyboardAvoidingView, Platform,
} from "react-native";
import { useAuth } from "../../src/context/AuthContext";
import { loginApi, changePassword, getApiUrl, setApiUrlSync } from "../../src/lib/api";
import { setApiUrl as saveApiUrl } from "../../src/lib/storage";
import { colors } from "../../src/theme/colors";
import { shared } from "../../src/theme/styles";

export default function LoginScreen() {
  const { login } = useAuth();
  const [form, setForm] = useState({ login: "", password: "" });
  const [totpCode, setTotpCode] = useState("");
  const [totpRequired, setTotpRequired] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [showServer, setShowServer] = useState(false);
  const [serverUrl, setServerUrl] = useState(getApiUrl());

  // Password change flow
  const [mustChangePassword, setMustChangePassword] = useState(false);
  const [pendingToken, setPendingToken] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newPasswordConfirm, setNewPasswordConfirm] = useState("");

  const doLogin = async (totp?: string) => {
    setLoading(true);
    setError("");
    try {
      const res = await loginApi(form.login, form.password, totp);
      if (res.must_change_password) {
        setPendingToken(res.access_token);
        setMustChangePassword(true);
      } else {
        await login(res.access_token);
      }
    } catch (e: any) {
      const msg = e.message || "";
      if (msg.toLowerCase().includes("totp") || msg.toLowerCase().includes("2fa")) {
        setTotpRequired(true);
      } else {
        setError(msg || "Ошибка входа");
      }
    } finally {
      setLoading(false);
    }
  };

  const doChangePassword = async () => {
    if (newPassword.length < 6) { setError("Минимум 6 символов"); return; }
    if (newPassword !== newPasswordConfirm) { setError("Пароли не совпадают"); return; }
    setLoading(true);
    setError("");
    try {
      await changePassword(pendingToken, form.password, newPassword);
      await login(pendingToken);
    } catch (e: any) {
      setError(e.message || "Ошибка смены пароля");
    } finally {
      setLoading(false);
    }
  };

  const handleServerSave = async () => {
    const url = serverUrl.replace(/\/+$/, "");
    setApiUrlSync(url);
    await saveApiUrl(url);
    setShowServer(false);
  };

  return (
    <KeyboardAvoidingView style={shared.container} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <ScrollView contentContainerStyle={{ flexGrow: 1, justifyContent: "center", padding: 24 }}>
        <Text style={{ fontSize: 28, fontWeight: "800", color: colors.accent, textAlign: "center", marginBottom: 8 }}>
          CCTV Console
        </Text>
        <Text style={{ fontSize: 14, color: colors.muted, textAlign: "center", marginBottom: 32 }}>
          Система видеонаблюдения
        </Text>

        {error ? <Text style={[shared.danger, { marginBottom: 12 }]}>{error}</Text> : null}

        {mustChangePassword ? (
          <>
            <Text style={[shared.label, { color: colors.warning, marginBottom: 12 }]}>
              Необходимо сменить пароль при первом входе
            </Text>
            <Text style={shared.label}>Новый пароль</Text>
            <TextInput
              style={[shared.input, { marginBottom: 14 }]}
              placeholder="Новый пароль"
              placeholderTextColor={colors.muted}
              secureTextEntry
              value={newPassword}
              onChangeText={setNewPassword}
            />
            <Text style={shared.label}>Подтвердите пароль</Text>
            <TextInput
              style={[shared.input, { marginBottom: 20 }]}
              placeholder="Повторите пароль"
              placeholderTextColor={colors.muted}
              secureTextEntry
              value={newPasswordConfirm}
              onChangeText={setNewPasswordConfirm}
            />
            <TouchableOpacity
              style={[shared.btn, shared.btnPrimary, loading && { opacity: 0.6 }]}
              onPress={doChangePassword}
              disabled={loading}
            >
              <Text style={shared.btnText}>{loading ? "Сохранение..." : "Сменить пароль"}</Text>
            </TouchableOpacity>
          </>
        ) : !totpRequired ? (
          <>
            <Text style={shared.label}>Логин</Text>
            <TextInput
              style={[shared.input, { marginBottom: 14 }]}
              placeholder="Имя пользователя"
              placeholderTextColor={colors.muted}
              autoCapitalize="none"
              value={form.login}
              onChangeText={(t) => setForm((p) => ({ ...p, login: t }))}
            />
            <Text style={shared.label}>Пароль</Text>
            <TextInput
              style={[shared.input, { marginBottom: 20 }]}
              placeholder="Пароль"
              placeholderTextColor={colors.muted}
              secureTextEntry
              value={form.password}
              onChangeText={(t) => setForm((p) => ({ ...p, password: t }))}
            />
            <TouchableOpacity
              style={[shared.btn, shared.btnPrimary, loading && { opacity: 0.6 }]}
              onPress={() => doLogin()}
              disabled={loading}
            >
              <Text style={shared.btnText}>{loading ? "Вход..." : "Войти"}</Text>
            </TouchableOpacity>
          </>
        ) : (
          <>
            <Text style={shared.label}>Код двухфакторной аутентификации</Text>
            <TextInput
              style={[shared.input, { marginBottom: 20 }]}
              placeholder="Введите TOTP код"
              placeholderTextColor={colors.muted}
              keyboardType="number-pad"
              value={totpCode}
              onChangeText={setTotpCode}
            />
            <TouchableOpacity
              style={[shared.btn, shared.btnPrimary, loading && { opacity: 0.6 }]}
              onPress={() => doLogin(totpCode)}
              disabled={loading}
            >
              <Text style={shared.btnText}>{loading ? "Проверка..." : "Подтвердить"}</Text>
            </TouchableOpacity>
            <TouchableOpacity style={{ marginTop: 12 }} onPress={() => setTotpRequired(false)}>
              <Text style={{ color: colors.accent, textAlign: "center" }}>Назад</Text>
            </TouchableOpacity>
          </>
        )}

        <TouchableOpacity style={{ marginTop: 20 }} onPress={() => setShowServer(!showServer)}>
          <Text style={{ color: colors.muted, textAlign: "center", fontSize: 13 }}>Настройки сервера</Text>
        </TouchableOpacity>

        {showServer && (
          <View style={[shared.card, { marginTop: 12 }]}>
            <Text style={shared.label}>URL сервера</Text>
            <TextInput
              style={[shared.input, { marginBottom: 12 }]}
              placeholder="http://192.168.50.62"
              placeholderTextColor={colors.muted}
              autoCapitalize="none"
              value={serverUrl}
              onChangeText={setServerUrl}
            />
            <TouchableOpacity style={[shared.btn, shared.btnSecondary]} onPress={handleServerSave}>
              <Text style={shared.btnTextSecondary}>Сохранить</Text>
            </TouchableOpacity>
          </View>
        )}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}
