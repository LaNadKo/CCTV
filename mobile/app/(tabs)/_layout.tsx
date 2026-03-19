import { Tabs } from "expo-router";
import { Text } from "react-native";
import { useAuth } from "../../src/context/AuthContext";
import { colors } from "../../src/theme/colors";

function icon(emoji: string) {
  return ({ focused }: { focused: boolean }) => (
    <Text style={{ fontSize: 20, opacity: focused ? 1 : 0.5 }}>{emoji}</Text>
  );
}

export default function TabsLayout() {
  const { user } = useAuth();
  const isAdmin = user?.role_id === 1;
  const isUser = user?.role_id === 1 || user?.role_id === 2;

  return (
    <Tabs
      screenOptions={{
        headerStyle: { backgroundColor: colors.card, elevation: 0, shadowOpacity: 0 },
        headerTintColor: colors.text,
        headerTitleStyle: { fontWeight: "700" },
        tabBarStyle: {
          backgroundColor: colors.card,
          borderTopColor: colors.border,
          borderTopWidth: 1,
          height: 60,
          paddingBottom: 8,
        },
        tabBarActiveTintColor: colors.accent,
        tabBarInactiveTintColor: colors.muted,
        tabBarLabelStyle: { fontSize: 11, fontWeight: "600" },
      }}
    >
      <Tabs.Screen name="live" options={{ title: "Live", tabBarIcon: icon("\u{1F4F9}") }} />
      <Tabs.Screen name="recordings" options={{ title: "Записи", tabBarIcon: icon("\u{1F4BC}") }} />
      <Tabs.Screen name="reviews" options={{ title: "Ревью", tabBarIcon: icon("\u{2705}"), href: isUser ? "/(tabs)/reviews" : null }} />
      <Tabs.Screen name="cameras" options={{ title: "Камеры", tabBarIcon: icon("\u{1F3A5}"), href: isAdmin ? "/(tabs)/cameras" : null }} />
      <Tabs.Screen name="groups" options={{ title: "Группы", tabBarIcon: icon("\u{1F4C1}") }} />
      <Tabs.Screen name="persons" options={{ title: "Персоны", tabBarIcon: icon("\u{1F464}"), href: isAdmin ? "/(tabs)/persons" : null }} />
      <Tabs.Screen name="reports" options={{ title: "Отчёты", tabBarIcon: icon("\u{1F4CA}"), href: isUser ? "/(tabs)/reports" : null }} />
      <Tabs.Screen name="processors" options={{ title: "Процессоры", tabBarIcon: icon("\u{2699}\u{FE0F}"), href: isAdmin ? "/(tabs)/processors" : null }} />
      <Tabs.Screen name="users" options={{ title: "Пользователи", tabBarIcon: icon("\u{1F465}"), href: isAdmin ? "/(tabs)/users" : null }} />
      <Tabs.Screen name="apikeys" options={{ title: "Ключи", tabBarIcon: icon("\u{1F511}"), href: isAdmin ? "/(tabs)/apikeys" : null }} />
      <Tabs.Screen name="settings" options={{ title: "Настройки", tabBarIcon: icon("\u{2699}\u{FE0F}") }} />
    </Tabs>
  );
}
