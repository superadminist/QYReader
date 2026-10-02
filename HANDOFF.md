# QYReader（启远阅读）2.0 Qt 桌面版交付说明

本文记录当前 Qt + React 重构的真实状态、架构约束、验证证据和剩余发布门禁。它取代旧版“把 Tk 原型落地”的实施前提示词，不再把已删除的 Tk UI 当作当前入口。

## 1. 当前结论

- 正式桌面入口已经切换为 `python -m novelreader.qt_main`，`novelreader.main` 仅转发到同一 Qt 入口。
- 主窗口和独立悬浮窗都由 PySide6 / Qt WebEngine 承载 React 静态产物。
- 前后端通过 QWebChannel 通信，`prototype/src/bridge.d.ts` 是唯一公共契约，当前 `schemaVersion` 为 `1`。
- 书架、导入、阅读、搜索、书签、进度、应用设置和悬浮窗设置已迁入无 UI 的 Python 服务。
- 主窗口和悬浮窗共享唯一的 `SpeechController`、`PlaybackService`、章节位置、字符偏移、阅读进度和 TTS 事件消费入口。
- 旧 Tk 正式 UI、Mixin 页面、`NovelReaderApp`、`ModernMethods` 和 `tkinterdnd2` 依赖已移除；受保护的历史常量文件不属于正式导入图。
- 网页、播客、音频导入和转写仍明确不可用；不创建空书或伪内容。
- 代码重构和阶段 1–5 门禁已经完成；阶段 6 已生成并自动验收 one-file EXE。发布前仍需在恢复正常 QtWebEngine 多进程渲染的图形会话、干净 Windows、真实音频/网络及真实双显示器上补齐环境门禁；未验证项不能写成通过。

## 2. 不可破坏的架构约束

```text
Qt DesktopWindow
  └─ QWebEngineView ── React main surface
            │
            └─ QWebChannel / DesktopBridge
                    ├─ AppPreferencesService
                    ├─ LibraryQueryService
                    ├─ LibraryImportService
                    ├─ ReaderService
                    ├─ PlaybackService ── SpeechController（唯一实例）
                    └─ FloatingReaderService
                              │
                              └─ FloatingReaderWindow
                                   └─ React floating surface
```

后续维护必须继续遵守：

1. 不创建第二个 `SpeechController` 或第二条 TTS 队列消费循环。
2. 主窗口与悬浮窗不各自保存一份播放、章节或进度状态。
3. 公共方法、事件、错误码或字段变更先修改 `prototype/src/bridge.d.ts`，再同步 Python Bridge、JavaScript provider 和测试。
4. 不改变 `library.json` 既有字段语义，不要求用户手工迁移。
5. Qt WebEngine 只加载打包的本地静态资源；请求拦截器继续阻止应用页面发起远程资源请求。Edge TTS 的网络调用位于 Python 朗读引擎，不经过页面。
6. 关闭悬浮窗只关闭显示，不停止朗读；退出主应用才执行统一播放停止、服务关闭和 WebEngine 清理。

## 3. 关键文件

| 文件 | 职责 |
| --- | --- |
| `novelreader/qt_main.py` | Qt 应用正式入口与前端产物缺失提示 |
| `novelreader/qt_host.py` | 主窗口、独立悬浮窗、WebEngine profile、离线拦截、原生拖动/缩放、几何恢复与退出 |
| `novelreader/qt_bridge.py` | QWebChannel slots/signals、schema 响应、异步导入/阅读事件及统一 TTS 事件分发 |
| `novelreader/app_service.py` | 主题、自动打开上次阅读等应用设置；原子写入并保留未知字段 |
| `novelreader/library_service.py` | 脱敏书架查询，不向前端泄露源文件路径 |
| `novelreader/import_service.py` | 文件检查、重复处理、粘贴导入、缓存和源文件备份 |
| `novelreader/reader_service.py` | 阅读会话、分块正文、导航、进度、搜索和书签 |
| `novelreader/playback_service.py` | 唯一播放状态、控制命令、相邻句定位和 TTS 原始事件消费 |
| `novelreader/floating_reader_service.py` | 悬浮窗可见状态、三句上下文、设置和几何持久化 |
| `novelreader/tts_engine.py` | 既有 SAPI5、Edge TTS、MCI、回退及缓存底层能力 |
| `prototype/src/bridge.d.ts` | 唯一前后端契约源 |
| `prototype/src/bridge.js` | Native/demo provider、严格 schema 校验和信号解绑 |
| `prototype/src/App.jsx` | 内容库、阅读器、导入、应用设置及主/悬浮 surface |
| `prototype/src/styles.css` | 主界面、主题、阅读器和悬浮窗样式 |

## 4. 已实现路径

### 内容库与导入

- 真实书架、搜索、最近阅读和空状态；前端只接收脱敏摘要。
- 文件选择、候选确认、大文件确认、重复策略、进度、取消和错误反馈。
- TXT、EPUB、MOBI、AZW3、PDF、DOCX、HTML/HTM 和 ZIP 继续走既有解析器。
- 粘贴文本可创建本地 TXT、写入缓存、加入书架并立即打开。
- 网页正文、播客和音频入口显示不可用说明，不调用伪实现。

### 阅读器

- 异步打开、章节目录、分块正文窗口、按章节/位置/百分比导航和进度保存。
- 搜索与分页结果、书签添加/删除、字号、行距和空行模式。
- 2 万字与 10 万字基准继续使用有界正文窗口和预构建句子索引，没有恢复高频全文扫描。

### 播放与悬浮窗

- 播放、暂停、停止、上一句、下一句、状态广播和当前句高亮。
- 悬浮窗是无 parent 的独立顶层窗口；主窗口最小化时仍可见。
- 默认、最小、放大和长句布局；系统拖动/缩放、置顶、透明度、浅色/米黄/深色背景、字号和双语显示设置。
- 几何在释放/变化后持久化；离线恢复和实时移动后都会限制在可见工作区。
- 重复打开复用同一实例；关闭悬浮窗前后播放快照保持一致。

### 应用外壳

- 自定义单层标题栏、窗口最小化/最大化/关闭和原生拖动/缩放。
- `F11` / `Alt+Enter` 全屏；`Ctrl+Shift+F` 切换悬浮窗；`Ctrl+O` 文件导入；`Ctrl+P`、`Ctrl+S` 和 `+`/`-` 提供阅读快捷操作。
- 白天、护眼、米黄、夜间主题与自动打开上次阅读内容持久化。
- 设置页会准确说明本地数据位置；旧版专用缓存管理页面未伪装为当前可用功能。

## 5. 数据兼容与保护

安装版默认数据根目录是 `<安装目录>\data`；源码运行仍使用 `%APPDATA%\DDNovelReader`：

| 路径 | 内容 |
| --- | --- |
| `library.json` | 书架、阅读进度、书签与设置 |
| `cache\` | 解析后的正文缓存 |
| `cache\sources\` | 导入源文件备份 |
| `tts_cache\` | 语音缓存 |
| `logs\edge-tts.log` | Edge 异常类别、状态码、Retry-After 与退避记录；不记录正文、令牌或完整 URL |

服务层沿用原有字段，缺失的新设置读取默认值；只有用户实际修改设置或导入内容时才写入。写入采用锁和原子替换，损坏或结构错误的数据会 fail closed，不用空数据覆盖原文件。

安装版首次启动且 `data` 不存在时，会先把旧 `%APPDATA%\DDNovelReader` 复制到临时兄弟目录，完整复制成功后再原子切换为 `data`。旧目录不删除；安装器升级和卸载也不删除 `data`。

仓库中的真实样书、个人 `library.json`、缓存、日志、`prototype/node_modules` 和本地包缓存都不是交付源码。任何测试应使用临时 `APPDATA`、`DOUBAO_NOVEL_DATA` 或明确的临时书架，并把截图写到仓库外。

## 6. 当前验证快照

以下结果来自 2026-09-12 当前集成工作区；它们只证明对应命令和环境，不代表尚未执行的发布门禁。

| 范围 | 命令或场景 | 结果 |
| --- | --- | --- |
| Python 全量测试 | `python -m unittest discover -s tests -p "test_*.py"` | 83 项通过，0 失败，Qt 测试未跳过 |
| Bridge / Sites / 阶段 2 契约 | Node 24.19 执行三个 `node --test` 文件 | 28 项通过，0 失败 |
| 前端构建 | Node 24.19 直接执行 Vite | 4,571 个模块构建通过，生成 `prototype/dist/client/index.html` 和 Sites 产物 |
| 真实 Qt 主流程 | `tests/stage3_desktop_qa.py`（此前阶段门禁） | 离线启动、Bridge、窗口控制、真实书架、单层标题栏、退出清理通过 |
| 悬浮窗/DPI | `tests/stage4_desktop_qa.py --dpi 1,1.25,1.5,2`（此前阶段门禁） | 默认/长句/主窗最小化/最小/最大/恢复及四档 DPI 通过；退出后无残留 QtWebEngine PID |
| 2 万字性能 | `python tests/stage3_performance_qa.py` | 本次 open 7.151 ms，窗口 0.019 ms，句子索引 25.593 ms |
| 10 万字性能 | 同上 | 本次 open 10.176 ms，窗口 0.029 ms，句子索引 153.968 ms，窗口字符数 18,432 |
| 旧 UI 残留门禁 | `tests/test_no_legacy_ui.py` | 正式入口不加载 Tk/Tkinterdnd2；旧 UI 模块不存在 |
| PyInstaller one-file | `python -m PyInstaller --clean --noconfirm QYReader.spec`（收敛 DLL 路径） | 构建成功；EXE 约 250 MB，包含 QtWebEngine、语言包和离线前端资源 |
| 冻结包自动验收 | `stage3_desktop_qa.py --executable dist\QYReader.exe --single-process` | 内容库、阅读、搜索、书签、高亮、播放事件、截图和退出清理通过；无外部 Node/Python 子进程；此参数仅用于诊断当前图形会话 |

本机 `PATH` 中的旧 Node 不支持当前 Vite，因此 Node 测试与构建必须使用 Node 20+ 的明确路径或修正 `PATH`。`build.bat` 已加入硬门禁；使用 Node 24.19 复跑已通过。

阶段 4 截图保存在仓库外：

```text
E:\C\Administrator\.codex\visualizations\2026\09\12\01a093cd-3f50-7512-aa0a-25ec83705a95\stage4-dpi-matrix\
```

其中包括 `stage4-default.png`、`stage4-long-sentence.png`、`stage4-main-minimized.png`、`stage4-minimum.png`、`stage4-maximum.png`、`stage4-restored.png` 和三档额外 DPI 截图。

冻结包验收截图位于同级目录的 `stage6-packaged-final-1280x720.png`。当前长时间打包会话中，QtWebEngine 的正常多进程模式无法创建共享图形上下文，源码与冻结包都会停在空白页；此前重启图形会话后阶段 4 的正常多进程矩阵曾完整通过。本次以 `--single-process` 只确认冻结资源、Bridge、业务流程及独立运行能力，不能替代发布前的正常多进程复验。

## 7. 尚需收口的发布门禁

以下项目必须记录真实结果后，才能把 2.0 标记为完整发布：

1. 重启 Windows 图形会话后，以默认 QtWebEngine 多进程模式启动最终 EXE，复跑内容库、导入、阅读、悬浮窗和退出清理；不得把 `--single-process` 诊断结果当作发布通过。
2. 当前 EXE 进程树已确认没有 Node、Vite 开发服务器或外部 Python 解释器；仍需在没有 Python/Node 的干净 Windows Sandbox 或 VM 只复制 EXE 验证一次。
3. 在有可用中文语音、COM 会话和扬声器的正常用户桌面实际听测 SAPI5。冻结包验收已正确返回结构化 `SAPI_PLAYBACK_FAILED`，这证明错误链路而不是扬声器真实出声。
4. 在联网状态听测 Edge TTS，并断网验证回退到 SAPI5；记录语音、设备和网络条件。
5. 在真实双显示器上验证跨屏拖动、拔插显示器、边缘恢复和不同缩放组合。单显示器工作区模拟不能替代此项。

若环境不具备某一项，交付记录应保留“未验证”并说明环境条件，不用单元测试或静态扫描替代。

## 8. 推荐发布命令

```bat
python -m unittest discover -s tests -p "test_*.py"
npm.cmd --prefix prototype run test:bridge
npm.cmd --prefix prototype run test:sites
npm.cmd --prefix prototype run build
python tests\stage3_performance_qa.py
python tests\stage4_desktop_qa.py --node "C:\path\to\node.exe" --screenshot-dir "C:\path\outside\repo\stage4-final" --dpi 1,1.25,1.5,2
build.bat
python tests\stage3_desktop_qa.py --node "C:\path\to\node.exe" --executable "dist\QYReader.exe" --screenshot "C:\path\outside\repo\stage6-final.png"
```

打包完成后不要只检查文件存在或构建退出码，应启动 `dist\QYReader.exe` 执行第 7 节的 EXE 验收。`--single-process` 只能用于定位 QtWebEngine 图形会话问题，不得加入正式启动参数。

## 9. Git 与后续修改边界

- 集成分支使用 `codex/ddnr-integration`。
- 保留用户已有修改，尤其不要覆盖受保护样书或仅有换行差异的历史常量文件。
- 不使用 force、`reset --hard`、`clean` 或批量覆盖工作区。
- 每个提交只包含自身职责文件，并在提交前检查 staged 文件清单。
- 公共契约提交先于 Python Bridge 和 React 实现提交；不要在子分支私自派生第二套 schema 或播放状态。

## 10. 完成判定

满足下列条件后才能宣布项目交付完成：

- Python、Bridge、React 构建和真实桌面回归全部通过；
- 100%、125%、150%、200% DPI 和真实双显示器有证据；
- SAPI5、Edge、断网回退和真实扬声器有证据；
- 2 万字、10 万字长文本性能无回退；
- PyInstaller EXE 在干净环境独立运行，资源完整且退出无残留进程；
- 正式路径没有旧 Tk UI、第二个播放控制器或真实用户数据写入测试仓库。

在此之前，准确状态是“实现已收口，仍有发布环境门禁”，不是“全部验证完成”。
