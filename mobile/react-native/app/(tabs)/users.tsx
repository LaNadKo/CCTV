import React, { useEffect, useState, useCallback } from "react";
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  TextInput,
  Alert,
  ActivityIndicator,
  RefreshControl,
} from "react-native";
import { useAuth } from "../../src/context/AuthContext";
import { colors } from "../../src/theme/colors";
import { shared } from "../../src/theme/styles";
import {
  adminListUsers,
  adminCreateUser,
  adminDeleteUser,
  adminSetUserRole,
} from "../../src/lib/api";

interface UserOut {
  user_id: number;
  login: string;
  role_id: number;
  must_change_password: boolean;
}

const ROLES: { id: number; label: string; color: string }[] = [
  { id: 1, label: "Админ", color: colors.warning },
  { id: 2, label: "Пользователь", color: colors.accent },
  { id: 3, label: "Наблюдатель", color: colors.muted },
];

function roleBadge(roleId: number) {
  const r = ROLES.find((r) => r.id === roleId);
  return r || { label: "Неизвестно", color: colors.muted };
}

export default function UsersScreen() {
  const { token, user: currentUser } = useAuth();

  const [users, setUsers] = useState<UserOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const [showCreate, setShowCreate] = useState(false);
  const [newLogin, setNewLogin] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRoleId, setNewRoleId] = useState(2);
  const [creating, setCreating] = useState(false);

  const [expandedId, setExpandedId] = useState<number | null>(null);

  const fetchUsers = useCallback(async () => {
    if (!token) return;
    try {
      const data = await adminListUsers(token);
      setUsers(data);
    } catch (e: any) {
      Alert.alert("Ошибка", e.message || "Не удалось загрузить пользователей");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [token]);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  const onRefresh = () => {
    setRefreshing(true);
    fetchUsers();
  };

  const handleCreate = async () => {
    if (!newLogin.trim() || !newPassword.trim()) {
      Alert.alert("Ошибка", "Введите логин и пароль");
      return;
    }
    setCreating(true);
    try {
      await adminCreateUser(token!, newLogin.trim(), newPassword.trim(), newRoleId);
      setNewLogin("");
      setNewPassword("");
      setNewRoleId(2);
      setShowCreate(false);
      fetchUsers();
    } catch (e: any) {
      Alert.alert("Ошибка", e.message || "Не удалось создать пользователя");
    } finally {
      setCreating(false);
    }
  };

  const handleSetRole = async (userId: number, roleId: number) => {
    try {
      await adminSetUserRole(token!, userId, roleId);
      fetchUsers();
    } catch (e: any) {
      Alert.alert("Ошибка", e.message || "Не удалось изменить роль");
    }
  };

  const handleDelete = (userId: number, login: string) => {
    Alert.alert(
      "Удалить пользователя",
      `Вы уверены, что хотите удалить «${login}»?`,
      [
        { text: "Отмена", style: "cancel" },
        {
          text: "Удалить",
          style: "destructive",
          onPress: async () => {
            try {
              await adminDeleteUser(token!, userId);
              if (expandedId === userId) setExpandedId(null);
              fetchUsers();
            } catch (e: any) {
              Alert.alert("Ошибка", e.message || "Не удалось удалить пользователя");
            }
          },
        },
      ]
    );
  };

  if (loading) {
    return (
      <View style={[shared.container, { justifyContent: "center", alignItems: "center" }]}>
        <ActivityIndicator size="large" color={colors.accent} />
      </View>
    );
  }

  return (
    <View style={shared.container}>
      <ScrollView
        style={shared.scroll}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
      >
        <Text style={shared.title}>Пользователи</Text>

        <TouchableOpacity
          style={[shared.btn, shared.btnPrimary, { marginBottom: 16 }]}
          onPress={() => setShowCreate(!showCreate)}
        >
          <Text style={shared.btnText}>
            {showCreate ? "Отмена" : "Создать пользователя"}
          </Text>
        </TouchableOpacity>

        {showCreate && (
          <View style={[shared.card, { marginBottom: 16 }]}>
            <Text style={shared.label}>Логин</Text>
            <TextInput
              style={shared.input}
              value={newLogin}
              onChangeText={setNewLogin}
              placeholder="Логин"
              placeholderTextColor={colors.muted}
              autoCapitalize="none"
            />

            <Text style={shared.label}>Пароль</Text>
            <TextInput
              style={shared.input}
              value={newPassword}
              onChangeText={setNewPassword}
              placeholder="Пароль"
              placeholderTextColor={colors.muted}
              secureTextEntry
            />

            <Text style={shared.label}>Роль</Text>
            <View style={[shared.row, { marginBottom: 12 }]}>
              {ROLES.map((r) => (
                <TouchableOpacity
                  key={r.id}
                  style={[
                    shared.pill,
                    {
                      marginRight: 8,
                      backgroundColor: newRoleId === r.id ? r.color : colors.inputBg,
                    },
                  ]}
                  onPress={() => setNewRoleId(r.id)}
                >
                  <Text
                    style={[
                      shared.pillText,
                      {
                        color: newRoleId === r.id ? "#fff" : colors.text,
                        fontWeight: newRoleId === r.id ? "700" : "400",
                      },
                    ]}
                  >
                    {r.label}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>

            <TouchableOpacity
              style={[shared.btn, shared.btnPrimary]}
              onPress={handleCreate}
              disabled={creating}
            >
              <Text style={shared.btnText}>
                {creating ? "Создание..." : "Создать"}
              </Text>
            </TouchableOpacity>
          </View>
        )}

        {users.length === 0 && (
          <Text style={shared.muted}>Нет пользователей</Text>
        )}

        {users.map((u) => {
          const badge = roleBadge(u.role_id);
          const isExpanded = expandedId === u.user_id;
          const isSelf = currentUser?.user_id === u.user_id;

          return (
            <TouchableOpacity
              key={u.user_id}
              style={[shared.card, { marginBottom: 12 }]}
              onPress={() => setExpandedId(isExpanded ? null : u.user_id)}
              activeOpacity={0.7}
            >
              <View style={shared.row}>
                <View style={{ flex: 1 }}>
                  <View style={shared.row}>
                    <Text style={{ color: colors.text, fontSize: 16, fontWeight: "600" }}>
                      {u.login}
                    </Text>
                    {u.must_change_password && (
                      <View
                        style={[
                          shared.pill,
                          { marginLeft: 8, backgroundColor: colors.warning },
                        ]}
                      >
                        <Text style={[shared.pillText, { color: "#fff", fontSize: 10 }]}>
                          Смена пароля
                        </Text>
                      </View>
                    )}
                  </View>
                </View>
                <View
                  style={[
                    shared.pill,
                    { backgroundColor: badge.color },
                  ]}
                >
                  <Text style={[shared.pillText, { color: "#fff" }]}>
                    {badge.label}
                  </Text>
                </View>
              </View>

              {isExpanded && !isSelf && (
                <View style={{ marginTop: 12 }}>
                  <View style={shared.divider} />
                  <Text style={[shared.label, { marginTop: 8 }]}>Изменить роль</Text>
                  <View style={[shared.row, { marginBottom: 12 }]}>
                    {ROLES.map((r) => (
                      <TouchableOpacity
                        key={r.id}
                        style={[
                          shared.pill,
                          {
                            marginRight: 8,
                            backgroundColor:
                              u.role_id === r.id ? r.color : colors.inputBg,
                          },
                        ]}
                        onPress={() => handleSetRole(u.user_id, r.id)}
                      >
                        <Text
                          style={[
                            shared.pillText,
                            {
                              color: u.role_id === r.id ? "#fff" : colors.text,
                              fontWeight: u.role_id === r.id ? "700" : "400",
                            },
                          ]}
                        >
                          {r.label}
                        </Text>
                      </TouchableOpacity>
                    ))}
                  </View>

                  <TouchableOpacity
                    style={[shared.btn, shared.btnDanger]}
                    onPress={() => handleDelete(u.user_id, u.login)}
                  >
                    <Text style={shared.btnDangerText}>Удалить пользователя</Text>
                  </TouchableOpacity>
                </View>
              )}

              {isExpanded && isSelf && (
                <View style={{ marginTop: 12 }}>
                  <View style={shared.divider} />
                  <Text style={[shared.muted, { marginTop: 8 }]}>
                    Это ваш аккаунт. Управление недоступно.
                  </Text>
                </View>
              )}
            </TouchableOpacity>
          );
        })}
      </ScrollView>
    </View>
  );
}
