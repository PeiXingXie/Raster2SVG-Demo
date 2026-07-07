# 打包流程 README

这个目录用于把当前项目构建成普通用户可以双击安装的桌面应用。目标用户不需要安装 Python、Node.js、conda，也不需要打开 terminal 手动启动后端服务。

当前项目的打包方式是：

```text
Electron 桌面壳
+ PyInstaller onedir 打包后的 FastAPI 后端
+ electron-builder 生成系统安装包
```

重要原则：

```text
Windows 安装器应在 Windows 上构建。
macOS 安装包应在 macOS 上构建。
```

原因是本项目包含 PyInstaller 打包的 Python 后端。PyInstaller 通常不是跨平台交叉编译工具，因此 Windows 后端需要在 Windows 上打包，macOS 后端需要在 macOS 上打包。

## 目录说明

```text
packaging/
├── README.packaging.md
├── prepare-package-venv.ps1
├── build-backend.ps1
├── build-desktop.ps1
├── build-windows-installer.ps1
├── build-release-windows.ps1
├── set-version.ps1
├── validate-version.ps1
├── analyze-package-deps.ps1
└── generate-icon.py
```

各文件作用：

- `prepare-package-venv.ps1`：创建干净的 Windows 打包环境 `.venv_package`，只安装运行依赖和 PyInstaller。
- `build-backend.ps1`：在 Windows 上把 Python/FastAPI 后端打包到 `dist/backend/raster-svg-api/`。
- `build-desktop.ps1`：调用 `electron-builder` 生成 Windows 安装器。
- `build-windows-installer.ps1`：Windows 完整构建入口，依次执行版本校验、后端打包、桌面安装器打包。
- `build-release-windows.ps1`：Windows 发布构建入口，先统一版本号，再生成版本化安装器。
- `set-version.ps1`：同步更新 `pyproject.toml`、`desktop/package.json`、`desktop/package-lock.json` 里的版本号。
- `validate-version.ps1`：校验版本号一致，并确保 `appId`、`productName` 没有被误改。
- `analyze-package-deps.ps1`：分析 `.venv_package` 里哪些依赖占空间最大。
- `generate-icon.py`：生成应用图标资源。

目前 Windows 已经有完整 `.ps1` 脚本；macOS 暂时使用手动命令完成最小闭环，后续建议补充 `build-release-macos.sh`。

## 启动原理

安装后的应用启动流程是：

```text
用户打开 Raster to SVG
-> Electron 自动寻找空闲端口
-> Electron 启动内置后端 raster-svg-api
-> Electron 等待 /health 成功
-> Electron 打开 /static/desktop.html
```

Windows 后端文件名是：

```text
raster-svg-api.exe
```

macOS/Linux 后端文件名是：

```text
raster-svg-api
```

`desktop/main.js` 已经按 `process.platform` 选择对应后端文件名。

## 在 Windows 上打包

Windows 平台使用 PowerShell 脚本。

### 第一次打包

在项目根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\build-windows-installer.ps1
```

这条命令会自动：

1. 准备 `.venv_package`
2. 构建后端
3. 安装或检查 Electron 打包依赖
4. 生成 Windows 安装器

如果希望重新创建干净的 `.venv_package`：

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\build-windows-installer.ps1 -RecreatePackageVenv
```

如果 `desktop/node_modules` 已经安装过，可以跳过 `npm install`：

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\build-windows-installer.ps1 -SkipNpmInstall
```

本机验证过的 Windows 优化构建命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\build-windows-installer.ps1 -Python .\.venv_test\Scripts\python.exe -RecreatePackageVenv -SkipNpmInstall
```

### 发布 Windows 新版本

正式发新版时，优先使用 `build-release-windows.ps1`，不要手动分别修改多个版本号。

例如从 `0.1.0` 发布到 `0.1.1`：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\build-release-windows.ps1 -Version 0.1.1 -Python .\.venv_test\Scripts\python.exe -SkipNpmInstall
```

如果 Python 后端依赖发生变化，重新创建干净打包环境：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\build-release-windows.ps1 -Version 0.1.1 -Python .\.venv_test\Scripts\python.exe -RecreatePackageVenv -SkipNpmInstall
```

发布脚本会做三件事：

1. 调用 `set-version.ps1` 统一版本号。
2. 调用 `validate-version.ps1` 校验版本和应用身份。
3. 构建 `dist/installers/Raster to SVG Setup <version>.exe`。

Windows 产物：

```text
dist/backend/raster-svg-api/raster-svg-api.exe
dist/installers/Raster to SVG Setup 0.1.1.exe
dist/installers/win-unpacked/
```

当前验证过的 Windows 安装器大小约为：

```text
Raster to SVG Setup 0.1.0.exe: 156 MB
```

## 在 macOS 上打包

macOS 平台需要在 Mac 电脑上执行。不要在 Windows 上直接构建 macOS 包。

当前 `desktop/package.json` 已经包含 macOS DMG 目标：

```json
"mac": {
  "target": [
    "dmg"
  ]
}
```

但 macOS 还没有专用 `.sh` 脚本，因此先使用下面的手动命令完成最小闭环。

### 1. 准备 Python 打包环境

在项目根目录运行：

```bash
python3 -m venv .venv_package
./.venv_package/bin/python -m pip install --upgrade pip
./.venv_package/bin/python -m pip install -e .
./.venv_package/bin/python -m pip install pyinstaller
```

如果要从干净环境重来：

```bash
rm -rf .venv_package
python3 -m venv .venv_package
./.venv_package/bin/python -m pip install --upgrade pip
./.venv_package/bin/python -m pip install -e .
./.venv_package/bin/python -m pip install pyinstaller
```

### 2. 打包 macOS 后端

在项目根目录运行：

```bash
./.venv_package/bin/python -m PyInstaller \
  --noconfirm \
  --clean \
  --name raster-svg-api \
  --onedir \
  --paths src \
  --add-data "src/deepagents_template/static:deepagents_template/static" \
  --distpath dist/backend \
  --workpath dist/pyinstaller-work \
  --specpath dist/pyinstaller-spec \
  src/deepagents_template/desktop_server.py
```

注意 `--add-data` 的分隔符不同：

```text
Windows: src/deepagents_template/static;deepagents_template/static
macOS:   src/deepagents_template/static:deepagents_template/static
```

打包完成后，macOS 后端产物通常是：

```text
dist/backend/raster-svg-api/raster-svg-api
```

确保后端文件有执行权限：

```bash
chmod +x dist/backend/raster-svg-api/raster-svg-api
```

### 3. 打包 macOS DMG

安装 Electron 打包依赖：

```bash
cd desktop
npm install
```

如果 `desktop/node_modules` 已经存在，并且没有改 Electron/Node 依赖，可以跳过 `npm install`。

构建 DMG：

```bash
npm run dist -- --mac dmg
```

macOS 产物通常在：

```text
dist/installers/Raster to SVG Setup 0.1.0.dmg
dist/installers/mac/
```

### 4. macOS 用户如何安装

把 `.dmg` 文件发给用户：

```text
dist/installers/Raster to SVG Setup 0.1.0.dmg
```

用户步骤：

1. 双击打开 `.dmg`。
2. 把 `Raster to SVG.app` 拖到 `Applications`。
3. 从 `Applications` 打开应用。

如果是未签名内部测试包，macOS 可能提示无法验证开发者。用户可以在系统设置的隐私与安全中允许打开，或右键应用选择打开。

### 5. macOS 正式发布前需要补齐

内部测试可以先使用未签名 DMG。正式分发给外部用户前，建议补齐：

- `desktop/assets/icon.icns`
- Apple Developer ID 代码签名
- notarization 公证
- DMG 签名
- Apple Silicon / Intel 架构策略：`arm64`、`x64` 或 `universal`
- macOS 专用发布脚本，例如 `build-release-macos.sh`

## 覆盖旧版安装的更新能力

Windows 当前采用最小可靠方案：新版安装器覆盖旧版安装。

开发者需要做：

1. 增加版本号，例如 `0.1.0` -> `0.1.1`。
2. 构建新版安装器：`Raster to SVG Setup 0.1.1.exe`。
3. 把新版 `.exe` 发给用户。

用户需要做：

1. 关闭正在运行的 Raster to SVG。
2. 双击新版安装器。
3. 一路按安装向导完成安装。
4. 从开始菜单或桌面快捷方式重新打开应用。

覆盖安装时，程序安装目录会被新版替换；用户配置、API 设置、运行结果和日志默认保留。

macOS 的更新方式目前是重新发新版 `.dmg`，用户把新版 `Raster to SVG.app` 拖入 `Applications` 覆盖旧版。正式产品化后可以再接入 electron-updater 或 Sparkle 类自动更新方案。

不要在普通版本升级时修改下面两个字段：

- `desktop/package.json` -> `build.appId`
- `desktop/package.json` -> `build.productName`

这两个字段决定系统是否把新版识别为同一个应用。当前值应保持为：

```text
appId: com.local.rastertosvg
productName: Raster to SVG
```

`validate-version.ps1` 会在 Windows 构建前检查这些字段，防止误改导致新版变成另一个应用。

如果只想更新版本号但不打包：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\set-version.ps1 -Version 0.1.1
```

如果只想检查版本元数据：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\validate-version.ps1
```

## 用户数据保存在哪里

安装版不会把配置和运行结果写回项目目录。

Windows 上通常位于：

```text
C:\Users\<用户名>\AppData\Roaming\Raster to SVG\
```

macOS 上通常位于：

```text
~/Library/Application Support/Raster to SVG/
```

里面包含：

```text
.frontend_runtime_overrides.json
artifacts/runs/
logs/backend.log
```

如果应用打不开，优先查看对应用户数据目录里的：

```text
logs/backend.log
```

## 卸载行为

Windows 卸载入口由 NSIS 自动提供：

- Windows 设置 -> 应用 -> 已安装的应用
- 开始菜单里的 `Raster to SVG` 卸载快捷方式

交互式卸载时，卸载器会询问是否同时清理用户数据。选择清理时，会删除 AppData 下的保存设置、生成结果和日志。选择保留时，只移除程序文件，用户数据继续保留。

macOS 卸载通常是删除：

```text
/Applications/Raster to SVG.app
```

如果需要清理用户数据，再手动删除：

```text
~/Library/Application Support/Raster to SVG/
```

## 为什么安装包会偏大

安装包包含三部分：

```text
Electron/Chromium 运行时
+ Python 解释器和后端依赖
+ 项目前端静态资源
```

Electron 本身会带 Chromium 和 Node.js，因此空应用也会比较大。

当前后端使用 PyInstaller `onedir` 模式，输出一个后端目录，而不是单个自解压 exe。这个模式通常更适合桌面应用：

- 启动更快
- 更容易排查缺失依赖
- 安装器压缩后体积可接受

## 依赖体积分析

Windows 上运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\analyze-package-deps.ps1
```

报告输出到：

```text
dist/dependency-size-report.md
```

当前 `.venv_package` 已经不默认安装 LangChain 相关依赖。主安装版走直接 OpenAI SDK 的多模态处理链路，因此这些包已移到可选依赖：

```text
deepagents
langchain
langgraph
langchain-openai
anthropic
google-genai
```

如果以后确实要恢复 legacy agent / LangChain 协调模块，再手动安装：

```powershell
.\.venv_package\Scripts\python.exe -m pip install -e ".[agent]"
```

macOS 对应命令是：

```bash
./.venv_package/bin/python -m pip install -e ".[agent]"
```

## 图标

应用图标由 shapes 方案生成，表达“raster 像素块逐步过渡到 shapes/vector path 节点”的概念。

Windows 当前使用：

```text
desktop/assets/icon.ico
desktop/assets/icon.png
```

macOS 正式发布建议补充：

```text
desktop/assets/icon.icns
```

重新生成当前图标：

```powershell
.\.venv_package\Scripts\python.exe .\packaging\generate-icon.py
```

macOS 对应命令：

```bash
./.venv_package/bin/python ./packaging/generate-icon.py
```

## 常见问题

### 1. npm 被 PowerShell 拦截

如果在 Windows 上直接运行 `npm` 报执行策略错误，脚本里已经使用 `npm.cmd` 避免这个问题。

### 2. electron-builder 下载失败

首次构建时，electron-builder 需要下载 Electron 和 NSIS/DMG 相关组件。网络不稳定时可以重跑命令。

### 3. PyInstaller 扫描用户 Python 目录报权限错误

优先使用干净的 `.venv_package` 构建，不要用全局 Python 环境。

如果在受限环境中看到类似下面的错误：

```text
PermissionError: [WinError 5] ... AppData\Roaming\Python\Python312\site-packages
```

说明 PyInstaller 的依赖扫描碰到了系统权限边界。可以在本机正常 PowerShell 里重新运行发布命令，或允许提升权限后重跑构建。

### 4. macOS 打出来的 app 无法启动后端

优先检查：

```text
dist/backend/raster-svg-api/raster-svg-api
```

并确认它有执行权限：

```bash
chmod +x dist/backend/raster-svg-api/raster-svg-api
```

还要确认 `dist/installers/mac/Raster to SVG.app/Contents/Resources/backend/` 下确实包含后端目录。

### 5. 安装包没有代码签名

当前 MVP 适合内部测试。正式发布前建议补齐：

- Windows 代码签名证书
- macOS 签名与 notarization
- 自动更新源
- 发布说明和校验哈希

## 推荐日常命令

Windows 日常本地重打当前版本：

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\build-windows-installer.ps1 -SkipNpmInstall
```

Windows 发布新版本：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\build-release-windows.ps1 -Version 0.1.1 -Python .\.venv_test\Scripts\python.exe -SkipNpmInstall
```

Windows 依赖变化后发布新版本：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\build-release-windows.ps1 -Version 0.1.1 -Python .\.venv_test\Scripts\python.exe -RecreatePackageVenv -SkipNpmInstall
```

macOS 最小打包闭环：

```bash
python3 -m venv .venv_package
./.venv_package/bin/python -m pip install --upgrade pip
./.venv_package/bin/python -m pip install -e .
./.venv_package/bin/python -m pip install pyinstaller
./.venv_package/bin/python -m PyInstaller --noconfirm --clean --name raster-svg-api --onedir --paths src --add-data "src/deepagents_template/static:deepagents_template/static" --distpath dist/backend --workpath dist/pyinstaller-work --specpath dist/pyinstaller-spec src/deepagents_template/desktop_server.py
chmod +x dist/backend/raster-svg-api/raster-svg-api
cd desktop
npm install
npm run dist -- --mac dmg
```

更多背景说明见项目根目录：

```text
docs.installer.md
```
