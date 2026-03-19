const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  platform: process.platform,
  isElectron: true,
  defaultApiUrl: process.env.CCTV_DEFAULT_API_URL || "http://192.168.50.62:8000",
});
