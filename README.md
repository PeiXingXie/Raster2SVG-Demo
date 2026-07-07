# Raster to SVG

Raster to SVG 是一个把普通位图图片转换为可编辑 SVG 的桌面/网页应用原型。本 README 是项目主入口：先用几分钟了解项目，再按你的角色跳到对应文档。

当前项目已经具备 Windows 安装器闭环：产品用户可以通过安装包安装应用，新版安装器可以覆盖旧版安装，并默认保留用户数据。

## 快速跳转

| 你的角色 | 应该阅读 | 你会做什么 |
| --- | --- | --- |
| 产品用户 | 本文的“产品用户如何使用” | 安装应用、填写 API 配置、上传图片、更新或卸载 |
| 开发者 | [README.developer.md](./README.developer.md) 和 [docs.development.md](./docs.development.md) | 从源码启动 Web/桌面开发版，调试后端和前端 |
| 发布维护者 | [packaging/README.packaging.md](./packaging/README.packaging.md) 和 [docs.installer.md](./docs.installer.md) | 构建版本化安装器，发布新版覆盖旧版 |
| 桌面壳调试 | [desktop/README.desktop.md](./desktop/README.desktop.md) | 调试 Electron 启动、URL 解析和桌面端问题 |
| 迁移部署 | [quick-start/README.quick-start.md](./quick-start/README.quick-start.md) | 打包源码、迁移到另一台机器、启动服务 |

## 项目简介

这个项目的目标是把 raster 图片转换为更容易编辑、复用和检查的 SVG 结构。

典型流程是：

```text
上传 raster 图片
-> 模型识别图像中的对象、区域和几何关系
-> 后端生成结构化转换结果
-> 前端展示预览、过程信息和 SVG 产物
-> 用户导出或继续编辑 SVG
```

当前应用形态包括：

- FastAPI 后端
- Web 前端
- Electron 桌面壳
- Windows NSIS 安装器

## 产品用户如何使用

产品用户不需要安装 Python、Node.js 或开发环境。

### 第一次安装

拿到安装器后，双击运行：

```text
Raster to SVG Setup 0.1.0.exe
```

安装时可以选择安装目录，也可以直接使用默认目录。

安装完成后，从开始菜单或桌面快捷方式打开：

```text
Raster to SVG
```

### 基本使用流程

1. 打开 Raster to SVG。
2. 在应用界面里填写 API Key / Base URL。
3. 上传需要转换的图片。
4. 启动转换。
5. 查看生成结果、运行日志和 SVG 产物。

安装版会自动启动内置后端，用户不需要打开 terminal，也不需要手动运行服务。

### 更新到新版

如果已经安装过旧版，收到新版安装器后：

1. 关闭正在运行的 Raster to SVG。
2. 双击新版安装器，例如：

```text
Raster to SVG Setup 0.1.1.exe
```

3. 按安装向导完成安装。
4. 重新打开应用。

新版安装器会覆盖旧程序文件。用户配置、API 设置、生成结果和日志默认保留。

### 卸载

可以从 Windows 设置或开始菜单卸载：

```text
Windows 设置 -> 应用 -> 已安装的应用 -> Raster to SVG
```

交互式卸载时，卸载器会询问是否同时清理用户数据。选择保留时，只删除程序文件；选择清理时，会删除保存设置、生成结果和日志。

### 用户数据位置

Windows 上用户数据通常位于：

```text
C:\Users\<用户名>\AppData\Roaming\Raster to SVG\
```

常见内容包括：

```text
.frontend_runtime_overrides.json
artifacts/runs/
logs/backend.log
```

如果应用打不开，可以优先查看：

```text
C:\Users\<用户名>\AppData\Roaming\Raster to SVG\logs\backend.log
```

## 开发者如何使用

开发者可以从源码启动 Web 版或桌面开发版。详细说明见：

- [README.developer.md](./README.developer.md)
- [docs.development.md](./docs.development.md)

快速启动 Web 开发版：

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-dev.ps1
```

macOS/Linux:

```bash
chmod +x start-dev.sh
./start-dev.sh
```

启动后通常访问：

```text
http://127.0.0.1:8120/
```

快速启动桌面开发版：

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-dev.ps1 -Desktop
```

macOS/Linux:

```bash
./start-dev.sh --desktop
```

开发环境的 API 配置位于项目根目录 `.env`。如果 `.env` 不存在，启动脚本会基于 `.env.example` 创建。

至少需要检查：

```env
API_KEY=your-real-api-key
BASE_URL=https://your-real-api-base-url/v1
API_PROVIDER=openai_compatible
API_FORMAT=openai_chat_completions
```

没有真实 API 配置时，前端页面仍可打开，但实际模型转换会失败。

## 构建安装包

Windows 安装包由 `packaging/` 目录下的脚本生成。详细说明见：

- [packaging/README.packaging.md](./packaging/README.packaging.md)
- [docs.installer.md](./docs.installer.md)

构建当前版本安装器：

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\build-windows-installer.ps1 -SkipNpmInstall
```

构建可发布的新版本安装器，例如发布 `0.1.1`：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\build-release-windows.ps1 -Version 0.1.1 -Python .\.venv_test\Scripts\python.exe -SkipNpmInstall
```

如果 Python 后端依赖发生变化：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\build-release-windows.ps1 -Version 0.1.1 -Python .\.venv_test\Scripts\python.exe -RecreatePackageVenv -SkipNpmInstall
```

输出位置：

```text
dist/installers/Raster to SVG Setup <version>.exe
```

## 当前平台状态

Windows：

- 已完成安装器最小闭环
- 支持自定义安装目录
- 支持卸载
- 卸载时可选择是否清理用户数据
- 支持新版安装器覆盖旧版安装

macOS/Linux：

- 开发启动脚本已提供
- Electron 配置里已有 `dmg`、`AppImage`、`deb` 目标
- 正式安装包仍需要在对应系统上构建、签名、测试和发布

## 文档入口

除主 README 外，项目自有 README 都带有语义后缀：

- [README.developer.md](./README.developer.md)：开发者入口文档
- [packaging/README.packaging.md](./packaging/README.packaging.md)：打包、版本发布、覆盖安装、依赖体积说明
- [desktop/README.desktop.md](./desktop/README.desktop.md)：Electron 桌面壳说明
- [quick-start/README.quick-start.md](./quick-start/README.quick-start.md)：迁移、部署和目标机器 bootstrap

其他详细文档：

- [docs.development.md](./docs.development.md)：详细开发环境、启动方式和故障排查
- [docs.installer.md](./docs.installer.md)：安装器实现和已安装模式说明

## 推荐阅读路径

产品用户：

1. 阅读本 README 的“产品用户如何使用”。
2. 安装 `Raster to SVG Setup <version>.exe`。
3. 打开应用并填写 API 配置。

开发者：

1. 阅读 [README.developer.md](./README.developer.md)。
2. 再阅读 [docs.development.md](./docs.development.md)。
3. 用 `start-dev` 脚本启动开发环境。

发布维护者：

1. 阅读 [packaging/README.packaging.md](./packaging/README.packaging.md)。
2. 使用 `build-release-windows.ps1` 构建版本化安装器。
3. 发布新版安装器给用户覆盖安装。
