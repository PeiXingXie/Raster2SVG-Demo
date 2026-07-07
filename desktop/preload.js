const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("desktopHost", {
  getHostInfo: () => ipcRenderer.invoke("desktop-host-info"),
  openLocalImage: () => ipcRenderer.invoke("desktop-open-file"),
});
