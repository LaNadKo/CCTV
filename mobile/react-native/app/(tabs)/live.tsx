import { useEffect, useState } from "react";
import { View, Text, ScrollView, TouchableOpacity, StyleSheet, Dimensions } from "react-native";
import { WebView } from "react-native-webview";
import { useAuth } from "../../src/context/AuthContext";
import { getCameras, cameraStreamUrl, Camera } from "../../src/lib/api";
import { colors } from "../../src/theme/colors";
import { shared } from "../../src/theme/styles";

export default function LiveScreen() {
  const { token } = useAuth();
  const [cams, setCams] = useState<Camera[]>([]);
  const [fullscreen, setFullscreen] = useState<number | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!token) return;
    getCameras(token)
      .then(setCams)
      .catch((e) => setError(e.message));
  }, [token]);

  const screenW = Dimensions.get("window").width;

  if (fullscreen !== null) {
    const cam = cams.find((c) => c.camera_id === fullscreen);
    if (!cam) return null;
    return (
      <View style={{ flex: 1, backgroundColor: "#000" }}>
        <WebView
          source={{ uri: cameraStreamUrl(cam.camera_id, token!) }}
          style={{ flex: 1 }}
          javaScriptEnabled={false}
          scalesPageToFit
        />
        <TouchableOpacity
          style={s.closeBtn}
          onPress={() => setFullscreen(null)}
        >
          <Text style={{ color: "#fff", fontSize: 18, fontWeight: "700" }}>X</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <ScrollView style={shared.scroll}>
      <Text style={shared.title}>Трансляция</Text>
      {error ? <Text style={shared.danger}>{error}</Text> : null}
      {cams.length === 0 && !error && <Text style={shared.muted}>Нет доступных камер</Text>}
      {cams.map((cam) => (
        <TouchableOpacity
          key={cam.camera_id}
          style={shared.card}
          onPress={() => setFullscreen(cam.camera_id)}
        >
          <Text style={shared.subtitle}>{cam.name}</Text>
          {cam.location ? <Text style={[shared.muted, { marginBottom: 8 }]}>{cam.location}</Text> : null}
          <View style={{ height: (screenW - 64) * 0.5625, borderRadius: 8, overflow: "hidden" }}>
            <WebView
              source={{ uri: cameraStreamUrl(cam.camera_id, token!) }}
              style={{ flex: 1 }}
              javaScriptEnabled={false}
              scalesPageToFit
              scrollEnabled={false}
            />
          </View>
        </TouchableOpacity>
      ))}
    </ScrollView>
  );
}

const s = StyleSheet.create({
  closeBtn: {
    position: "absolute",
    top: 50,
    right: 20,
    backgroundColor: "rgba(0,0,0,0.6)",
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: "center",
    justifyContent: "center",
  },
});
