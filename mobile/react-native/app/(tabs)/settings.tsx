import { useState } from "react";
import { View, Text, TextInput, TouchableOpacity, ScrollView, Alert } from "react-native";
import { useAuth } from "../../src/context/AuthContext";
import { getApiUrl, setApiUrlSync, changePassword } from "../../src/lib/api";
import { setApiUrl as saveApiUrl } from "../../src/lib/storage";
import { colors } from "../../src/theme/colors";
import { shared } from "../../src/theme/styles";

const roleName = (id?: number) => {
  if (id === 1) return "Админ";
  if (id === 2) return "Пользователь";
  if (id === 3) return "Наблюдатель";
  return "—";
};

export default function SettingsScreen() {
  const { user, token, logout, refreshUser } = useAuth();
  const [serverUrl, setServerUrl] = useState(getApiUrl());

  const [currentPwd, setCurrentPwd] = useState("");
  const [newPwd, setNewPwd] = useState("");
  const [confirmPwd, setConfirmPwd] = useState("");
  const [pwdLoading, setPwdLoading] = useState(false);

  const handleSaveUrl = async () => {
    const url = serverUrl.replace(/\/+$/, "");
    setApiUrlSync(url);
    await saveApiUrl(url);
    Alert.alert("Сохранено", "URL сервера обновлён. Может потребоваться повторный вход.");
  };

  const handleChangePassword = async () => {
    if (!currentPwd.trim() || !newPwd.trim()) {
      Alert.alert("Ошибка", "Заполните все поля");
      return;
    }
    if (newPwd !== confirmPwd) {
      Alert.alert("Ошибка", "Новый пароль и подтверждение не совпадают");
      return;
    }
    if (newPwd.length < 4) {
      Alert.alert("Ошибка", "Пароль должен быть не менее 4 символов");
      return;
    }
    setPwdLoading(true);
    try {
      await changePassword(token!, currentPwd, newPwd);
      await refreshUser();
      setCurrentPwd("");
      setNewPwd("");
      setConfirmPwd("");
      Alert.alert("Готово", "Пароль успешно изменён");
    } catch (e: any) {
      Alert.alert("Ошибка", e.message || "Не удалось изменить пароль");
    } finally {
      setPwdLoading(false);
    }
  };

  return (
    <ScrollView style={shared.scroll}>
      <Text style={shared.title}>Настройки</Text>

      {/* Информация о пользователе */}
      <View style={shared.card}>
        <Text style={shared.subtitle}>Пользователь</Text>
        <Text style={{ color: colors.text, marginBottom: 4 }}>{user?.login ?? "—"}</Text>
        <View style={[shared.pill, { alignSelf: "flex-start" }]}>
          <Text style={shared.pillText}>{roleName(user?.role_id)}</Text>
        </View>
      </View>

      {/* Смена пароля */}
      <View style={shared.card}>
        <Text style={shared.subtitle}>Смена пароля</Text>
        <TextInput
          style={[shared.input, { marginBottom: 8 }]}
          placeholder="Текущий пароль"
          placeholderTextColor={colors.muted}
          secureTextEntry
          value={currentPwd}
          onChangeText={setCurrentPwd}
          autoCapitalize="none"
        />
        <TextInput
          style={[shared.input, { marginBottom: 8 }]}
          placeholder="Новый пароль"
          placeholderTextColor={colors.muted}
          secureTextEntry
          value={newPwd}
          onChangeText={setNewPwd}
          autoCapitalize="none"
        />
        <TextInput
          style={[shared.input, { marginBottom: 12 }]}
          placeholder="Подтвердите новый пароль"
          placeholderTextColor={colors.muted}
          secureTextEntry
          value={confirmPwd}
          onChangeText={setConfirmPwd}
          autoCapitalize="none"
        />
        <TouchableOpacity
          style={[shared.btn, shared.btnPrimary, pwdLoading && { opacity: 0.6 }]}
          onPress={handleChangePassword}
          disabled={pwdLoading}
        >
          <Text style={shared.btnText}>{pwdLoading ? "Сохранение..." : "Изменить пароль"}</Text>
        </TouchableOpacity>
      </View>

      {/* URL сервера */}
      <View style={shared.card}>
        <Text style={shared.subtitle}>URL сервера</Text>
        <TextInput
          style={[shared.input, { marginBottom: 12 }]}
          value={serverUrl}
          onChangeText={setServerUrl}
          autoCapitalize="none"
          placeholder="http://192.168.1.100"
          placeholderTextColor={colors.muted}
        />
        <TouchableOpacity style={[shared.btn, shared.btnSecondary]} onPress={handleSaveUrl}>
          <Text style={shared.btnTextSecondary}>Сохранить URL</Text>
        </TouchableOpacity>
      </View>

      {/* Выход */}
      <TouchableOpacity style={[shared.btn, shared.btnDanger, { marginTop: 8 }]} onPress={logout}>
        <Text style={shared.btnDangerText}>Выйти</Text>
      </TouchableOpacity>

      <View style={{ height: 40 }} />
    </ScrollView>
  );
}
