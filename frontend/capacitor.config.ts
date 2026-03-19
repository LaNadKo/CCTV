import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "com.cctv.console",
  appName: "CCTV Console",
  webDir: "dist",
  server: {
    // For development: point to your backend server
    // url: "http://192.168.1.100:5173",
    // cleartext: true,

    // For production: use bundled web assets
    androidScheme: "https",
  },
  plugins: {
    StatusBar: {
      style: "DARK",
      backgroundColor: "#0f172a",
    },
  },
};

export default config;
