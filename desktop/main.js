const { app, BrowserWindow, dialog, ipcMain, Menu, shell } = require("electron");
const fs = require("fs");
const http = require("http");
const net = require("net");
const path = require("path");
const { spawn } = require("child_process");

const RAW_FRONTEND_URL = process.env.RASTER_SVG_FRONTEND_URL || "http://127.0.0.1:8120/";
const DEV_PID_FILE = process.env.RASTER_SVG_DESKTOP_PID_FILE || "";
const BACKEND_HEALTH_TIMEOUT_MS = Number(process.env.RASTER_SVG_BACKEND_TIMEOUT_MS || 45000);

let backendProcess = null;
let runtimeFrontendUrl = resolveDesktopFrontendUrl(RAW_FRONTEND_URL);
let runtimeServiceUrl = resolveServiceUrl(RAW_FRONTEND_URL);

function resolveServiceUrl(rawUrl) {
  const fallback = "http://127.0.0.1:8120/";
  try {
    const url = new URL(rawUrl || fallback);
    url.pathname = "/";
    url.search = "";
    url.hash = "";
    return url.toString();
  } catch {
    return fallback;
  }
}

function resolveDesktopFrontendUrl(rawUrl) {
  const fallback = "http://127.0.0.1:8120/static/desktop.html";
  try {
    const url = new URL(rawUrl || "http://127.0.0.1:8120/");
    if (url.pathname === "/" || url.pathname === "") {
      url.pathname = "/static/desktop.html";
      url.search = "";
      url.hash = "";
    }
    return url.toString();
  } catch {
    return fallback;
  }
}

function shouldLaunchPackagedBackend() {
  if (process.argv.includes("--dev") || process.env.RASTER_SVG_SKIP_BACKEND_LAUNCH === "1") {
    return false;
  }
  return app.isPackaged || process.env.RASTER_SVG_PACKAGED_BACKEND === "1";
}

function findFreePort(host = "127.0.0.1") {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, host, () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 8120;
      server.close(() => resolve(port));
    });
  });
}

function waitForBackendHealth(serviceUrl, timeoutMs = BACKEND_HEALTH_TIMEOUT_MS) {
  const healthUrl = new URL("/health", serviceUrl).toString();
  const startedAt = Date.now();

  return new Promise((resolve, reject) => {
    const poll = () => {
      const request = http.get(healthUrl, { timeout: 3000 }, (response) => {
        response.resume();
        if (response.statusCode && response.statusCode >= 200 && response.statusCode < 300) {
          resolve();
          return;
        }
        retry();
      });
      request.on("timeout", () => {
        request.destroy();
        retry();
      });
      request.on("error", retry);
    };

    const retry = () => {
      if (Date.now() - startedAt >= timeoutMs) {
        reject(new Error(`Backend health check timed out at ${healthUrl}`));
        return;
      }
      setTimeout(poll, 500);
    };

    poll();
  });
}

function resolvePackagedBackendPath() {
  const executableName = process.platform === "win32" ? "raster-svg-api.exe" : "raster-svg-api";
  const candidates = [
    path.join(process.resourcesPath || "", "backend", "raster-svg-api", executableName),
    path.join(process.resourcesPath || "", "backend", executableName),
    path.join(__dirname, "..", "dist", "backend", "raster-svg-api", executableName),
    path.join(__dirname, "..", "dist", "backend", executableName),
  ];
  return candidates.find((candidate) => candidate && fs.existsSync(candidate)) || candidates[0];
}

function createBackendLogStream() {
  const logDir = path.join(app.getPath("userData"), "logs");
  fs.mkdirSync(logDir, { recursive: true });
  return fs.createWriteStream(path.join(logDir, "backend.log"), { flags: "a" });
}

async function launchPackagedBackendIfNeeded() {
  if (!shouldLaunchPackagedBackend()) {
    return;
  }

  const backendPath = resolvePackagedBackendPath();
  if (!fs.existsSync(backendPath)) {
    throw new Error(`Packaged backend was not found at ${backendPath}`);
  }

  const host = "127.0.0.1";
  const port = await findFreePort(host);
  const serviceUrl = `http://${host}:${port}/`;
  const appConfigDir = app.getPath("userData");
  const artifactsDir = path.join(appConfigDir, "artifacts", "runs");
  fs.mkdirSync(artifactsDir, { recursive: true });

  const logStream = createBackendLogStream();
  logStream.write(`\n[${new Date().toISOString()}] launching ${backendPath} on ${serviceUrl}\n`);

  backendProcess = spawn(backendPath, [], {
    env: {
      ...process.env,
      APP_HOST: host,
      APP_PORT: String(port),
      APP_CONFIG_DIR: appConfigDir,
      RUN_ARTIFACTS_DIR: artifactsDir,
      UVICORN_LOG_LEVEL: process.env.UVICORN_LOG_LEVEL || "info",
    },
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });

  backendProcess.stdout.pipe(logStream, { end: false });
  backendProcess.stderr.pipe(logStream, { end: false });
  backendProcess.on("exit", (code, signal) => {
    logStream.write(`[${new Date().toISOString()}] backend exited code=${code} signal=${signal}\n`);
    logStream.end();
  });

  runtimeServiceUrl = serviceUrl;
  runtimeFrontendUrl = resolveDesktopFrontendUrl(serviceUrl);
  await waitForBackendHealth(serviceUrl);
}

function stopPackagedBackend() {
  if (!backendProcess || backendProcess.killed) {
    return;
  }
  if (process.platform === "win32") {
    spawn("taskkill", ["/pid", String(backendProcess.pid), "/T", "/F"], {
      stdio: "ignore",
      windowsHide: true,
    });
  } else {
    backendProcess.kill("SIGTERM");
  }
  backendProcess = null;
}

function writeDevPidFile() {
  if (!DEV_PID_FILE) {
    return;
  }
  try {
    fs.writeFileSync(DEV_PID_FILE, `${process.pid}\n`, { encoding: "ascii" });
  } catch (error) {
    console.warn(`Failed to write desktop PID file at ${DEV_PID_FILE}:`, error);
  }
}

function removeDevPidFile() {
  if (!DEV_PID_FILE) {
    return;
  }
  try {
    fs.rmSync(DEV_PID_FILE, { force: true });
  } catch (error) {
    console.warn(`Failed to remove desktop PID file at ${DEV_PID_FILE}:`, error);
  }
}

async function createWindow() {
  const win = new BrowserWindow({
    width: 1600,
    height: 980,
    minWidth: 1200,
    minHeight: 760,
    title: "Shape Studio",
    icon: path.join(__dirname, "assets", process.platform === "win32" ? "icon.ico" : "icon.png"),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  try {
    await win.webContents.session.clearCache();
  } catch (error) {
    console.warn("Failed to clear the desktop HTTP cache:", error);
  }
  await win.loadURL(runtimeFrontendUrl);
  return win;
}

function buildMenu(win) {
  const template = [
    {
      label: "File",
      submenu: [
        {
          label: "Open Desktop Frontend",
          click: async () => {
            await win.loadURL(runtimeFrontendUrl);
          },
        },
        { type: "separator" },
        { role: "quit" },
      ],
    },
    {
      label: "View",
      submenu: [
        { role: "reload" },
        { role: "forceReload" },
        { role: "toggleDevTools" },
        { type: "separator" },
        { role: "resetZoom" },
        { role: "zoomIn" },
        { role: "zoomOut" },
        { role: "togglefullscreen" },
      ],
    },
    {
      label: "Help",
      submenu: [
        {
          label: "Open Service URL In Browser",
          click: async () => {
            await shell.openExternal(runtimeServiceUrl);
          },
        },
      ],
    },
  ];
  const menu = Menu.buildFromTemplate(template);
  Menu.setApplicationMenu(menu);
}

ipcMain.handle("desktop-host-info", async () => {
  return {
    hostMode: "desktop",
    frontendUrl: runtimeFrontendUrl,
    serviceUrl: runtimeServiceUrl,
    platform: process.platform,
  };
});

ipcMain.handle("desktop-open-file", async () => {
  const result = await dialog.showOpenDialog({
    properties: ["openFile"],
    filters: [
      { name: "Images", extensions: ["png", "jpg", "jpeg", "webp", "bmp"] },
      { name: "All Files", extensions: ["*"] },
    ],
  });
  if (result.canceled || result.filePaths.length === 0) {
    return null;
  }
  return result.filePaths[0];
});

app.whenReady().then(async () => {
  writeDevPidFile();
  try {
    await launchPackagedBackendIfNeeded();
  } catch (error) {
    dialog.showErrorBox(
      "Backend startup failed",
      `${error.message}\n\nCheck the backend log under:\n${path.join(app.getPath("userData"), "logs", "backend.log")}`,
    );
    app.quit();
    return;
  }

  const win = await createWindow();
  buildMenu(win);
  app.on("activate", async () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      const nextWin = await createWindow();
      buildMenu(nextWin);
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("will-quit", () => {
  stopPackagedBackend();
  removeDevPidFile();
});
