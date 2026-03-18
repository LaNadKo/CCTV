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
  Modal,
} from "react-native";
import { useAuth } from "../../src/context/AuthContext";
import { colors } from "../../src/theme/colors";
import { shared } from "../../src/theme/styles";
import {
  listGroups,
  createGroup,
  getGroup,
  updateGroup,
  deleteGroup,
  assignCameraToGroup,
  unassignCameraFromGroup,
  getCameras,
} from "../../src/lib/api";

interface GroupOut {
  group_id: number;
  name: string;
  description: string | null;
  created_at: string;
  camera_count: number;
}

interface GroupCameraOut {
  camera_id: number;
  name: string;
}

interface Camera {
  camera_id: number;
  name: string;
}

export default function GroupsScreen() {
  const { token, user } = useAuth();
  const isAdmin = user?.role_id === 1;

  const [groups, setGroups] = useState<GroupOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [detailCameras, setDetailCameras] = useState<GroupCameraOut[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);

  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [creating, setCreating] = useState(false);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");

  const [allCameras, setAllCameras] = useState<Camera[]>([]);
  const [showAssign, setShowAssign] = useState(false);
  const [assignGroupId, setAssignGroupId] = useState<number | null>(null);

  const fetchGroups = useCallback(async () => {
    if (!token) return;
    try {
      const data = await listGroups(token);
      setGroups(data);
    } catch (e: any) {
      Alert.alert("Ошибка", e.message || "Не удалось загрузить группы");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [token]);

  useEffect(() => {
    fetchGroups();
  }, [fetchGroups]);

  const onRefresh = () => {
    setRefreshing(true);
    fetchGroups();
  };

  const toggleExpand = async (groupId: number) => {
    if (expandedId === groupId) {
      setExpandedId(null);
      return;
    }
    setExpandedId(groupId);
    setDetailLoading(true);
    try {
      const detail = await getGroup(token!, groupId);
      setDetailCameras(detail.cameras || []);
    } catch {
      setDetailCameras([]);
    } finally {
      setDetailLoading(false);
    }
  };

  const handleCreate = async () => {
    if (!newName.trim()) {
      Alert.alert("Ошибка", "Введите название группы");
      return;
    }
    setCreating(true);
    try {
      await createGroup(token!, newName.trim(), newDesc.trim() || undefined);
      setNewName("");
      setNewDesc("");
      setShowCreate(false);
      fetchGroups();
    } catch (e: any) {
      Alert.alert("Ошибка", e.message || "Не удалось создать группу");
    } finally {
      setCreating(false);
    }
  };

  const handleUpdate = async (groupId: number) => {
    try {
      await updateGroup(token!, groupId, {
        name: editName.trim() || undefined,
        description: editDesc.trim() || undefined,
      });
      setEditingId(null);
      fetchGroups();
    } catch (e: any) {
      Alert.alert("Ошибка", e.message || "Не удалось обновить группу");
    }
  };

  const handleDelete = (groupId: number, name: string) => {
    Alert.alert("Удалить группу", `Вы уверены, что хотите удалить «${name}»?`, [
      { text: "Отмена", style: "cancel" },
      {
        text: "Удалить",
        style: "destructive",
        onPress: async () => {
          try {
            await deleteGroup(token!, groupId);
            if (expandedId === groupId) setExpandedId(null);
            fetchGroups();
          } catch (e: any) {
            Alert.alert("Ошибка", e.message || "Не удалось удалить группу");
          }
        },
      },
    ]);
  };

  const openAssignModal = async (groupId: number) => {
    setAssignGroupId(groupId);
    setShowAssign(true);
    try {
      const cams = await getCameras(token!);
      setAllCameras(cams);
    } catch {
      setAllCameras([]);
    }
  };

  const handleAssign = async (cameraId: number) => {
    if (!assignGroupId) return;
    try {
      await assignCameraToGroup(token!, assignGroupId, cameraId);
      const detail = await getGroup(token!, assignGroupId);
      setDetailCameras(detail.cameras || []);
      fetchGroups();
    } catch (e: any) {
      Alert.alert("Ошибка", e.message || "Не удалось привязать камеру");
    }
  };

  const handleUnassign = async (groupId: number, cameraId: number) => {
    try {
      await unassignCameraFromGroup(token!, groupId, cameraId);
      const detail = await getGroup(token!, groupId);
      setDetailCameras(detail.cameras || []);
      fetchGroups();
    } catch (e: any) {
      Alert.alert("Ошибка", e.message || "Не удалось отвязать камеру");
    }
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
        <Text style={shared.title}>Группы</Text>

        {isAdmin && (
          <TouchableOpacity
            style={[shared.btn, shared.btnPrimary, { marginBottom: 16 }]}
            onPress={() => setShowCreate(!showCreate)}
          >
            <Text style={shared.btnText}>
              {showCreate ? "Отмена" : "Создать группу"}
            </Text>
          </TouchableOpacity>
        )}

        {showCreate && (
          <View style={[shared.card, { marginBottom: 16 }]}>
            <Text style={shared.label}>Название</Text>
            <TextInput
              style={shared.input}
              value={newName}
              onChangeText={setNewName}
              placeholder="Название группы"
              placeholderTextColor={colors.muted}
            />
            <Text style={shared.label}>Описание</Text>
            <TextInput
              style={shared.input}
              value={newDesc}
              onChangeText={setNewDesc}
              placeholder="Описание (необязательно)"
              placeholderTextColor={colors.muted}
            />
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

        {groups.length === 0 && (
          <Text style={shared.muted}>Нет групп</Text>
        )}

        {groups.map((g) => (
          <View key={g.group_id} style={[shared.card, { marginBottom: 12 }]}>
            {editingId === g.group_id ? (
              <View>
                <Text style={shared.label}>Название</Text>
                <TextInput
                  style={shared.input}
                  value={editName}
                  onChangeText={setEditName}
                  placeholderTextColor={colors.muted}
                />
                <Text style={shared.label}>Описание</Text>
                <TextInput
                  style={shared.input}
                  value={editDesc}
                  onChangeText={setEditDesc}
                  placeholderTextColor={colors.muted}
                />
                <View style={shared.row}>
                  <TouchableOpacity
                    style={[shared.btn, shared.btnPrimary, { flex: 1, marginRight: 8 }]}
                    onPress={() => handleUpdate(g.group_id)}
                  >
                    <Text style={shared.btnText}>Сохранить</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={[shared.btn, shared.btnSecondary, { flex: 1 }]}
                    onPress={() => setEditingId(null)}
                  >
                    <Text style={shared.btnTextSecondary}>Отмена</Text>
                  </TouchableOpacity>
                </View>
              </View>
            ) : (
              <TouchableOpacity onPress={() => toggleExpand(g.group_id)}>
                <View style={shared.row}>
                  <Text style={{ color: colors.text, fontSize: 16, fontWeight: "600", flex: 1 }}>
                    {g.name}
                  </Text>
                  <View style={shared.pill}>
                    <Text style={shared.pillText}>{g.camera_count} кам.</Text>
                  </View>
                </View>
                {g.description ? (
                  <Text style={[shared.muted, { marginTop: 4 }]}>{g.description}</Text>
                ) : null}
              </TouchableOpacity>
            )}

            {expandedId === g.group_id && editingId !== g.group_id && (
              <View style={{ marginTop: 12 }}>
                <View style={shared.divider} />
                <Text style={[shared.label, { marginTop: 8 }]}>Камеры</Text>
                {detailLoading ? (
                  <ActivityIndicator size="small" color={colors.accent} />
                ) : detailCameras.length === 0 ? (
                  <Text style={shared.muted}>Нет камер в группе</Text>
                ) : (
                  detailCameras.map((c) => (
                    <View key={c.camera_id} style={[shared.row, { marginTop: 6 }]}>
                      <Text style={{ color: colors.text, flex: 1 }}>{c.name}</Text>
                      {isAdmin && (
                        <TouchableOpacity
                          onPress={() => handleUnassign(g.group_id, c.camera_id)}
                        >
                          <Text style={shared.danger}>Отвязать</Text>
                        </TouchableOpacity>
                      )}
                    </View>
                  ))
                )}

                {isAdmin && (
                  <View style={[shared.row, { marginTop: 12 }]}>
                    <TouchableOpacity
                      style={[shared.btn, shared.btnPrimary, { flex: 1, marginRight: 8 }]}
                      onPress={() => openAssignModal(g.group_id)}
                    >
                      <Text style={shared.btnText}>Добавить камеру</Text>
                    </TouchableOpacity>
                    <TouchableOpacity
                      style={[shared.btn, shared.btnSecondary, { flex: 1, marginRight: 8 }]}
                      onPress={() => {
                        setEditingId(g.group_id);
                        setEditName(g.name);
                        setEditDesc(g.description || "");
                      }}
                    >
                      <Text style={shared.btnTextSecondary}>Редактировать</Text>
                    </TouchableOpacity>
                    <TouchableOpacity
                      style={[shared.btn, shared.btnDanger]}
                      onPress={() => handleDelete(g.group_id, g.name)}
                    >
                      <Text style={shared.btnDangerText}>Удалить</Text>
                    </TouchableOpacity>
                  </View>
                )}
              </View>
            )}
          </View>
        ))}
      </ScrollView>

      <Modal visible={showAssign} transparent animationType="slide">
        <View
          style={{
            flex: 1,
            justifyContent: "center",
            backgroundColor: "rgba(0,0,0,0.6)",
            padding: 20,
          }}
        >
          <View style={[shared.card, { maxHeight: "70%" }]}>
            <Text style={[shared.title, { fontSize: 18 }]}>Выберите камеру</Text>
            <ScrollView>
              {allCameras
                .filter(
                  (c) => !detailCameras.some((dc) => dc.camera_id === c.camera_id)
                )
                .map((c) => (
                  <TouchableOpacity
                    key={c.camera_id}
                    style={[shared.row, { paddingVertical: 10 }]}
                    onPress={() => {
                      handleAssign(c.camera_id);
                      setShowAssign(false);
                    }}
                  >
                    <Text style={{ color: colors.text }}>{c.name}</Text>
                  </TouchableOpacity>
                ))}
              {allCameras.filter(
                (c) => !detailCameras.some((dc) => dc.camera_id === c.camera_id)
              ).length === 0 && (
                <Text style={shared.muted}>Нет доступных камер</Text>
              )}
            </ScrollView>
            <TouchableOpacity
              style={[shared.btn, shared.btnSecondary, { marginTop: 12 }]}
              onPress={() => setShowAssign(false)}
            >
              <Text style={shared.btnTextSecondary}>Закрыть</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
    </View>
  );
}
