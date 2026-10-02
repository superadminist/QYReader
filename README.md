# QYReader（启远阅读）

<p align="center"><img src="assets/qyreader-icon.png" alt="QYReader 启远阅读图标" width="144"></p>

启远阅读（QYReader）是面向 Windows 的本地小说阅读器。2.x 桌面版使用 **PySide6 / Qt WebEngine** 承载 React 界面，通过 QWebChannel 调用本地 Python 服务；书架、正文、进度和设置默认只保存在本机。

品牌图标以“展开的书页通向远方晨光”为核心意象，深蓝代表沉静阅读，暖金代表探索与启程。仓库保留高清 PNG 源图，并由其生成包含 16/32/48/64/128/256 像素层级的 Windows ICO。

## 当前版本能力

- 内容库：读取现有书架、搜索、最近阅读、空状态和自动打开上次阅读内容。
- 内容导入：支持文件选择、粘贴文本和网页链接；文件格式包括 TXT、MD/Markdown、DOC/DOCX、EPUB、MOBI、AZW3、PDF、HTML/HTM、ZIP。
- 文档与网页：Markdown 保留正文，去掉格式符号、图片、链接地址、元数据和代码块；DOC 支持未加密的 Word 97–2003 二进制文档，DOCX 支持正文及表格文字；网页通过 HTTP/HTTPS 提取文章正文并保存本地副本，导入后可离线阅读、朗读、搜索和保存进度。网页不会执行脚本或读取浏览器登录状态，需登录、验证码或动态加载的页面可复制正文后使用粘贴文本。
- 阅读器：章节目录、分块正文、章节跳转、阅读进度、全文搜索、书签、字号、行距和空行模式；正文支持单击或选中文字后从任意字符位置开始朗读，播放条也可一键平滑定位到当前朗读句。
- 朗读：本地 SAPI5 与 Edge 神经语音，共用唯一的 `SpeechController`；支持播放、暂停、停止、上一句、下一句、语速、音量和当前句高亮。Edge 合成失败时会回退 SAPI5 并持续提示，网络恢复后在句子边界自动切回用户选择的音色；本地语音按真实 SAPI 流编号同步文字，暂停恢复会重读当前句，旧语音流的迟到事件不会提前推动下一句。
- 独立悬浮朗读窗：显示上一句、当前句和下一句，与主窗口共享章节、字符偏移、进度和播放状态；主面板可切换到悬浮朗读，悬浮窗可一键返回主面板；支持系统拖动/缩放、置顶、透明度、字体、背景及几何恢复。
- 桌面窗口：自定义标题栏、最小化、最大化、全屏和 100%–200% DPI 适配。Windows 默认使用 Qt 软件合成，优先避免透明窗口内容闪白，启动配置不额外禁用 Chromium GPU；封面悬停仍保留移动与阴影动画。驱动兼容排查可设置 `QYREADER_RENDER_MODE=software`，同时禁用 Chromium GPU；`hardware` 保留交由 Qt 选择的可选路径。
- 应用设置：白天、护眼、米黄、夜间主题，以及启动时自动打开上次阅读内容。

以下入口当前明确不可用，不会创建伪内容：

- 播客、音频导入或语音转写；
- 账号、云同步和在线书城。

旧版 Tk 界面中的整本音频缓存管理等专用页面尚未在 2.x React 界面开放。底层数据和缓存格式仍保留兼容，但不能把“底层代码存在”理解为“当前界面已经可用”。

## 更新说明

| 版本 | 主要更新 |
| --- | --- |
| [v2.1.7](release-notes/v2.1.7.md) | 调整 Windows 透明窗口合成，处理内容库整块闪白，保留圆角与悬停动画。 |
| [v2.1.6](release-notes/v2.1.6.md) | 悬浮窗新增全文朗读进度，支持通过开关选择纯展示或点击、拖动跳转。 |
| [v2.1.5](release-notes/v2.1.5.md) | 新增 MD、DOC 与网页正文阅读，优化内容库动画、滚动、切换和长目录，调整导入入口顺序。 |
| [v2.1.4](release-notes/v2.1.4.md) | 白天和护眼模式恢复浅灰白界面与蓝紫色按钮，移除整窗绿色配色，保留圆角修复。 |
| [v2.1.3](release-notes/v2.1.3.md) | 统一四种主题配色，增强缩放过程中的主窗口与悬浮窗圆角，并优化透明窗口交互重绘。 |
| [v2.1.2](release-notes/v2.1.2.md) | 补齐夜间主题，新增内容库拖动排序、源文件定位和导入目录记忆。 |
| [v2.1.1](release-notes/v2.1.1.md) | 内容库卡片增加中文右键菜单与“更多”入口，可确认后移出内容库，保留原文件和应用缓存。 |
| [v2.1.0](release-notes/v2.1.0.md) | 支持在正文任意位置单击或选中文字后开始朗读，精确到字符偏移并保留唯一播放控制器。 |
| [v2.0.10](release-notes/v2.0.10.md) | 修复旧 SAPI 流事件被误标成下一句导致的声音文字不同步；暂停恢复后按当前语音流实际首词换句。 |
| [v2.0.9 候选版](release-notes/v2.0.9.md) | 处理句边界暂停事件；用户实测纯本地语音仍会提前跳句，已由 2.0.10 候选版替代。 |
| [v2.0.8](release-notes/v2.0.8.md) | 修复联网语音回退本地后快速暂停/播放导致的跳句；安装版更新包改存入应用数据目录。 |

更早版本请查看 [完整更新历史](CHANGELOG.md) 或 [GitHub Releases](https://github.com/superadminist/QYReader/releases)。每次发布都必须新增 `release-notes/vX.Y.Z.md`，用于生成用户可读的 Release 说明。

## 架构

```text
React 界面（prototype/src）
        │  唯一契约：prototype/src/bridge.d.ts（schemaVersion 1）
        ▼
QWebChannel / DesktopBridge（novelreader/qt_bridge.py）
        │
        ├─ 书架、导入、阅读、设置服务
        ├─ PlaybackService ── 唯一 SpeechController
        └─ FloatingReaderService
                 │
Qt 主窗口 ───────┴────── 独立 Qt 悬浮窗
```

主窗口和悬浮窗使用同一个 Bridge、WebEngine profile、播放服务和 TTS 事件消费入口。正式入口不加载 Tkinter，也不存在隐藏的旧 UI 兼容实例。

## 用户数据与隐私

安装版数据位置（安装目录由用户在安装向导中选择）：

- 书架、设置和阅读进度：`<安装目录>\data\library.json`
- 正文缓存：`<安装目录>\data\cache\`
- 导入源文件备份：`<安装目录>\data\cache\sources\`
- 语音缓存：`<安装目录>\data\tts_cache\`
- Edge 连接诊断：`<安装目录>\data\logs\edge-tts.log`（轮转保留，不含正文、令牌或完整 URL）

安装版首次启动且 `<安装目录>\data` 不存在时，会把旧版多多朗读的 `%APPDATA%\DDNovelReader` 完整复制到新位置，旧目录不会删除。为兼容已有开发数据，源码运行仍使用该历史目录；测试可继续通过 `DOUBAO_NOVEL_DATA` 指定隔离目录。

应用不会上传书架、正文或阅读进度。只有选用 Edge 在线语音时，朗读文本会按 Edge TTS 的工作方式发送给该服务；本地 SAPI5 不需要网络。

升级安装不会覆盖安装目录中的 `data`，卸载也默认保留它。设置更新会保留现有书籍和未知字段。建议升级前备份 `<安装目录>\data`；不要把真实书架、受版权保护的样书或本地缓存提交到 Git。

## 使用

1. 启动后在“内容库”中选择文件或粘贴文本。
2. 打开书籍，通过目录、滚动或搜索定位正文。
3. 使用底部播放条朗读；`Ctrl+P`/`Ctrl+S` 可暂停或停止，`+`/`-` 调整字号。
4. 使用“悬浮朗读”或 `Ctrl+Shift+F` 打开独立窗口。关闭悬浮窗不会停止朗读；主窗口最小化后悬浮窗仍保持可用。
5. `F11` 或 `Alt+Enter` 切换全屏。

## 源码开发

### 环境要求

- Windows 10/11；
- Python 3.10+；
- Node.js 20+（仅前端开发、测试和打包需要；打包后的应用不需要 Node.js）。

### 安装 Python 依赖

```bat
install.bat
```

等价的手动命令：

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 构建前端

仓库中的桌面宿主只加载静态构建产物，不依赖 Vite 开发服务器。首次运行或修改 `prototype/src` 后执行：

```bat
npm.cmd --prefix prototype ci
npm.cmd --prefix prototype run build
```

产物入口必须存在于 `prototype\dist\client\index.html`。

### 运行桌面应用

```bat
run.bat
```

或：

```bat
.venv\Scripts\python.exe -m novelreader.qt_main
```

`novelreader.main` 只保留为兼容入口，并转发到同一个 Qt 主程序。

### 测试

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
npm.cmd --prefix prototype run test:bridge
npm.cmd --prefix prototype run test:sites
npm.cmd --prefix prototype run build
```

长文本基准：

```bat
.venv\Scripts\python.exe tests\stage3_performance_qa.py
```

真实桌面/DPI 验收需要可用的 Windows 图形会话和 Node.js 20+：

```bat
.venv\Scripts\python.exe tests\stage4_desktop_qa.py --node "C:\path\to\node.exe" --screenshot-dir "C:\path\outside\repo\stage4-qa" --dpi 1,1.25,1.5,2
```

截图目录应放在仓库外，避免把测试书架或视觉证据误提交。

## 打包

先安装 Inno Setup 6，再运行以下脚本。它会检查 Node.js 和 Inno Setup、重新构建离线前端、安装固定版本的 PyInstaller，生成快速启动版、单文件兼容版和 Windows 安装包：

```bat
build.bat
```

手动流程为先构建前端、安装打包依赖，再执行：

```bat
.venv\Scripts\python.exe -m pip install -r build-requirements.txt
.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm "QYReader.spec"
```

当前发布产物为 `dist\installer\QYReader-Setup-2.1.7.exe`。安装向导允许选择安装路径和是否创建桌面图标，默认安装到系统 `Program Files\QYReader`，启动安装程序时会自动请求管理员权限。发布前必须实际完成安装、首次数据迁移、覆盖升级和卸载保留数据验证，并检查 WebEngine 静态资源、导入/阅读、窗口退出清理，以及进程树中不存在 Node、Vite 开发服务器或外部 Python 解释器。仅仅“构建成功”不等于桌面验收通过。

推送到 `main` 后，GitHub Actions 的 `Windows installer` 工作流会在 Windows Runner 上运行测试和完整打包，并将安装包及 `SHA256SUMS.txt` 保存为 30 天有效的构建产物。也可以在 GitHub Actions 页面手动触发该工作流；生成文件不会提交进 Git。

## 目录结构

```text
QYReader/
├─ novelreader/
│  ├─ qt_main.py                 # Qt 正式入口
│  ├─ qt_host.py                 # 主窗口、悬浮窗和离线 WebEngine 宿主
│  ├─ qt_bridge.py               # QWebChannel 边界与事件分发
│  ├─ *_service.py               # 设置、书架、导入、阅读、播放和悬浮窗服务
│  ├─ book_loader.py             # 各格式解析
│  ├─ storage.py                 # 既有本地数据与缓存兼容层
│  └─ tts_engine.py              # SAPI5、Edge TTS、MCI 与 SpeechController
├─ prototype/
│  ├─ src/                       # React 界面与唯一 Bridge 契约
│  ├─ tests/                     # Bridge / Sites 测试
│  └─ dist/client/               # Qt 加载的前端构建产物
├─ tests/                        # Python、Qt、性能与真实桌面验收
├─ installer/QYReader.iss        # Inno Setup 安装器定义
├─ requirements.txt
├─ run.bat
├─ build.bat
└─ QYReader.spec
```

## 已知环境边界

- SAPI5 和真实扬声器播放依赖当前 Windows 用户的语音包、COM 会话和音频设备；CI 或受限桌面会话不能替代实机听音。
- Edge TTS 和断网回退需要分别在联网与断网状态验证。
- 双显示器验收需要真实的第二块屏幕；单屏上的几何单元测试不能替代它。
- 打包后“不依赖本机 Python”的严格证明应在没有 Python/Node 的干净 Windows 环境中完成。

## 许可证

MIT License
