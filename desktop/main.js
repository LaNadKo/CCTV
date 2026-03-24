const { app, BrowserWindow, Menu, shell } = require("electron");
const path = require("path");
const fs = require("fs");
const http = require("http");
const url = require("url");

const isDev = process.argv.includes("--dev");
let mainWindow = null;
let localServer = null;
let isQuitting = false;

const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    if (!mainWindow.isVisible()) mainWindow.show();
    mainWindow.focus();
  });
}

// Window state persistence
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

// Mime types for local server
const MIME = {
  ".html": "text/html", ".js": "application/javascript", ".css": "text/css",
  ".json": "application/json", ".png": "image/png", ".jpg": "image/jpeg",
  ".svg": "image/svg+xml", ".ico": "image/x-icon", ".webmanifest": "application/manifest+json",
  ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf",
};

function startLocalServer(frontendDir) {
  return new Promise((resolve) => {
    localServer = http.createServer((req, res) => {
      const parsed = url.parse(req.url);
      let filePath = path.join(frontendDir, parsed.pathname === "/" ? "index.html" : parsed.pathname);
      // SPA fallback: if file doesn't exist, serve index.html
      if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
        filePath = path.join(frontendDir, "index.html");
      }
      const ext = path.extname(filePath).toLowerCase();
      const contentType = MIME[ext] || "application/octet-stream";
      try {
        const data = fs.readFileSync(filePath);
        res.writeHead(200, { "Content-Type": contentType });
        res.end(data);
      } catch {
        res.writeHead(404);
        res.end("Not found");
      }
    });
    localServer.listen(0, "127.0.0.1", () => {
      const port = localServer.address().port;
      resolve(port);
    });
  });
}

async function createWindow() {
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
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

  // Load app
  if (isDev) {
    mainWindow.loadURL("http://localhost:5173");
    mainWindow.webContents.openDevTools({ mode: "detach" });
  } else {
    const frontendDir = path.join(process.resourcesPath, "frontend");
    const port = await startLocalServer(frontendDir);
    mainWindow.loadURL(`http://127.0.0.1:${port}`);
  }

  mainWindow.once("ready-to-show", () => mainWindow.show());
  mainWindow.on("close", () => {
    saveWindowState();
  });
  mainWindow.on("closed", () => { mainWindow = null; });

  // Open external links in browser
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  // App menu
  const menuTemplate = [
    {
      label: "CCTV Console",
      submenu: [
        { label: "Настройки сервера", click: () => mainWindow?.webContents.executeJavaScript("document.querySelector('details summary')?.click()") },
        { type: "separator" },
        { label: "Перезагрузить", role: "reload" },
        { label: "DevTools", role: "toggleDevTools" },
        { type: "separator" },
        { label: "Выход", click: () => { isQuitting = true; app.quit(); } },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(menuTemplate));
  return mainWindow;
}

app.whenReady().then(async () => {
  await createWindow();

  app.on("activate", async () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      await createWindow();
      return;
    }
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
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
  if (localServer) {
    localServer.close();
    localServer = null;
  }
});
