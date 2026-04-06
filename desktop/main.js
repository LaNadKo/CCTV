const { app, BrowserWindow, Menu, Tray, shell } = require("electron");
const path = require("path");
const fs = require("fs");
const http = require("http");
const url = require("url");

const isDev = process.argv.includes("--dev");
let mainWindow = null;
let localServer = null;
let isQuitting = false;
let tray = null;

app.setAppUserModelId("com.cctv.console");

const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  app.exit(0);
} else {
  app.on("second-instance", async () => {
    if (!mainWindow) {
      await createWindow();
      return;
    }
    showMainWindow();
  });
}

const stateFile = path.join(app.getPath("userData"), "window-state.json");

function loadWindowState() {
  try {
    return JSON.parse(fs.readFileSync(stateFile, "utf-8"));
  } catch {
    return { width: 1200, height: 800 };
  }
}

function saveWindowState() {
  if (!mainWindow) return;
  const bounds = mainWindow.getBounds();
  fs.writeFileSync(stateFile, JSON.stringify(bounds));
}

function showMainWindow() {
  if (!mainWindow) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  if (!mainWindow.isVisible()) mainWindow.show();
  mainWindow.focus();
  mainWindow.webContents.focus();
}

const MIME = {
  ".html": "text/html",
  ".js": "application/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
  ".webmanifest": "application/manifest+json",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
};

const UTF8_MIME_EXTENSIONS = new Set([".html", ".js", ".css", ".json", ".svg", ".webmanifest"]);

function startLocalServer(frontendDir) {
  return new Promise((resolve) => {
    if (localServer && localServer.listening) {
      resolve(localServer.address().port);
      return;
    }

    localServer = http.createServer((req, res) => {
      const parsed = url.parse(req.url);
      let filePath = path.join(frontendDir, parsed.pathname === "/" ? "index.html" : parsed.pathname);
      if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
        filePath = path.join(frontendDir, "index.html");
      }

      const ext = path.extname(filePath).toLowerCase();
      const contentType = MIME[ext] || "application/octet-stream";
      const responseType = UTF8_MIME_EXTENSIONS.has(ext) ? `${contentType}; charset=utf-8` : contentType;

      try {
        let data = fs.readFileSync(filePath);
        if (ext === ".html") {
          const html = data
            .toString("utf-8")
            .replace(/<script id="vite-plugin-pwa:register-sw"[^>]*><\/script>/g, "")
            .replace(
              "</body>",
              `<script>
                (async () => {
                  try {
                    if ("serviceWorker" in navigator) {
                      const registrations = await navigator.serviceWorker.getRegistrations();
                      await Promise.all(registrations.map((registration) => registration.unregister()));
                    }
                    if ("caches" in window) {
                      const keys = await caches.keys();
                      await Promise.all(keys.map((key) => caches.delete(key)));
                    }
                  } catch {}
                })();
              </script></body>`
            );
          data = Buffer.from(html, "utf-8");
        }
        res.writeHead(200, {
          "Content-Type": responseType,
          "Cache-Control": "no-store, no-cache, must-revalidate",
          Pragma: "no-cache",
          Expires: "0",
        });
        res.end(data);
      } catch {
        res.writeHead(404);
        res.end("Not found");
      }
    });

    localServer.once("error", (error) => {
      console.error("Failed to start local frontend server", error);
    });

    localServer.listen(0, "127.0.0.1", () => resolve(localServer.address().port));
  });
}

async function createWindow() {
  if (mainWindow) {
    showMainWindow();
    return mainWindow;
  }

  const state = loadWindowState();

  mainWindow = new BrowserWindow({
    width: state.width,
    height: state.height,
    x: state.x,
    y: state.y,
    minWidth: 400,
    minHeight: 600,
    title: "CCTV Console",
    icon: path.join(__dirname, "build", "icon.png"),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
    show: false,
    backgroundColor: "#0b1021",
  });

  try {
    await mainWindow.webContents.session.clearStorageData({ storages: ["serviceworkers", "cachestorage"] });
    await mainWindow.webContents.session.clearCache();
  } catch (error) {
    console.warn("Failed to clear Electron web cache", error);
  }

  if (isDev) {
    mainWindow.loadURL("http://localhost:5173");
    mainWindow.webContents.openDevTools({ mode: "detach" });
  } else {
    const frontendDir = path.join(process.resourcesPath, "frontend");
    const port = await startLocalServer(frontendDir);
    mainWindow.loadURL(`http://127.0.0.1:${port}`);
  }

  mainWindow.once("ready-to-show", () => mainWindow.show());
  mainWindow.on("close", (event) => {
    saveWindowState();
    if (!isQuitting) {
      event.preventDefault();
      mainWindow.hide();
    }
  });
  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  mainWindow.webContents.setWindowOpenHandler(({ url: targetUrl }) => {
    shell.openExternal(targetUrl);
    return { action: "deny" };
  });

  const menuTemplate = [
    {
      label: "CCTV Console",
      submenu: [
        {
          label: "Настройки сервера",
          click: () => mainWindow?.webContents.executeJavaScript("document.querySelector('details summary')?.click()"),
        },
        { type: "separator" },
        { label: "Перезагрузить", role: "reload" },
        { label: "DevTools", role: "toggleDevTools" },
        { type: "separator" },
        {
          label: "Выход",
          click: () => {
            isQuitting = true;
            app.quit();
          },
        },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(menuTemplate));

  return mainWindow;
}

function ensureTray() {
  if (tray) return tray;

  const iconPath = path.join(__dirname, "build", "icon.png");
  tray = new Tray(iconPath);
  tray.setToolTip("CCTV Console");
  tray.on("double-click", async () => {
    await createWindow();
  });

  const refreshMenu = () => {
    tray.setContextMenu(
      Menu.buildFromTemplate([
        {
          label: "Открыть",
          click: async () => {
            await createWindow();
          },
        },
        {
          label: mainWindow && mainWindow.isVisible() ? "Скрыть в трей" : "Показать окно",
          click: async () => {
            if (!mainWindow) {
              await createWindow();
              return;
            }
            if (mainWindow.isVisible()) {
              mainWindow.hide();
            } else {
              showMainWindow();
            }
          },
        },
        { type: "separator" },
        {
          label: "Выход",
          click: () => {
            isQuitting = true;
            app.quit();
          },
        },
      ])
    );
  };

  refreshMenu();
  return tray;
}

app.whenReady().then(async () => {
  ensureTray();
  await createWindow();

  app.on("activate", async () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      await createWindow();
      return;
    }
    if (mainWindow) {
      showMainWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    isQuitting = true;
    app.quit();
  }
});

app.on("before-quit", () => {
  isQuitting = true;
});

app.on("will-quit", () => {
  isQuitting = true;
  if (tray) {
    tray.destroy();
    tray = null;
  }
  if (localServer) {
    localServer.close();
    localServer = null;
  }
});
