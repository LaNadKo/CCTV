const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  platform: process.platform,
  isElectron: true,
  defaultApiUrl: process.env.CCTV_DEFAULT_API_URL || "http://127.0.0.1:8000",
});
