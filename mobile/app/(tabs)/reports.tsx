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
  Linking,
} from "react-native";
import { useAuth } from "../../src/context/AuthContext";
import { colors } from "../../src/theme/colors";
import { shared } from "../../src/theme/styles";
import {
  getAppearanceReport,
  appearanceExportUrl,
  listPersons,
} from "../../src/lib/api";

interface PersonOut {
  person_id: number;
  label: string;
}

interface AppearanceItem {
  event_ts: string;
  camera_name: string;
  person_label: string;
  confidence: number;
}

interface ReportResult {
  total: number;
  items: AppearanceItem[];
}

export default function ReportsScreen() {
  const { token } = useAuth();

  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [persons, setPersons] = useState<PersonOut[]>([]);
  const [selectedPersonId, setSelectedPersonId] = useState<number | null>(null);

  const [report, setReport] = useState<ReportResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [personsLoading, setPersonsLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    (async () => {
      try {
        const data = await listPersons(token);
        setPersons(data);
      } catch {
        setPersons([]);
      } finally {
        setPersonsLoading(false);
      }
    })();
  }, [token]);

  const fetchReport = async () => {
    if (!token) return;
    setLoading(true);
    try {
      const params: any = {};
      if (dateFrom.trim()) params.date_from = dateFrom.trim();
      if (dateTo.trim()) params.date_to = dateTo.trim();
      if (selectedPersonId !== null) params.person_id = selectedPersonId;
      const data = await getAppearanceReport(token, params);
      setReport(data);
    } catch (e: any) {
      Alert.alert("Ошибка", e.message || "Не удалось загрузить отчёт");
    } finally {
      setLoading(false);
    }
  };

  const handleExport = (format: string) => {
    if (!token) return;
    const params: any = {};
    if (dateFrom.trim()) params.date_from = dateFrom.trim();
    if (dateTo.trim()) params.date_to = dateTo.trim();
    if (selectedPersonId !== null) params.person_id = selectedPersonId;
    const url = appearanceExportUrl(format, params);
    const separator = url.includes("?") ? "&" : "?";
    Linking.openURL(`${url}${separator}token=${token}`);
  };

  const formatTs = (ts: string) => {
    try {
      const d = new Date(ts);
      return d.toLocaleString("ru-RU");
    } catch {
      return ts;
    }
  };

  return (
    <View style={shared.container}>
      <ScrollView style={shared.scroll}>
        <Text style={shared.title}>Отчёты о появлениях</Text>

        <View style={[shared.card, { marginBottom: 16 }]}>
          <Text style={shared.label}>Дата начала (ГГГГ-ММ-ДД)</Text>
          <TextInput
            style={shared.input}
            value={dateFrom}
            onChangeText={setDateFrom}
            placeholder="2026-01-01"
            placeholderTextColor={colors.muted}
            autoCapitalize="none"
          />

          <Text style={shared.label}>Дата окончания (ГГГГ-ММ-ДД)</Text>
          <TextInput
            style={shared.input}
            value={dateTo}
            onChangeText={setDateTo}
            placeholder="2026-12-31"
            placeholderTextColor={colors.muted}
            autoCapitalize="none"
          />

          <Text style={shared.label}>Персона</Text>
          {personsLoading ? (
            <ActivityIndicator size="small" color={colors.accent} />
          ) : (
            <ScrollView horizontal showsHorizontalScrollIndicator={false}>
              <TouchableOpacity
                style={[
                  shared.pill,
                  {
                    marginRight: 8,
                    backgroundColor:
                      selectedPersonId === null ? colors.accent : colors.inputBg,
                  },
                ]}
                onPress={() => setSelectedPersonId(null)}
              >
                <Text
                  style={[
                    shared.pillText,
                    {
                      color: selectedPersonId === null ? "#fff" : colors.text,
                    },
                  ]}
                >
                  Все
                </Text>
              </TouchableOpacity>
              {persons.map((p) => (
                <TouchableOpacity
                  key={p.person_id}
                  style={[
                    shared.pill,
                    {
                      marginRight: 8,
                      backgroundColor:
                        selectedPersonId === p.person_id
                          ? colors.accent
                          : colors.inputBg,
                    },
                  ]}
                  onPress={() => setSelectedPersonId(p.person_id)}
                >
                  <Text
                    style={[
                      shared.pillText,
                      {
                        color:
                          selectedPersonId === p.person_id ? "#fff" : colors.text,
                      },
                    ]}
                  >
                    {p.label}
                  </Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
          )}

          <TouchableOpacity
            style={[shared.btn, shared.btnPrimary, { marginTop: 16 }]}
            onPress={fetchReport}
            disabled={loading}
          >
            <Text style={shared.btnText}>
              {loading ? "Загрузка..." : "Сформировать отчёт"}
            </Text>
          </TouchableOpacity>
        </View>

        {report && (
          <>
            <View style={[shared.row, { marginBottom: 12 }]}>
              <Text style={{ color: colors.text, fontWeight: "600", fontSize: 16 }}>
                Всего: {report.total}
              </Text>
            </View>

            <View style={[shared.row, { marginBottom: 16, flexWrap: "wrap", gap: 8 }]}>
              <TouchableOpacity
                style={[shared.btn, shared.btnSecondary]}
                onPress={() => handleExport("pdf")}
              >
                <Text style={shared.btnTextSecondary}>Экспорт PDF</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[shared.btn, shared.btnSecondary]}
                onPress={() => handleExport("xlsx")}
              >
                <Text style={shared.btnTextSecondary}>Экспорт XLSX</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[shared.btn, shared.btnSecondary]}
                onPress={() => handleExport("docx")}
              >
                <Text style={shared.btnTextSecondary}>Экспорт DOCX</Text>
              </TouchableOpacity>
            </View>

            {report.items.length === 0 ? (
              <Text style={shared.muted}>Нет данных за указанный период</Text>
            ) : (
              report.items.map((item, idx) => (
                <View key={idx} style={[shared.card, { marginBottom: 10 }]}>
                  <View style={shared.row}>
                    <Text style={{ color: colors.text, fontWeight: "600", flex: 1 }}>
                      {item.person_label}
                    </Text>
                    <Text style={shared.muted}>
                      {(item.confidence * 100).toFixed(1)}%
                    </Text>
                  </View>
                  <Text style={[shared.muted, { marginTop: 4 }]}>
                    {item.camera_name}
                  </Text>
                  <Text style={[shared.muted, { marginTop: 2 }]}>
                    {formatTs(item.event_ts)}
                  </Text>
                </View>
              ))
            )}
          </>
        )}
      </ScrollView>
    </View>
  );
}
