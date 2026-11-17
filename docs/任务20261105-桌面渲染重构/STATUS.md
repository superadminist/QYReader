# 任务20261105 桌面渲染重构当前状态

## 1. 当前状态

| 项目 | 当前值 |
|---|---|
| 更新时间/最近验证时间 | 2026-11-17 依次完成：启动耗时离线拆解（09:05–09:40）、宿主两批 300/400 本并切开构造段（09:20–09:26）、`edge_tts` 改按需导入（09:30–09:50）、**可见渲染路径打通并完成管线验证（09:40–09:47，甲）**、冒烟过期断言修复并用隐藏批次验证通过（09:51–09:55）。2026-11-16 依次完成：隐藏冒烟通过（15:47）、五批 performance 数据（15:51–16:09）、滚动加规则尝试否证回退（16:33/16:34）、设置面板首用塑形优化（17:04–17:07）、移除 `data-scrolling` 门控（17:20–17:22）、书库滚动剩余成本离线归因（17:45–18:05）、虚拟窗口阈值离线实验（18:10–18:45）、阈值 512→200 落地并重建（18:33–18:45）、宿主批次验证通过（18:46）、`open-reader` 采样加长并验证（18:53）、打开正文 128ms 离线拆解（19:00–19:40，七对照臂，产品零改动）、**阅读页结构空闲预热尝试（19:05–19:40）：离线布局降七成，宿主零收益且把一帧丢进 `library-down`，已回退并重建回 `index-Q-TfAU_F.js`（逐字节同 18:33）**。最近一次真实宿主实测是 19:25 批次（预热产物，页面侧 12 用例 `passed`、退出码 1 仅因系统输入指示窗 1390 条可见性违规）。本轮留存三项产品改动未变：设置空闲预热、移除滚动悬停门控、书库虚拟窗口阈值 512→200；测试工具改动一项：新增 `open-reader-settle` 用例。**本轮新增一条口径修正：离线 tracing 把首次布局抬高约 4 倍（31–45ms vs 宿主 7–8ms），128ms `Task` 不是布局主导。** 20:00 前后转向后端（同一用户"继续"）：新增 `open-split` 诊断相位，在真实宿主页面传输层打点，确认 `readerOpened` 事件 367–419ms 才到、之后渲染只要 30–55ms；根因是 `SpeechController.set_volume` 每次调用都跑 `AudioUtilities.GetAllSessions()`（本机 250–480ms，7 个音频会话）。改动 `novelreader/tts_engine.py`（+39/−9）：值不变不再申请 OS 音量 + 缓存 `ISimpleAudioVolume` 句柄；宿主重复开书 **411→202ms**、字号一次设置往返 **409→55ms**，`tests/test_speech_volume.py` 新增 7 例，全量 325 例通过；前端产物未重建（仍 `index-Q-TfAU_F.js`，`sha256 c68b2f1f…`）。**20:15–20:30 同一主线再进一步**：音量改为按播放状态分流（正在朗读才立即申请 OS 音量，其余只在播放起点落地，SAPI 起点补应用），静音改音量 **184.5ms → 0ms**（真机 7 会话，`oldPathResolved=false` 证明原调用无作用对象），播放中保持即时；开书边车 18 次 `set_volume` 全 0.0ms、`_set_process_volume` 0 次；单测 7→14 例、全量 **332 例通过**。同时更正 19:50 的旧口径：首次开书 `set_volume` 本就只有 0.5–0.8ms，本轮对开书是除隐患而非再省半秒。**11-17 08:55–09:20（用户引用第 8 节第 2 条后"继续"）**：把宿主入口放开到非 300 本（`fixture.py`/`run.py` 的 `--books`·`--menu-books` 扩到 250/300/400/500/600，guard 允许 `performance`，`owner.fixtureBooks` 所有相位写入；`benchmark.mjs` 增采 `libraryDomBefore/After`），并用离线探针在 250/300/400 四臂上确认**全部走虚拟窗口、挂载恒 64→96、Task 219–281ms 无规模趋势**；负向对照（旧阈值 512 产物 @400 本）全量挂 400 张、Task 616ms，证明探针能区分。宿主批次尚待桌面空档，产品代码本轮零改动。**11-17 09:05–09:40（同一"继续"）**：启动耗时已离线拆开——宿主 28 个热缓存批次中位 **3.265s**，其中模块导入 **1.191s**、主窗构造 **1.576s**、首次 showEvent 116ms、事件循环到 `load-started` 228ms、前端加载 101ms；导入里 Qt 全套只 0.21s，`novelreader.qt_host` 连带依赖 0.95s，消融显示 `edge_tts` 一个包占 **0.314s（−29%）**、`pyttsx3` 0.071s 且与 edge 栈重叠；构造的大头是 QtWebEngine profile/page（离屏口径 87%），四个自研服务构造均 ≤0.1ms（懒加载）；冷缓存批次 8.823s 里导入 6.142s 全是磁盘首次读，不可离线拆。测试工具改 1 处：`desktop-lab/qt_host.py` 把产品 `_qa_trace` 的 7 个构造子阶段镜像进 `startup-stages.jsonl`（新事件 `product-stage`），下次宿主批次可切这 1.576s；产品代码本轮零改动。**11-17 09:20–09:26（用户选"丙"）**：一次空档跑完两批宿主——300 本 `…092034-df05bd52`（页面通过、审计因 13 个前台采样里 1 个空读数判 `foreground-attribution-failed`）与 400 本 `…092145-a3fb6fa8`（**审计通过、退出码 0**、可见窗 0、无残留）；两批 `libraryDomBefore/After.cards` 都是 **64/64**、标题含 300/400，证明 400 本仍在虚拟窗口内（全量挂载会是 400），滚动用例与 18:46 基线同值域、无规模趋势；新 `product-stage` 打点已生效，构造段切开——300/400 本构造 **1439.3/1072.5ms**，其中 `view-created→page-created`（`QWebEngineProfile` + 拦截器 + `QWebEnginePage`，`qt_host.py` 436–442）**1369.0/1004.4ms＝95.1%/93.6%**，四个自研服务相关两段合计仅 20.2/23.3ms；据此把上次"差的 1.2s 属平台"定位到 profile/page 这一段（离屏 338ms vs 宿主 1004–1369ms）。启动合计 3168.3/2447.2ms，落在历史区间内，新增 7 条打点未观察到抬升。该轮产品代码零改动。**11-17 09:30–09:50（用户"继续"，即第 8 节第 3 条的甲）**：`edge_tts` 改按需导入——`novelreader/tts_engine.py` 顶层 `try: import edge_tts` 换成哨兵 `_EDGE_TTS_UNLOADED` + `_edge_tts_module()`（首次合成才真正导入），`synth_audio` 改用加载器；`edge_tts = None` 仍是"未安装"的硬信号，SAPI 一次性回退与两个测试桩不受影响。干净子进程 A/B（各 3 次）：`import novelreader.qt_host` **914.2 → 689.1ms（中位 −225.1，配对 219–251）**，旧臂内部单独计 `edge_tts` 236–238ms；代价是**首次 Edge 合成 +244.5ms**（一次性，播放工作线程，不吃 30 秒合成预算）。启动路径核对：`import novelreader.qt_host`、`SpeechController()`、`set_voice("zh-CN-XiaoxiaoNeural")`、`list_edge_voices()`、`shutdown()` 之后 `edge_tts` 都不在 `sys.modules`。回归 `tests/test_edge_resilience.py` 新增 3 例，全量 **335 例通过**。 |
| 最终目标入口与本轮对应场景 | 保留现有界面和阅读功能，改善书库滚动、打开正文、设置和浮窗交互。当前验收见[整体流畅度实施计划](整体流畅度实施计划.md)开头的场景表，完整边界见[原始任务计划](任务计划.md)。 |
| 当前阶段与主线子任务 | 现有 Qt 入口的流畅度改进进行中，正在补齐可比较的宿主基线。原换壳 P2 的验收未通过，Qt Quick 第一节点也未通过。 |
| 主线恢复位置 | [Qt 前台归属核验与隐藏冒烟复测](整体流畅度实施计划.md#qt-前台归属核验与隐藏冒烟复测2026-11-12)及[第 8 节](#8-下一步任务)。 |
| 当前Bug | 当前记录为宿主验证阻塞。现有任务文档未登记独立联调 Bug 编号。 |
| 当前授权与禁止 | 本轮离线复核并更新状态。实际桌面呈现、系统输入及听音须由用户明确安排。新的真实宿主批次按其场景核对有效授权，旧单次授权已随对应批次使用。提交、推送、发布和正式入口切换须有对应授权。 |

## 2. 已完成内容

### 2.1 现有 Qt 入口的局部改进

- 书卡菜单已隔离开关状态，设置弹层打开和标签切换已减少正文重复渲染。浏览器交互和性能证据的适用条件见[书卡菜单对照](整体流畅度实施计划.md#首项实施结果书卡菜单)和[设置交互回归](整体流畅度实施计划.md#交互回归及证据边界)。
- Qt 隐藏冒烟记录验证了前台归属、退出回应与宿主身份匹配、退出码 0、Job 自然清空以及已登记端口无残留。冒烟在页面就绪前停止，未建立性能基线。[退出与清理证据](../../my-doc/测试文件/任务20261105-桌面渲染重构/qt-foreground-preflight-20261112-203600/verification.json)

### 2.2 Qt Quick 候选的已验证范围

- 冻结包的侧进程使用实际二进制管道验证了 UTF-8 中文路径、带表情的请求标识、合成书库结果和关闭回执，侧进程退出码为 0。真实双窗宿主的第一节点验收仍未通过。[侧进程实测](../../my-doc/测试文件/任务20261105-桌面渲染重构/quick-node1-utf8-repair-20261112-170659/sidecar-wire/result.json) · [宿主失败结果](../../my-doc/测试文件/任务20261105-桌面渲染重构/quick-node1-utf8-repair-20261112-170659/host-acceptance/result.json)

## 3. 当前正在处理

- 主线：**可见渲染路径已打通，等一次上屏时段**（2026-11-17 09:40–09:47，用户选"甲"）。做法：不在 `run.py` 上加分支（那里每条判据都要求窗口不可见），改为新增 `desktop-lab/visible_accept.py`，复用 `qt_host.py`/`fixture.py`/`benchmark.mjs` 的 `QY_LAB_*` 契约，只换启动桌面与判据方向。`qt_host.py` 加默认关闭的 `QY_LAB_VISIBLE=1`/`QY_LAB_AUDIO=1`，`metadata()` 的 `hiddenOnly`/`muted` 改为真实值并补 `visible`/`hWnd`/`exposed`/`dontShowOnScreen`/`transparentForInput`。**管线已验**：私有桌面两次运行 `driver/host=0/0`、`visible`+`exposed` 均 true、无残留进程；`benchmark.mjs` 三处改动只在 `owner.visibleRun` 存在时生效。**隐藏路径未变**：冒烟自有可见窗 0 条（80 条全为系统输入指示窗 pid 36816）、300 本性能批次 `exitCode=0`。**顺带**：同一批隐藏 performance 导入 **852.8ms**，对同日改前 1033.4/971.9 为 −119 至 −181ms，是 `edge_tts` 懒加载在真实宿主里的首条就地证据。未做：上屏（需用户时段）。证据 `visible-path-20261117-0940/`、验收预登记 `正式桌面验收预登记.md`。

- 主线：**`edge_tts` 已改按需导入，热启动 −0.225s**（2026-11-17 09:30–09:50，用户"继续"＝第 8 节第 3 条的甲）。改动 1 文件 2 处：`novelreader/tts_engine.py` 顶层 `try: import edge_tts` 换成哨兵 `_EDGE_TTS_UNLOADED = object()` + `_edge_tts_module()`（首次调用才 import，失败写回 `None` 并保持），`synth_audio` 改 `module = _edge_tts_module()`、`module.Communicate`；`RuntimeError("edge-tts 未安装")` 文案与抛点语义不变，SAPI 一次性回退路径不变。**用哨兵而非 `None`**：`edge_tts = None` 是现有代码与 `test_edge_resilience.setUp` 的"未安装"硬信号，若用它表示"未加载"，加载器会覆盖测试桩并误触发回退。**测量**（干净子进程三臂各 3 次）：`import novelreader.qt_host` 改后 **689.1ms**（689.1/704.1/661.0）、改前 914.2ms（922.6/912.6/914.2），**中位 −225.1ms**、配对差 219–251ms；旧臂内部单独计 `edge_tts` 236–238ms；比 09:05 消融估的 314ms 小（那是已加载 Qt 进程内的屏蔽增量，这是端到端 A/B），取 **−0.22 至 −0.25 秒**，占热启动 7–9%。**代价**：首次 Edge 合成 **+244.5ms**（249.0/239.6/244.5），一次性、在播放工作线程，导入在 `asyncio.wait_for` 之外不吃 30 秒预算。**启动路径核对**：`import novelreader.qt_host`、`SpeechController()`、`set_voice("zh-CN-XiaoxiaoNeural")`、`list_edge_voices()`（9 个静态音色）、`shutdown()` 之后 `edge_tts` 均不在 `sys.modules`。**回归**：`tests/test_edge_resilience.py` 新增 `EdgeLazyImportTests` 3 例（子进程验证未加载、加载器幂等且不覆盖 `None`、缺包时抛原文案），全量 **335 例通过**（原 332+3）。**未验证**：真实宿主首次朗读的主观延迟、宿主启动批次（跨批噪声 2.4–3.2 秒，单批证明不了 0.23 秒）。证据 `edge-tts-lazy-20261117-0930/`。

- 主线：**宿主两批已完成（2026-11-17 09:20–09:26，用户选"丙"）**，一次空档同时收口"200–511 本复核"和"构造段切开"。①**规模**：300 本 `…-20261117-092034-df05bd52` 与 400 本 `…-092145-a3fb6fa8` 两批页面侧均 `passed=true`（12 用例、`errors=[]`、可见窗 0），`libraryDomBefore/After.cards` 都是 **64/64**、标题分别含 300/400——400 本若全量挂载会是 400 张，故**虚拟窗口在 400 本下仍生效**；宿主只在三个滚动用例前后采静止态，手势峰值 96 仍是离线探针口径。滚动横向 400 vs 300：`library-down` 33.3/311.4 vs 49.9/356.1、`library-up` 16.8/148.2 vs 16.8/152.4、`library-reverse` 16.7/254.9 vs 16.8/190.0，与 18:46 基线同值域，**无规模趋势**。②**审计**：400 那批**通过、退出码 0**、`activeProcesses=0`、无残留 PID/CDP 监听；300 那批判 `foreground-attribution-failed`——13 个前台采样里 1 个 `hwnd=null/pid=0`（该批 22 次空桌面轮询），按原判据不豁免不重试，页面数据仍完整。③**构造切开**：`product-stage` 镜像已生效（每批 journal 20 行含 7 条），构造 300 本 **1439.3ms** / 400 本 **1072.5ms**，其中 `view-created→page-created`（`QWebEngineProfile` + `OfflineRequestInterceptor` + `QWebEnginePage`，`qt_host.py` 436–442）**1369.0/1004.4ms＝95.1%/93.6%**；`page→speech` 4.6/5.9、`speech→bridge` 15.6/17.4（四个自研服务合计 20.2/23.3ms）、`bridge→channel` 2.9/2.8、`channel→load` 4.6/3.2、`load→constructed` 16.3/15.2，未打点 3.5/3.0ms，闭合误差 ≤0.2%。**口径修正**：上次"宿主 vs 离屏差 1.2s 属平台"现在定位到差额全在 profile/page 这一段（离屏 338ms vs 宿主 1004–1369ms）。④启动合计 **3168.3/2447.2ms** = 导入 1033.4/971.9 + `QApplication` 44.2/36.9 + 构造 1439.3/1072.5 + showEvent 118.4/90.8 + 循环→load 273.1/200.8 + 加载 246.9/63.9，均在历史 2564–5244 内，7 条新打点未观察到抬升。**结论**：构造段可收口（再动只能改 Chromium 初始化，page 就是加载 UI 的那个不能延后），尺寸线可收口，剩甲（`edge_tts` 懒加载 −0.31s）是唯一已定量、可直接做的启动优化。证据 `host-batch-scale-startup-20261117-0920/`。

- 主线：启动耗时**已离线拆解完成**（2026-11-17 09:05–09:40，用户"继续"，产品零改动）。三段证据：①`summarize_host_stages.py` 只读汇总 29 份 `startup-stages.jsonl`，28 个热缓存批次中位——导入 **1191ms**（997–2320）、`QApplication` 39ms（29–90）、主窗构造 **1576ms**（1160–2699）、首次 showEvent 116ms（84–311）、事件循环→`load-started` 228ms（171–494）、前端加载 101ms（64–169），**合计 3265ms**（2564–5244）；冷缓存批次（11-16 15:41）导入 **6142ms**、构造 1767ms、合计 **8823ms**，冷热差的 5.5 秒全在导入＝磁盘首次读 DLL。②`measure_import.py` 单进程逐段 import（3 次）：`QtCore` 140.4 / `QtGui` +10.5 / `QtWidgets` +5.8 / `QtWebEngineCore` +54.6 / `QtWebEngineWidgets` +3.3 / `novelreader.qt_host` **+947.2**，合计 1145.9ms，与宿主 journal 对得上；消融（各 3 次中位）基线 1080.6 → 屏蔽 `edge_tts` **766.5（−314.1）**、屏蔽 `pyttsx3` 1010.1（−70.5）、两个都屏蔽 755.8（−324.8，与单屏蔽 edge 只差 10ms，重叠在 comtypes 一侧）。`edge_tts` 全文件只被 `synth_audio` 用到（第 422/429 行），只服务 Edge 音色后端。③`measure_window.py` 离屏跑真 `DesktopWindow`（`offscreen` QPA、不 `show()`、真 400 本夹具、产品不改）：构造合计 391.7ms（373.9–439.5），`QWebEngineProfile` **300.4（77%）**、`QWebEnginePage` 37.8（10%）、`DesktopBridge` 17.3（4%）、`RoundedWebEngineView` 0.4、`QWebChannel` 0.2、四个自研服务各 0.0–0.1ms；**绝对值不可搬运**——宿主同段 1576ms vs 离屏 392ms，加不加 `--disable-gpu` 都 374–392ms、DPR1.25 也只 510.8ms，差的约 1.2s 属平台，离屏测不到。为了让这段 1.576s 能在宿主上切开，测试工具加了一行：`desktop-lab/qt_host.py` 把产品 `_qa_trace` 的七个构造点镜像成 journal 的 `product-stage` 事件（只增不改）。下一步三选一（见第 8 节第 3 条）：甲 `edge_tts` 改按需导入、乙 跑带 `product-stage` 的宿主批次、丙 把乙并进 200–511 本那条批次——推荐丙。

- 主线：200–511 本的库，**测试工具已就绪、离线证据已成立**（2026-11-17 08:55–09:20，用户引用该条后"继续"）。三步：①把宿主入口放开——`desktop-lab/fixture.py` 与 `desktop-lab/run.py` 的 `--books`/`--menu-books` 由 `[300,600]` 扩到 `[250,300,400,500,600]`，guard 由"非 300 仅 menu-boundary"改为"非 300 仅 menu-boundary 与 performance"，`owner.fixtureBooks` 由仅 menu-boundary 写入改为所有相位写入（否则 400 本批次会等标题里的 `300` 超时）；`benchmark.mjs` 在 `performance` 相位三个滚动用例前后增采 `libraryDomBefore/After`（`.book-card` 数/`scrollTop`/标题，只增字段）。②离线探针 `probe-scale.mjs`（复用 `browser.mjs` 链路，`--books` 参数化、build 支持绝对路径）跑同一 `library-down` 手势：**250 / 300 / 400 / 400 复测 四臂全部 `virtual-window`，挂载恒 64→96，Task 281/228/219/261ms、Layout 8–15ms，无规模趋势**。③负向对照：用阈值仍是 512 的旧产物（`index-C3BnI7BJ.js`）跑同一 400 本，判 `full-mount`、挂 400 张、Task 616ms、Layout 27ms——证明探针不是"恒返回 96"，且当前产物把同规模成本压掉 64%。夹具自检：`--books 400` 1.2 秒生成、`library.json` 400 条、4.7MB。**未做**：宿主批次（需桌面空档与授权），命令与预期判据写在证据目录 `结论.md`。
- 主线：音量改为按播放状态分流，**已完成**（2026-11-16 20:15–20:30，用户"继续"）。做法：用户发现第 8 节第 1 条时先只读查证——`qt_bridge._apply_speech_settings` → `set_volume` 是唯一枚举入口，而 `_set_process_volume` 全文件只有一个调用点（`_speak_edge_play` 每句播放前），**SAPI 走 `_engine.say()` 完全不经过它**，所以不能简单摘掉，必须把应用点补到 SAPI 自己的播放起点。改动 `novelreader/tts_engine.py`（+45/−9）：`set_volume` 值没变直接返回；值变了且 `_state in ("playing","paused")`（用户正在听）才立即 `_apply_volume`，否则只记期望值并保持待应用；新增 `_apply_pending_volume()` 作为播放起点入口（Edge/Kokoro 每句之前、SAPI `say()` 之前各一次，已一致时零开销）；`_apply_volume` 失败不记账以便下一句重试。离线真机测量（`measure_volume_change.py`，7 个音频会话）：静音改音量 **204.9/208.4/184.5 → 0.0ms**（中位 184.5→0），播放中 177.3–222.1ms 不变（保持即时）；且旧路径三轮都 `oldPathResolved=false`，证明静音期那次枚举根本没有作用对象。开书边车三批 18 次：`set_volume` 全 0.0ms、`_set_process_volume` 0 次调用、worker 23.0–30.6ms。**同时更正一条旧口径**：19:50 那批 `timings-*.json` 显示首次开书 `set_volume` 本就只有 0.5–0.8ms（COM 未初始化直接失败），198–203ms 属于更早的 profile 批次，所以本轮对开书是"消除隐患"而非"再省半秒"。单测 7→14 例（新增静音延迟/暂停即时/播放起点落地/失败重试/SAPI 起点先于 `say`），全量 **332 例通过**；前端产物与测试工具零改动。证据 `volume-deferral-20261116-2015/`。
- 主线：打开正文的主项已定位到后端音频会话枚举，**已修复并通过宿主 A/B**（2026-11-16 19:45–20:00，用户"继续"）。三步：①`desktop-lab` 新增诊断相位 `open-split`（`benchmark.mjs` + `run.py`，只测不改）——在宿主页面 `qt.webChannelTransport` 的 `send`/`onmessage` 上打点，得到"pointerdown → `openReaderBook` 发出 5.5–13.9ms → requestId 回执 17ms → `readerOpened` 事件 **367–419ms** → 首块 → 下一帧 30–55ms"，即打开耗时的 85% 在后端等事件，渲染只占几十毫秒；②离线边车 `measure_open_backend.py`（真实 `desktop-lab/service.py`、真库真缓存，只套计时）拆开 worker：重复开书 216–228ms 里 **198–203ms 是 `set_volume` → `_set_process_volume`**，`AudioUtilities.GetAllSessions()` 本机每次 **250–480ms**（7 个会话），首次开书只 0.6ms 是因为工作线程 COM 未初始化直接异常走 MCI 回退；③改 `novelreader/tts_engine.py`：值没变不再申请 OS 音量（进程会话音量会保持，播放起点 `_speak_edge_play` 本来就会重新应用），并把解析到的 `ISimpleAudioVolume` 缓存复用。宿主同相位 A/B 各三次：重复开书 **298.1/411.3/567.5 → 202.2/209.0/178.4ms**（中位 411→202），字号一次设置往返 **409.4 → 54.8/66.4/50.9ms**；首次开书不变（仍付一次枚举，进程内一次性）。实验室重复开书 worker 216–228→25–33ms。`tests/test_speech_volume.py` 7 例 + 全量 325 例通过；前端产物未重建。标准 `performance` 批次因同机负载波动（`book-hover` Task 449→899ms）只作参考：改动后 `open-reader` ready 119.2/191.3/218.3/391.3ms（中位 204.8），改动前中位 275.5ms。证据 `open-book-backend-20261116-1955/` 与 `qt-default-open-split-native-hidden-20261116-1945*/1950*/1953*`。
- 主线（已收口）："减少阅读页首次提交的节点与工作"这条方向**已被 `fewBlocks` 数据否证**——40→3 块时 `TaskDuration` 0.105/0.151/0.156 对基线 0.108/0.098/0.174、`LayoutDuration` 0.031/0.034/0.035 对 0.043/0.031/0.045，没有收益；把首屏拆成 8–10 块再增量提交只会把"就绪"时点提前（指标好看）而帧不变快，属于自欺，不做。
- 主线：阅读页结构空闲预热**已尝试并否证回退**（2026-11-16 19:05–19:40，用户"先做1"授权）。做法与设置预热同类：空闲时把真实 `NativeReader`（合成 state、30 段中文、默认 `微软雅黑 17px/1.5`）渲染进隐藏宿主，宿主按 `.content-area` 实测矩形定位。离线（tracing，每臂 3 次）窗口内 Layout 31/29/45→**9.3/14.2/11.5ms**、`LayoutDuration` 0.031–0.045→0.009–0.014s、卡顿段 46–69→17–31ms。但宿主批次 `qt-default-performance-native-hidden-20261116-192533-abef3671`（产物 `index-D6FC2Ozb.js`）**零收益**：`TaskDuration` 0.1283→0.1278、`LayoutDuration` 0.0073→0.0089、长任务 64→65ms、打开耗时 258→273ms、p95 恒 133.3。根因是口径——**宿主自己的首次阅读页布局一直只有 7.3–8.0ms，离线 tracing 把它抬到 31–45ms（约 4 倍仪表开销）**，所以"128ms 里七成是布局"在真实宿主上不成立（65ms 长任务里脚本 20ms、布局 9ms，其余样式/绘制/合成）。代价真实：预热那个 **79ms 空闲任务落进 `library-down`**，`>50ms` 帧 0→3（2.1%，触到 1% 判据）、最长帧 50→83.3ms，`book-hover` 最长帧 116.6→200ms。处理：源码与样式已回退，重建产物与 18:33 **逐字节相同**（`index-Q-TfAU_F.js`，`sha256 c68b2f1f…`），产品零残留；源码只在设置预热注释下留三行"试过并回退"的说明。证据 `reader-warmup-20261116-1930/`。~~下一轮若继续压 `open-reader`，方向是"减少首次提交的节点与工作"（首屏只提交可视块），不是预热。~~ **20:00 修正**：该方向已被 `fewBlocks` 数据否证；真正的缺口在后端会话枚举，见本节第一条。
- 主线：打开正文 128ms 已完成离线拆解（2026-11-16 19:00–19:40，七个对照臂，产品零改动）。结论四句话：①宿主 `open-reader` 的 128ms 分成 4–7ms 输入分发 + 12–27ms 请求与 `OPENING` 渲染 + 18–32ms 等待期零散工作 + **45–69ms 数据到位后的连续渲染**；②这 45–69ms 里七成是一次首次布局（`dirtyObjects=337/394` 的那次 Layout 占 27–45ms），**与章节数无关**（1000→30 章无变化）、与段落量弱相关（40→3 块只省约 10ms）、与绘制无关（1–3ms）；③这约 30ms 是会话内一次性成本，第二次打开（同书或异书）同一个 337 脏对象只要 2–6ms，卡顿段从 45–69ms 降到 10–23ms；④**打开耗时的主项不在这 128ms**——响应到 `readerOpened` 事件之间 257–375ms 是后端 `open_book`，主线程只占 7%–9%。附带否证：用隐藏宿主按阅读字体排 40 段中文（21px/17px 各 3 次）**暖不动**冷布局，`LayoutDuration` 仍 0.030–0.031s，所以"预热字体"这条路不通。**注（19:40 修正）**：②里的 27–45ms 与 0.030–0.031s 均为 tracing 口径，宿主实测首次布局只有 7.3–8.0ms，绝对值不能用；相对结论（章节数/段落量/绘制不是主因）仍成立。证据 `open-reader-cost-20261116-1900/summary.json` 与同目录 `结论.md`。
- 主线：`open-reader` 采样加长已完成并验证（2026-11-16 18:53）。`desktop-lab/benchmark.mjs` 在 `open-reader` 之后插入 `open-reader-settle`：正文已打开后固定采样 1500ms（约 90 帧），`open-reader` 本身保持原样以维持历史可比。首批数据：`open-reader` 11 帧 p95 133.3（未变）、`open-reader-settle` **91 帧 p95 16.7、最长 16.8ms、>50ms 帧 0**、Task 32.2ms/1500ms、Layout 0 → **133ms 是打开这一次的过渡帧，不是持续卡顿**。打开耗时 `pointerdown→ready→next rAF` 阈值前 335.6/331.5、阈值后 275.5/258.0ms（该项历史抖动 258–524ms，只能算没变慢）。同一批其余 11 用例 p95 与 18:46 完全一致。`benchmark.mjs` `sha256` 由 `18aea73d…`→`1517ef4a…`，产品产物与源码零改动。
- 主线：虚拟窗口阈值 200 已通过宿主批次验证（2026-11-16 18:46，`qt-default-performance-native-hidden-20261116-184645-c0c4fcfd`）。批次 `passed=true`、11 用例、10 检查、`errors=[]`、`visibleViolations=0`、退出码 0、34 秒，启动参数与 17:20/17:21 一致。三个滚动用例：`library-down` Task **590.9/594.8→315.4ms（-47%）**、Layout 49.1→28.3、p95 33.3 不变、最长帧 66.7 不变；`library-up` Task **308.0/299.4→159.1ms（-47%）**、Layout 51.0→14.0、p95 16.7、最长帧 66.7→**49.9**、超 50ms 帧 1→**0**；`library-reverse` Task **407.7→218.4ms（-45%）**、p95 16.8 不变。其余 8 个用例 p95 全部与基线相同，其中 `book-hover` Task 624.8→353.2、`book-menu-open-close` 184.5→126.3、`open-reader` 156.3→126.7（节点少一半的溢出收益）。唯一上升项是 `library-down` 的 Style 0.8→8.0ms（新挂载卡片挂 `motion-ready`），相对省下 275ms 可忽略。预登记点名的失败形态（Task 降但 p95 恶化）**没有出现**，**不回滚**。
- 已落地内容（同上一条的历史记录，保留）：虚拟窗口阈值已落地（2026-11-16 18:33 用户"按你的推荐做"）。`prototype/src/App.jsx` 第 395 行由 `books.length > 512` 改为 `> 200`，并加三行注释说明取值依据（窗口为 64–96 张，200 本已是 2.5 个窗口；更小的库省不下、只添换卡开销）。取值不用 120 的理由同此。`npm run build` 已重建：CSS 保持 `index-BUgJh7pn.css`，JS 由 `index-C3BnI7BJ.js` 变为 `index-Q-TfAU_F.js`（588555 B，`sha256 c68b2f1f…`）；`test:bridge` 61 / `test:library` 8 / `test:sites` 4 全过。新产物离线复测两次：Task 218.3/216.0ms、HitTest 73.0/73.2ms、Layout 8.0/8.2ms、挂载 64→96、p95 16.9ms、`scrollHeight` 32854 不变（旧产物 459.2/548.3ms）。虚拟窗口下的筛选回归六步全部符合预期（300→100→1→0→清空→深滚，挂载数 96/68/1/0/64/96，页面异常 0）。**宿主批次未跑**，软件合成下跨批新挂载封面的栅格成本仍是唯一未验项。
- 虚拟窗口阈值的离线实验数据仍在本节下一条（2026-11-16 18:10–18:45）。用户说"继续"后按第 8 节第 1 条推进，做法是把产品源码临时改一行（`> 512` → `> 120`）构建到证据目录，与当前源码重建的 `dist-current` 并列测量，构建完立即改回（`sha256` 与实验前一致 `438fed9…`，`prototype/dist` mtime 仍是 17:23）。32×wheel/5580px、每臂两次：当前 Task 459.2/548.3ms、HitTest 267.9/319.8ms、Layout 20.2/21.5ms、挂载 300 常驻；变体 Task **285.5/238.6ms**、HitTest 98.7/82.6ms、Layout 10.0/8.4ms、挂载 64→96。72×wheel/12960px 长手势：1549.0 vs **549.0ms**（-65%），三次跨批共新增 96/移除 64 节点，帧最长 17.3ms、无 long task、`scrollHeight` 稳定 32854。打开书库耗时两组重叠（Task 205–245 vs 169–209ms）、只能算没变慢。GPU/合成线程未升高，说明省的是主线程的活。判据"Task 与 p95 同时不劣"离线成立，但**尚未改产品阈值**：宿主是软件合成，跨批新挂载封面的栅格成本在离线口径里不存在，要宿主批次才能判。产品零改动，`dist` 未重建。
- 书库滚动的剩余主线程成本已完成离线归因（2026-11-16 17:45–18:05，用户选「甲」）。七个对照臂在同一真实 300 本夹具、同一 `library-down` 手势（32×wheel、5580px）下各摘一类成本：基线 Task 451/480ms、指针在卡片上 340、去封面 490、去装饰 503、`content-visibility` 614、不绘制 183、只剩 40 张卡 125。四条结论：①整条手势 300 张卡常驻，DOM 只有 12 条 settle 后的 `motion-ready` 切换，成本与"每帧挂载卡片"无关；②封面与装饰都不是成本；③**命中测试是最大单项**——32 次 wheel 触发 67 次 `HitTest` 共 280.8ms（占主线程 58%，4.2ms/次），指针落到卡片上即降到 155ms；④成本随挂载卡片数增长（40 张卡时 -72%），而 `content-visibility:auto` 反而把 Layout 推到 160ms、Task +28%，明确否证。自算 self time 合计 450.2ms 与 `TaskDuration` 452ms 差 0.4%，拆解无漏项。全部软件合成口径，产品零改动。
- performance 相位共五批（15:51、15:54、16:03、16:08、16:09）。三批通过、两批因 `foreground-attribution-failed` 判失败，页面侧五批均完整（11 用例、10 检查、异常 0），清理均干净（退出码 0、Job 归零、无残留）。
- 已查明前台审计机制：采样只在 start/end 与"前台发生变化"的 poll 追加，五批采样数 17/13/12/4/2、poll 数 15/11/10/2/0。故"通过"的覆盖强度取决于桌面前台活动量而非被测程序行为——16:09 通过的批次只有 2 个端点采样，覆盖最弱；16:08 的失败来自 t+33.05s 一次外部前台变动瞬间的空读数。既不能断言判据不可满足（16:03 已否证），也不能断言判据覆盖充分。判据未改动，局限已登记。
- 五批帧数据（软件合成）p50 一律 16.7–16.8ms，与校准基准相同，60fps 已顶格，只有 p95 长尾可比较。p95 中位数：`settings` 66.6ms、`open-reader` 133.4ms、`book-hover` 100.0ms、`book-menu-open-close` 49.9ms、`library-down` 33.4ms；其余五项五批稳定 16.7–16.8ms。`open-reader` 每批仅 14–21 帧，p95 由个别慢帧决定，需加长采样才可定论。
- 移除 `data-scrolling` 门控（2026-11-16 17:10 用户选「甲」，**已留存产品改动**）：离线在真实 300 本夹具上逐条减规则，测得翻转成本由被失效的**元素数**决定——0 条 0.1ms、1 条 6.65ms（1500 元素）、3 条 6.5ms、6 条 11.4ms（2100 元素），自定义属性方案反而升到 38.5ms（4923 元素）；**翻转本身零 Layout 事件**，此前把宿主用例 51–64ms Layout 归因于该开关是错的。真实宿主两批一致：`library-down` Style 68.2→0.6/0.8ms、Task 767.9→590.9/594.8ms；`library-up` Style 72.0→0.5ms、Task 479.8→308.0/299.4ms；`library-reverse` Style 65.6→0.0ms、Task 583.0→407.7ms；其余 8 个用例不变。已移除 6 条规则的祖先条件，保留 `:hover` 本身与 `data-scrolling` 的发布逻辑（后者仅作 desktop-lab 检查用的滚动状态信号）。产品测试 61+8+4 全过。
- 设置面板优化（2026-11-16 16:38 用户选「甲」，**已留存产品改动**）：离线定位否证了「全页重排」猜测——打开设置只有 104/9587 个节点被标记脏，弹层自身 78 个节点；真实成本是会话内首用文本塑形，首次打开 Layout 35.83ms、同会话第二次 1.04ms，首次切「常规」9.47→0.71ms。改法是在书库就绪后延迟 300ms，用 `requestIdleCallback` 把「朗读与悬浮」「常规」两页渲染一次到隐藏宿主（`visibility:hidden` + `contain:layout style paint`），两帧后移除。离线复测首次打开 Layout **1.4–2.6ms**、首次切「常规」**0.95–2.20ms**、首次打开到下一帧 62→17–22ms。真实宿主三批：17:04 页面完整但审计判退出阶段窗口销毁竞态 + 前台空读数；17:06 审计通过但被机器争用整体拖慢 1.5–2 倍（含无关用例，判污染）；17:07 审计通过、无争用，全用例落在基线值域内（settings p95 66.7、Layout 15.4 vs 基线中位 19.7）。**口径说明**：基准脚本计时前已预开过一次设置，故宿主口径看不到本次收益，该批次只证明没有把成本搬到别处；收益证据来自离线冷/暖对照，且本改动是把一次性成本移到空闲期（约 +45ms 空闲布局），不是消除。
- 优化尝试（2026-11-16 16:29 用户选「甲」）：针对滚动用例试改 2 条 CSS（滚动期关每卡 `backdrop-filter`、关 `will-change`），**假设被否证**——干净批次（16:34，审计通过、退出码 0）无任何用例改善，`library-up` 的 Layout 反升至 172ms（基线 51–64ms）、Style 升到 221ms（基线 61–85ms）、p95 从 16.8 掉到 33.3。原因是新增 `[data-scrolling="true"]` 规则扩大了 subtree-wide 失效范围，其成本对规则数量超线性。两条规则已删除，重建后产物与 11-12 版本逐字节等价（`index-Cj4hGzgN.css` 70738 bytes），**产品代码已回到原状**。
- Qt Quick 已有远程调试 Origin 与窗口归属记录的离线候选，尚无宿主实测。第二节点只有独立协议候选，宿主移植尚未启动。[离线诊断](../../my-doc/测试文件/任务20261105-桌面渲染重构/quick-node1-offline-diagnosis-20261112-174803/诊断结果.md) · [节点移交](../../my-doc/测试文件/任务20261105-桌面渲染重构/quick-node2-preflight-20261112-173118/节点移交.md)

## 4. 验证状态

| 验证项 | 状态 | 证据或说明 |
|---|---|---|
| 「不闪屏+丝滑」：主窗口不透明直角，绕开透明合成冲突（2026-11-17 14:38） | **已验证（硬件保留 + 绕开透明 + 用户确认不闪白）** | 主窗口 `DesktopWindow` 改不透明直角（`WA_TranslucentBackground=False`、背景 `#f7f9fc`、`--main-window-radius:0px`、`CornerClip` 仅悬浮窗启用）。私有桌面 `visible-accept-private-20261117-142113` + 真实上屏 `--hold` 三次（142238/143319/143642）：**`graphicsApis=Direct3D11`、`translucent=False`**；用户现场确认「丝滑+不闪白」；`driverExitCode` 1→0（尺寸漂移消失）。悬浮窗保持透明不变。 |
| 渲染模式开关落地：默认硬件加速拿到 GPU（2026-11-17 11:45） | **已验证（GPU 后端切换确证）** | 私有桌面批次 `visible-accept-private-20261117-114528-009ec942`（`--candidate qt-default --desktop private`，产品代码已改默认硬件）：`host.json` `graphicsApis = ["GraphicsApi.Direct3D11"]`、`configured = system`、`qtQuickBackend = None`、`translucent = True`。对照 09:40 旧代码同环境两批 `094052`/`094226` 均为 `Software` / `software-composition`。**结论**：产品「默认硬件加速」在透明窗下（含此前「拿不到 GPU」的私有桌面）即拿到 D3D11，圆角保留。`book-hover` 帧时间本批未测到（窗口 1280×720→1024×576 尺寸漂移致 `renderer-calibration` 报 `NO_CLICK_AREA:.book-open`，私有桌面固有），但 16.7ms 是硬件合成同一因果链（11:00 上屏对照已证 83.4→16.8ms）。[批次目录](../../my-doc/测试文件/任务20261105-桌面渲染重构/visible-accept-private-20261117-114528-009ec942/report.json) |
| B 人工通道验收：真实上屏 + 真实音频（2026-11-17 14:02） | **已验证（真实上屏 D3D11 确证，干净关闭）** | `visible-accept-active-20261117-140208-f14beccd`（`--desktop active --hold --audio`）：真实上屏（console 会话、AMD 双屏）+ 真实音频，`graphicsApis=["GraphicsApi.Direct3D11"]`、`size=[1280,720]`、`visible/exposed=true`；`hostExitCode=0`/`driverExitCode=0`/`errors=[]`/`residualPids=[]`。主观观察项（闪帧/拖缩/跨屏/浮窗/朗读）由用户现场观察；「闪白」回归留待长期使用。**顺带修复工具缺陷**：`qt_host.py` 10 分钟硬超时会把 `--hold` 窗口强制关闭，已改为 `QY_LAB_HOLD=1` 时跳过。 |
| 冒烟就绪断言修复（2026-11-17 09:51–09:55） | **已修并验证（隐藏批次通过）** | `desktop-lab/qt_smoke.mjs` 去掉 `cards===300`（阈值 512→200 后该式永不成立）；改为 `.section-title span` 读数等于 `owner.fixtureBooks`，且挂载数在 `16…fixtureBooks`。批次 `…095101-35a361b8`：`pageReady=true`、`cards=64`、`total="300 项内容"`、`virtualized=true`、`exitCode=0`、`qtHiddenAudit.passed=true`、可见违规 0、无残留。 |
| 可见渲染路径（2026-11-17 09:40–09:47） | **管线已验证；上屏未跑；21ms 两项仍只有软件合成口径** | 新增 `desktop-lab/visible_accept.py`（`--desktop active|private`、`--hold`、`--audio`）+ `qt_host.py` 默认关闭的 `QY_LAB_VISIBLE`/`QY_LAB_AUDIO`。私有桌面两次：`driver/host=0/0`、`visible=true`、`exposed=true`、`dontShowOnScreen=false`、`transparentForInput=false`、残留 0；`book-hover` 83.4/83.4、`settings` 66.7/66.6，与隐藏批次一致到 0.1ms。隐藏路径未变：冒烟自有可见窗 0 条、300 本性能批次 `exitCode=0`、`cards 64/64`。判据表与两条通道见[验收预登记](正式桌面验收预登记.md)，结论见 `visible-path-20261117-0940/结论.md`。 |
| `edge_tts` 按需导入（2026-11-17 09:30–09:50） | **离线已验证收益；宿主未跑** | 干净子进程 A/B（各 3 次）：`import novelreader.qt_host` **914.2 → 689.1ms（−225.1 中位，配对 219–251）**；旧臂单独计 `edge_tts` 236–238ms。首次 Edge 合成 **+244.5ms**（一次性，工作线程）。启动链 `import qt_host`/`SpeechController`/`set_voice`/`list_edge_voices`/`shutdown` 后 `edge_tts` 均未进 `sys.modules`。回归 +3 例，全量 335 通过。宿主批次未跑——跨批噪声 2.4–3.2 秒，单批不足以分离 0.23 秒。[结论](../../my-doc/测试文件/任务20261105-桌面渲染重构/edge-tts-lazy-20261117-0930/结论.md) · [测量](../../my-doc/测试文件/任务20261105-桌面渲染重构/edge-tts-lazy-20261117-0930/measure-lazy.json) |
| 宿主两批：400 本虚拟窗口 + 构造段切开（2026-11-17 09:20–09:26） | **已完成（真实宿主，400 批审计通过）** | 300 本 `…-20261117-092034-df05bd52`、400 本 `…-092145-a3fb6fa8`；两批页面 `passed=true`、`errors=[]`、可见窗 0、`hostExitCode=0`、`activeProcesses=0`、无残留。`libraryDomBefore/After.cards` 均 **64/64**（标题含 300/400）→ 400 本仍走虚拟窗口。构造 1439.3/1072.5ms，`view→page` **1369.0/1004.4（95.1%/93.6%）**，四个自研服务段合计 20.2/23.3ms；启动合计 3168.3/2447.2ms。300 批审计失败＝13 个前台采样 1 个空读数，页面数据不受影响。[结论](../../my-doc/测试文件/任务20261105-桌面渲染重构/host-batch-scale-startup-20261117-0920/结论.md) · [汇总](../../my-doc/测试文件/任务20261105-桌面渲染重构/host-batch-scale-startup-20261117-0920/summary.json) |
| 启动耗时离线拆解（2026-11-17 09:05–09:40） | **已完成（离线，产品零改动）；构造段宿主绝对值已由 09:20 两批补齐** | 宿主 28 热批次中位：导入 1191ms、`QApplication` 39ms、构造 **1576ms**、showEvent 116ms、循环→load 228ms、前端加载 101ms、合计 **3265ms**；冷批次导入 6142ms、合计 8823ms。导入分解：Qt 全套 0.21s，`novelreader.qt_host` +947.2ms（单进程逐段增量，3 次）；消融 3 次中位 基线 1080.6 → 屏蔽 `edge_tts` **766.5（−314.1，−29%）**、屏蔽 `pyttsx3` 1010.1、两者 755.8。构造（离屏 5 臂）391.7ms：profile 300.4、page 37.8、bridge 17.3、自研服务各 ≤0.1ms；`--disable-gpu` 无关（391.7/373.9），DPR1.25 510.8。宿主 vs 离屏差约 1.2s 归平台，新加 `product-stage` journal 打点待宿主批次验证。[结论](../../my-doc/测试文件/任务20261105-桌面渲染重构/startup-cost-20261117-0915/结论.md) · [汇总](../../my-doc/测试文件/任务20261105-桌面渲染重构/startup-cost-20261117-0915/summary.json) |
| 浏览器交互与布局 | 局部已验证 | 已有合成书库及设置交互实测，结果适用于记录的输入与浏览器条件。[现有流畅度证据](整体流畅度实施计划.md) |
| 移除 `data-scrolling` 滚动悬停门控 | **已验证收益（宿主两批一致）** | 离线逐条减规则：0 条 0.1ms / 1 条 6.65ms / 3 条 6.5ms / 6 条 11.4ms，失效元素 1500→2100，自定义属性方案 38.5ms（4923 元素）；翻转零 Layout。宿主 17:20 与 17:21 两批：`library-down` Style 68.2→0.6/0.8ms、Task 767.9→590.9/594.8ms；`library-up` Style 72.0→0.5ms、Task 479.8→308.0/299.4ms；`library-reverse` Style 65.6→0.0ms、Task 583.0→407.7ms；其余 8 用例不变，p95 不变（软件合成整屏光栅决定）。两批均因前台采样空读数判 `foreground-attribution-failed`，页面完整、可见性违规 0。[证据汇总](../../my-doc/测试文件/任务20261105-桌面渲染重构/scrolling-gate-20261116-172000/summary.json) |
| 书库滚动剩余成本离线归因 | 已完成（离线，七对照臂；产品零改动） | 同一 300 本夹具与 `library-down` 手势（32×wheel deltaY180、5580px）：基线 Task 451/480ms、指针在卡片上 340、去封面 490、去装饰 503、`content-visibility` 614、不绘制 183、只剩 40 张卡 125。命中测试 280.8ms/67 次占主线程 58%，指针落到卡片即 155ms；300 卡常驻、DOM 仅 12 条类切换；`content-visibility` 使 Layout 21→160ms、LayoutCount 1→23（否证）。self time 合计 450.2ms vs `TaskDuration` 452ms（差 0.4%）。软件合成口径 `validForComparison=false`。[归因汇总](../../my-doc/测试文件/任务20261105-桌面渲染重构/scroll-cost-20261116-174500/summary.json) |
| 设置面板首用塑形优化 | 离线已验证收益 / 宿主无回归 | 离线夹具（真实 300 本、真实服务、真实 `dist`、headless Chromium）首次打开 Layout 35.83→1.4–2.6ms、首次切「常规」9.47→0.95–2.20ms、首次打开到下一帧 62→17–22ms；宿主 17:07 批次审计通过、退出码 0、全 11 用例落在五批基线值域内（settings p95 66.7、Layout 15.4 vs 中位 19.7）。**宿主计时口径预开过一次设置，看不到该收益**，只用于证明无回归。[离线臂](../../my-doc/测试文件/任务20261105-桌面渲染重构/settings-optimization-20261116-164500/预登记.md) · [批次](../../my-doc/测试文件/任务20261105-桌面渲染重构/qt-default-performance-native-hidden-20261116-170737-97769f19/report.json) |
| 现有 Qt 宿主隐藏冒烟 | **通过（2026-11-16 15:47，带窄范围豁免）** | `qtHiddenAudit.passed=true`、违规 0、退出码 0、Job 归零、无残留与清理错误。58 次枚举，豁免 114 窗（`UAC_InputIndicatorOverlayWnd` 43、`UAC Input Indicator` 43、`SoPY_Status` 28），本批内分别核验到 `C:\Windows\System32\InputSwitch.dll` 与 `C:\WINDOWS\system32\SogouPY.ime`。页面 `page-ready-confirmed`：300 卡、`fixture`、`nativeChannel`、1280×720、DPR 1.25、QtWebEngine 6.8.3。仍为软件合成（`gl=disabled`、GLES3 失败回退 GLES2），且该口径按既有规则不进入性能对比。[页面报告](../../my-doc/测试文件/任务20261105-桌面渲染重构/qt-default-qt-smoke-native-hidden-20261116-154721-378fb39d/qt-smoke-page.json) · [豁免与所有权](../../my-doc/测试文件/任务20261105-桌面渲染重构/qt-default-qt-smoke-native-hidden-20261116-154721-378fb39d/ownership-and-resources.json) · [批次汇总](../../my-doc/测试文件/任务20261105-桌面渲染重构/qt-startup-diagnostic-exempt-batch-20261116-154711/summary.json) |
| 现有 Qt 宿主隐藏冒烟（严格判据历史） | 未通过，已定位首故障 | 归档中的 30 项源码和前端文件摘要与当前工作区一致。11 月 12 日 20:38:18.756–18.757 首次观察到两个宿主所属的输入指示窗口，18.759 登记停批。11 月 16 日 15:41 复现：首个可见窗 `UAC_InputIndicatorOverlayWnd` 属 `InputSwitch.dll`，出现于 `qapplication-created` 后 0.416 秒。严格判据下该环境必停在 GUI 初始化阶段。[产物与入口](../../my-doc/测试文件/任务20261105-桌面渲染重构/qt-default-qt-smoke-native-hidden-20261116-154140-cd04aca4/qt-smoke-stop.json) |
| 启动诊断的离线准备与回放 | 已验证（离线） | 45 项断言用例通过、0 次真实宿主。停批记录现可定位首见可见窗时宿主阶段并采集注册模块或显式失败；归档回放确认 11 月 12 日批次事件顺序、归属链（113 条违规同属 Job 成员 48880）与 GLES 停批后 2.073 秒时序。真实批次待登记。[离线验证汇总](../../my-doc/测试文件/任务20261105-桌面渲染重构/qt-startup-diagnostic-offline-20261116-153355/summary.json) |
| 首次真实隐藏启动诊断（2026-11-16 15:41） | 已执行，失败批次，已定位首故障 | 首个可见窗 `UAC_InputIndicatorOverlayWnd`，模块 `C:\Windows\System32\InputSwitch.dll`，Job 归属已复核；出现于 `qapplication-created` 后 0.416 秒、`mainwindow-constructed` 前 1.298 秒；96 条违规全属 PID 47748。判据沿用原口径停批；退出码 0、Job 归零、无残留进程与端口、无清理错误。页面未就绪，GLES3 创建失败与此前一致。[停批记录](../../my-doc/测试文件/任务20261105-桌面渲染重构/qt-default-qt-smoke-native-hidden-20261116-154140-cd04aca4/qt-smoke-stop.json) · [阶段流水](../../my-doc/测试文件/任务20261105-桌面渲染重构/qt-default-qt-smoke-native-hidden-20261116-154140-cd04aca4/startup-stages.jsonl) |
| Qt 宿主 performance 诊断批次（15:51 / 15:54 / 16:03 / 16:08 / 16:09） | 五批中 16:03、16:09 干净通过；三批判失败（前台归属） | 五批页面侧均完整（11 用例、10 检查、异常 0），清理均干净（退出码 0、Job 归零、无残留）。前台采样数 17/13/12/4/2（poll 15/11/10/2/0），因采样只在前台变化时追加，"通过"的覆盖强度不一：16:09 仅 2 个端点采样即通过，覆盖最弱。帧数据 p50 一律 16.7–16.8ms（软件合成 60fps 顶格），p95 中位数：`settings` 66.6、`open-reader` 133.4、`book-hover` 100.0、`menu` 49.9、`library-down` 33.4，其余五项稳定 16.8ms；`open-reader` 每批仅 14–21 帧，p95 不可靠。全部 `validForComparison=false`，仅诊断参考。[五批汇总](../../my-doc/测试文件/任务20261105-桌面渲染重构/qt-performance-median-batch-20261116-160823/summary.json) · [16:09 批次](../../my-doc/测试文件/任务20261105-桌面渲染重构/qt-default-performance-native-hidden-20261116-160919-221c673e/report.json) · [16:03 汇总](../../my-doc/测试文件/任务20261105-桌面渲染重构/qt-performance-idle-batch-20261116-160323/summary.json) · [15:54 汇总](../../my-doc/测试文件/任务20261105-桌面渲染重构/qt-performance-rerun-batch-20261116-155445/summary.json) · [15:51 汇总](../../my-doc/测试文件/任务20261105-桌面渲染重构/qt-performance-diagnostic-batch-20261116-155126/summary.json) |
| 虚拟窗口阈值：实验、落地与宿主验证（2026-11-16 18:46） | **已验证收益（宿主已跑，不回滚）** | 离线实验：`dist-current` 对 `dist-variant-120`，32×wheel/5580px 两次 Task 459.2/548.3→285.5/238.6ms、HitTest 267.9/319.8→98.7/82.6ms；72×wheel/12960px 1549.0→549.0ms（-65%）、跨批 3 次无 long task。落地：`App.jsx` 阈值 `>512`→`>200`，重建 JS→`index-Q-TfAU_F.js`（`sha256 c68b2f1f…`），测试 61+8+4 全过；新产物离线两次 Task 218.3/216.0ms、HitTest 73.0/73.2ms、筛选回归六步正常。**宿主 18:46 批次**（`passed`、11 用例 10 检查、异常 0、可见性违规 0、退出码 0、34s）：`library-down` Task 590.9/594.8→**315.4ms（-47%）**、Layout 49.1→28.3、p95 33.3 不变；`library-up` 308.0/299.4→**159.1ms（-47%）**、Layout 51.0→14.0、最长帧 66.7→49.9、超 50ms 帧 1→0；`library-reverse` 407.7→**218.4ms（-45%）**、p95 16.8 不变；其余 8 用例 p95 与基线一致，`book-hover` Task 624.8→353.2、`open-reader` 156.3→126.7。唯一上升项 `library-down` Style 0.8→8.0ms（跨批挂 `motion-ready`）。[宿主报告](../../my-doc/测试文件/任务20261105-桌面渲染重构/qt-default-performance-native-hidden-20261116-184645-c0c4fcfd/report.json) · [预登记与结论](../../my-doc/测试文件/任务20261105-桌面渲染重构/virtual-window-20261116-1800/预登记-宿主批次.md) |
| 阅读页结构空闲预热（2026-11-16 19:05–19:40） | **已否证并回退（宿主零收益）** | 离线（tracing，每臂 3 次）：窗口内 Layout 31/29/45→9.3/14.2/11.5ms、`LayoutDuration` 0.031–0.045→0.009–0.014s、卡顿段 46–69→17–31ms、脏对象仍 337/394；预热自身 79ms `longtask`、199 元素、`visibility:hidden`、两帧后卸除。宿主 19:25 批次（`index-D6FC2Ozb.js`，页面侧 `passed` 12 用例）：`TaskDuration` 0.1283→0.1278、`LayoutDuration` 0.0073→0.0089、长任务 64→65ms、打开耗时 258→273ms、p95 133.3 不变——**全在噪声内**。根因：宿主首次阅读页布局只有 7.3–8.0ms，离线 tracing 抬高约 4 倍。代价：`library-down` `>50ms` 帧 0→3（2.1%）、最长帧 50→83.3ms，`book-hover` 最长帧 116.6→200ms。已回退，重建产物与 18:33 逐字节相同（`index-Q-TfAU_F.js`，`sha256 c68b2f1f…`）。批次退出码 1 仅因 1390 条系统输入指示窗可见性违规（`InputSwitch.dll`）。[预热证据](../../my-doc/测试文件/任务20261105-桌面渲染重构/reader-warmup-20261116-1930/summary.json) · [宿主报告](../../my-doc/测试文件/任务20261105-桌面渲染重构/qt-default-performance-native-hidden-20261116-192533-abef3671/report.json) |
| 打开正文后端成本：音频会话枚举（2026-11-16 19:45–20:00） | **已修复（宿主 A/B 通过）；首次开书未变** | 新增宿主诊断相位 `open-split`（页面 `qt.webChannelTransport.send/onmessage` 打点，只测不改）：`pointerdown`→`openReaderBook` 发出 5.5–13.9ms、回执 17ms、`readerOpened` 事件 **367–419ms**、事件→首块→下一帧 30–55ms。离线边车（真实 service，只套计时）拆 worker：重复开书 216–228ms 中 **198–203ms 是 `set_volume`→`_set_process_volume`**；`AudioUtilities.GetAllSessions()` 本机 253.6–481.3ms（7 会话），首次开书 0.6ms 是 COM 未初始化异常走 MCI。改 `tts_engine.py`（+39/−9）：同值不再申请 OS 音量 + 缓存 `ISimpleAudioVolume`。宿主同相位各三次：重复开书 **298.1/411.3/567.5 → 202.2/209.0/178.4ms**、设置往返 **409.4 → 54.8/66.4/50.9ms**；实验室 worker 216–228→25–33ms。标准批次 `open-reader` ready 275.5→204.8（中位，同机负载波动大）。`tests/test_speech_volume.py` 7 例、全量 325 例通过；前端产物未动。[结论](../../my-doc/测试文件/任务20261105-桌面渲染重构/open-book-backend-20261116-1955/结论.md) · [打点批次](../../my-doc/测试文件/任务20261105-桌面渲染重构/qt-default-open-split-native-hidden-20261116-195031-71325744/report.json) |
| 打开正文 128ms 成本拆解（2026-11-16 19:00–19:40） | 已完成（离线七臂；产品零改动）；布局绝对值已修正 | 同一产物、同一 300 本夹具、同一 `pointerdown→首块→下一帧` 窗口。阶段：指针到请求 6–10ms（task 4–7）、请求到响应 17–28（12–27）、响应到事件 **257–375（task 18–32，占用 7%–9%）**、事件到就绪 **46–69（task 45–69，占用 ~100%）**。窗口内 4 次 Layout，只有 `dirty=337/394` 那次慢（41.38/29.02/40.28ms）。否证：1000→30 章 Layout 31（30–38）、40→3 块 34（31–35）、`visibility:hidden` 30（29–32）——都不低于 baseline 的 43（31–45）。暖化：同书第二次 Layout **3**、异书 **5**，卡顿段 56→10–14。`prewarmText`（40 段同字号中文、21px/17px 各 3 次）`LayoutDuration` 仍 0.030–0.031s，文字预热无效。软件合成口径 `validForComparison=false`。[结论](../../my-doc/测试文件/任务20261105-桌面渲染重构/open-reader-cost-20261116-1900/结论.md) · [汇总](../../my-doc/测试文件/任务20261105-桌面渲染重构/open-reader-cost-20261116-1900/summary.json) |
| `open-reader` 采样加长（2026-11-16 18:53） | **已验证：133ms 为单次过渡帧** | `benchmark.mjs` 在 `open-reader` 之后插入 `open-reader-settle`（已打开后 1500ms 固定窗口），`open-reader` 原样保留以维持历史可比；`sha256` 由 `18aea73d…`→`1517ef4a…`，产品产物未动。批次 `qt-default-performance-native-hidden-20261116-185312-3ad61d69`：`passed`、12 用例 10 检查、异常 0、可见性违规 0、退出码 0、40s。`open-reader` 11 帧 p95 133.3（未变）；**`open-reader-settle` 91 帧 p95 16.7、最长 16.8、>50ms 帧 0**、Task 32.2ms/1500ms（2.1%）、Layout 0；打开耗时 335.6/331.5→275.5/258.0ms（历史抖动大，不算确定收益）。其余 11 用例 p95 与 18:46 完全一致。[报告](../../my-doc/测试文件/任务20261105-桌面渲染重构/qt-default-performance-native-hidden-20261116-185312-3ad61d69/report.json) |
| 滚动路径 CSS 优化尝试（2026-11-16 16:34） | 已否证并回退 | 干净批次审计通过、退出码 0，但无一用例改善，`library-up` Layout 51–64→172ms、Style 61–85→221ms、p95 16.8→33.3ms。两条规则已删除；重建后 `index-Cj4hGzgN.css`（70738 bytes）与 `index-BH9Vkab0.js` 与 11-12 版本同名同字节，产品回到原状。[汇总](../../my-doc/测试文件/任务20261105-桌面渲染重构/qt-scroll-optimization-batch-20261116-163329/summary.json) |
| Qt Quick 双窗、落盘和自然退出 | 第一节点未通过 | UTF-8 修正版宿主完成服务握手，随后因远程调试警告停批。双窗实际渲染、落盘和自然退出未取得完整证据。[执行记录末节](执行记录.md#2026-11-12-quick-第一节点-utf-8-修正版隐藏验收停止) |
| 正式桌面与听音 | 待验 | 启动闪帧、拖缩、跨屏、浮窗往返和真实朗读由用户安排后验证。 |
| 编译、数据库、接口、联调和发布 | 本轮执行了构建与一次宿主批次 | 阅读页预热实现了两版并各跑过构建：预热版 `index-D6FC2Ozb.js`、回退版重建回 `index-Q-TfAU_F.js`（`sha256 c68b2f1f…`，与 18:33 逐字节相同）。宿主批次 `qt-default-performance-native-hidden-20261116-192533-abef3671` 页面侧 `passed`、退出码 1 仅因系统输入指示窗可见性违规。无关键 SQL、无接口变更、未发布。 |

## 5. 已知问题和风险

- Qt 批次使用 `desktop-lab/qt_host.py` 加载现有阅读器宿主，Qt 版本为 6.8.3。控制器的 50 ms 轮询记录了 HWND、类名、PID 和 TID，缺少窗口注册模块、首次创建时间与 Qt 初始化阶段。旧 Tauri 批次曾将同名窗口归属到 `InputSwitch.dll` 和 `SogouPY.ime`，可作为本次采样线索。Qt 批次的模块来源及触发条件仍待核对。[Qt 窗口归属记录](../../my-doc/测试文件/任务20261105-桌面渲染重构/qt-default-qt-smoke-native-hidden-20261112-203814-f973b539/ownership-and-resources.json) · [Tauri 模块归属证据](../../my-doc/测试文件/任务20261105-桌面渲染重构/p2-native-repair-diagnostic-v11-20261106-135500/结论.md)
- Qt Quick 最近宿主批次已结束，首故障、随后观察到的原生可见窗口和清理兜底均需保留。后续如重启候选，应重新确定验收前提和本轮授权。[Quick 离线诊断](../../my-doc/测试文件/任务20261105-桌面渲染重构/quick-node1-offline-diagnosis-20261112-174803/诊断结果.md)

- 前台归属审计的采样密度由外部桌面事件决定：`sample_foreground` 只在 start/end 与"前台发生变化"的 poll 追加，五批 performance 实测 17/13/12/4/2 个采样点（poll 15/11/10/2/0）。桌面完全静止时只剩 2 个端点采样，"通过"的检测覆盖最弱；桌面有活动时采样变多，反而更易撞到前台切换瞬间的空读数。故"通过/失败"不能等量解读为被测程序合规程度。判据未改动，改法（固定频率采样、或仅 Job 前台判失败）需单独授权。

## 6. 已尝试但废弃或修正的方案

| 方案 | 结果 | 原因/最终处理 |
|---|---|---|
| Tauri 性能与窗口能力验证 | 暂缓采用 | 最后独立收敛未得到满足门槛的候选，原 P2 未通过。[最终结论](../../my-doc/测试文件/任务20261105-桌面渲染重构/p2-final-convergence-20261106-195801/结论.md) |
| 设置文字整批或分批预热 | 暂未采用 | 分批预热完成后首开更快，提前点击仍有退化样本，空闲回调也出现预算超支。[分批对照结果](整体流畅度实施计划.md#设置分批文字预热对照2026-11-12) |
| "严格前台判据在长批次不可满足"（15:54 结论） | 已撤回，命题不成立 | 该批期间用户实际操作鼠标，前提失效；16:03 与 16:09 两个安静批次均干净通过（前台采样全部有效）。 |
| 阅读页结构空闲预热（2026-11-16 19:25） | 已实施并回退，宿主假设否证 | 离线 tracing 显示首次布局 31–45→9–12ms，但宿主 `LayoutDuration` 仅 7.3–8.0ms，改动后 8.9ms；`Task` 0.1283→0.1278、长任务 64→65ms、打开耗时 258→273ms 全在噪声内。预热 79ms 空闲任务还把 `library-down` 的 `>50ms` 帧从 0 推到 3（2.1%）。源码回退，重建产物 `index-Q-TfAU_F.js` 与 18:33 逐字节相同。[预热证据](../../my-doc/测试文件/任务20261105-桌面渲染重构/reader-warmup-20261116-1930/summary.json) |
| 以单批 p95 作为优化前基线 | 已废弃 | 五批实测波动大（`book-hover` p95 83.3–250.0、`open-reader` 16.8–150.0），改用五批 p95 中位数作参照；`open-reader` 每批仅 14–21 帧，须先加长采样窗口。 |
| 滚动期关闭每卡 blur 与 will-change（2026-11-16） | 已实施并回退，假设否证 | 干净批次无改善，`library-up` Layout 51–64ms→172ms、Style 61–85ms→221ms、p95 16.8→33.3ms。新增 `[data-scrolling="true"]` 规则扩大 subtree-wide 失效，成本超线性。规则已删，产物与 11-12 版本逐字节等价。[本轮汇总](../../my-doc/测试文件/任务20261105-桌面渲染重构/qt-scroll-optimization-batch-20261116-163329/summary.json) |

## 7. 重要技术决策

- 现有 Qt 入口承接流畅度主线。宿主性能对照使用同一视口、刷新率、主题和合成书库。浏览器对照用于定位页面开销，正式桌面呈现和听音各自验收。[场景、条件与实施顺序](整体流畅度实施计划.md)
- 隐藏实验保持独立数据、静音和窗口归属检查。出现可见窗时按既定判据停止，保留原始失败结果，工作区和已有书库按[原任务隔离边界](任务计划.md#隔离方式与回退)保护。
- 渲染模式改为**默认硬件加速、可选回退软件合成**（`settings.render_mode` 开关，默认 `hardware`）。依据：透明+硬件合成实测 `book-hover` 16.7ms 丝滑且圆角保留，而透明+软件合成 83.4ms 是卡顿根因。`software` 仅作驱动异常时的回退。**11-17 11:45 已验证落地效果**：私有桌面批次 `graphicsApis=Direct3D11`（旧代码为 `Software`）。根因与证据见 [卡顿根因分析](卡顿根因分析.md)。
- **「不闪屏+丝滑」兼得 → 主窗口改不透明直角窗口（14:38 落地）**。闪白根因是「透明窗口 + 硬件加速」下 QtWebEngine 的 backing-store 交接整帧丢失（平台级限制，非业务 bug），v2.1.7 曾因此回退软件合成。绕开透明合成即可兼得：主窗口不透明直角（`WA_TranslucentBackground=False` + `#f7f9fc` 背景 + `--main-window-radius:0px`），硬件加速保留（`graphicsApis=Direct3D11`）且不闪白。**悬浮窗保持透明不变**（半透明朗读窗必须透明）。Win10 下 `SetWindowRgn` 圆角无抗锯齿（锯齿硬限制），故放弃蒙版圆角、采用直角。

## 8. 下一步任务

`open-reader` 的 128ms 已拆开（见第 3/4 节），但**绝对值要打折看**：离线 tracing 把首次布局从 7–8ms 抬到 27–45ms，宿主自己的 `LayoutDuration` 只有 7.3–8.0ms，所以这 128ms 不是布局主导，而是挂载阅读页那一次 React 提交（65ms 长任务里脚本 20ms、布局 9ms，其余样式/绘制/合成）。阅读页结构预热的路线已按宿主实测否证并回退（19:25），不要再试。**20:00 补：后端音频会话枚举已修（重复开书 411→202ms、设置往返 409→55ms）**。**20:30 补：音量改为按播放状态分流，静音期改音量的枚举归零（184.5ms→0）**，剩下：

1. ~~首次开书/静音时改音量仍枚举~~ **已完成（20:30）**：改为"正在朗读才立即应用，其余情况记期望值、播放起点落地"，SAPI 播放起点补应用点。注意本轮实测更正了上一条的口径——19:50 那批边车里 `set_volume` 首次开书本就只有 0.5–0.8ms（工作线程 COM 未初始化直接失败），所以开书路径没有"再省半秒"，真正修掉的是静音状态下**每次**值变化的那次枚举。证据 `volume-deferral-20261116-2015/`。
2. **200–511 本的库：已完成（离线 11-17 08:55–09:20，宿主复核 09:20–09:26），不再推进**。测试工具改动：`fixture.py`/`run.py` 的 `--books`、`--menu-books` 扩到 `[250,300,400,500,600]`，guard 允许 `performance` 用非 300，`owner.fixtureBooks` 改为所有相位写入；`benchmark.mjs` 在 `performance` 相位增采 `libraryDomBefore/After`（只增字段）。离线四个臂（250/300/400/400 复测）都判 `virtual-window`、挂载恒 64→96、Task 219–281ms 无规模趋势；负向对照用阈值仍是 512 的旧产物跑 400 本，全量挂 400 张、Task 616ms。**宿主复核结果**：300/400 两批 `libraryDomBefore/After.cards` 都是 **64/64**（标题含 300/400），400 本仍在虚拟窗口内；滚动用例与 18:46 基线同值域、无规模趋势；400 批次审计通过、退出码 0。注意宿主只采手势前后静止态，96 的峰值只有离线口径。证据 `library-scale-20261117-0900/` 与 `host-batch-scale-startup-20261117-0920/`。
3. **启动耗时：三步都已完成（离线拆解 09:05、宿主切开 09:20、`edge_tts` 按需导入 09:30）**。结构：热启动 3265ms（28 批中位）＝ 导入 1191 + `QApplication` 39 + 构造 **1576** + showEvent 116 + 循环到 load 228 + 前端加载 101；导入里 Qt 全套仅 0.21s，`novelreader.qt_host` 连带依赖 0.95s，其中 **`edge_tts` 一个包 0.31s**（已按需化，见下）；构造的大头是 QtWebEngine profile/page——**宿主两批已切开**：300/400 本构造 **1439.3/1072.5ms**，`view-created→page-created`（`QWebEngineProfile` + 拦截器 + `QWebEnginePage`，`qt_host.py` 436–442）**1369.0/1004.4ms＝95.1%/93.6%**，四个自研服务相关两段合计 20.2/23.3ms；冷批次导入 6.142s 是磁盘首次读，离线不可拆。
   - ~~**甲｜`edge_tts` 改按需导入**~~ **已完成（09:30–09:50）**：哨兵 + `_edge_tts_module()` 惰性加载，`edge_tts = None` 仍是"未安装"硬信号。热启动 **−225.1ms**（914.2→689.1 中位，配对 219–251）；代价是首次 Edge 合成 **+244.5ms**（一次性、工作线程）。回归 +3 例、全量 335 通过。**宿主已有一条就地证据**：09:45 的 300 本隐藏 performance 批次导入阶段 **852.8ms**，对同日改前 09:20 两批的 1033.4/971.9 为 −119 至 −181ms，方向与量级都对得上；仍只有一批，不作定论。**待用户主观确认**：第一次按播放多等约 0.24 秒是否可接受；若要挪走，只能改成"窗口出现后后台预热"，而那会重演 11-16 的丢帧风险（不推荐）。
   - ~~**乙**~~ **已完成（09:20）**：`product-stage` 打点在真实宿主生效，构造段已切到 95% 集中度，结论见第 3 节第二条。
   - ~~**丙**~~ **已完成（09:20）**：与第 2 条批次同一空档跑完，两批 300/400 本。
   - **构造段判断（已定论，不再反复测）**：再动只能改 Chromium 初始化——page 就是加载 UI 的那个、不能延后；持久化 profile 会改变缓存与隐私语义、首次仍要建库，收益不确证。四个自研服务的构造成本已被实测否证（20–23ms）。
4. **可见桌面验收：自动通道已跑（11-17 10:29–10:31），GPU 仍软件合成，Q1/Q2 未达标**。首次真实上屏 `--desktop active`（`visible-accept-active-20261117-102928-71f8f468`），41 秒干净退出。**决定性结果**：`graphicsApis=['Software','Software']`——窗口真上屏到 console 会话、AMD 显卡双屏，Chromium 仍拿不到 GPU（stderr `Failed to create GLES3 context` + `Failed to create shared context for virtualization`，与私有桌面完全相同）。12 用例 p95：`book-hover` **83.4**（判据 ≤21，超 4 倍，与隐藏完全一致）、`settings-open-tabs-close` **50.0**（隐藏 66.6→上屏 50.0，有降但仍超 21）、其余全过（book-menu 16.8、library 三向 33.3/16.7/16.8、open-reader-settle 16.7、reader/directory 16.7/16.8、floating-hover 16.8）。**结论**：预登记文档第 5 节"上屏后拿硬件光栅"的假设被否证——上屏没拿到 GPU，所以 Q1/Q2 依旧未达标；`book-hover` 83.4 确认为软件合成路径的稳定属性。**GLES3 失败根因未定位**（嫌疑：透明承载/驱动/QtWebEngine，非 flag）。**→ 该条已被 11:31「渲染模式开关」+ 11:45 落地验证 + 14:02 B 通道验收解决**：根因是 `QT_QUICK_BACKEND=software`，产品已改默认硬件加速，私有桌面（11:45）与真实上屏（14:02）两批均 `graphicsApis=Direct3D11`。B 人工通道已跑（14:02，真实上屏+真实音频，干净关闭）。剩「闪白」实际使用观察与打包版重新打包，仍需用户时段/长期使用。
5. **已完成，留档不再推进**：`data-scrolling` 门控移除、虚拟窗口阈值 512→200（宿主已验证）、`open-reader` 采样加长、打开正文 128ms 拆解、后端开书定位与音频会话枚举修复、音量按播放状态分流、启动耗时离线拆解、宿主两批（400 本复核 + 构造切开）、`edge_tts` 按需导入、**渲染模式开关落地（默认硬件加速，GPU 后端已验证）**。
6. **已否证，不要再试**：阅读页结构空闲预热（宿主零收益 + 79ms 空闲任务丢帧）；预热字体/预热一段同字号文字（`prewarmText` 无效）；"首屏只提交 8–10 块再增量提交"（`fewBlocks` 40→3 块时 `TaskDuration`/`LayoutDuration` 均无变化，拆开只会让"就绪"时点提前而帧不变快）。
7. **工具已完成、待宿主批次（11-17 10:20–10:35）**：给 `desktop-lab` 加"点音量按钮"诊断相位 `volume-split`，让宿主侧直接看到 volume-deferral 收益。改动 2 文件只增：`benchmark.mjs` 新增 `measureVolumeSplit()`（传输层打点 `invoke`/`webChannelTransport.send/onmessage`，记 out/in 时间戳与是否含 `updateReaderSettings`；`openReader()` 后连点音量按钮 4 次，用 label 变化当就绪条件）；`run.py` `--phase` 加 `volume-split`。设计要点：跳过 `floatingTests`（`float` 会启动朗读污染"静音态"前提）。判据：`updateReaderSettings` 的 out→in 往返应 ~几 ms（修复前 140–208ms 的 `AudioUtilities.GetAllSessions()` 枚举）。**未跑宿主批次**（需桌面空档 + 授权），命令 `--candidate qt-default --phase volume-split --render-path native-hidden --exempt-system-input-windows`。
8. ~~**待修**：`desktop-lab/qt_smoke.mjs` 仍断言 `cards===300`~~ **已修并验证（11-17 09:51–09:55）**：阈值降到 200 后 300 本只挂 64 张，`cards===300` 永不成立，冒烟必然 `OWNED_SYNTHETIC_LIBRARY_NOT_READY`。改为不再编码挂载策略——用 `.section-title span` 的"300 项内容"确认数据集全量载入，再要求挂载数在 `16…fixtureBooks` 之间（阈值无关）；`qt-smoke-page.json` 增记 `total`/`virtualized`/`fixtureBooks`。隐藏批次 `…095101-35a361b8`：`pageReady=true`、`cards=64`、`total="300 项内容"`、`virtualized=true`、`exitCode=0`、审计通过、可见违规 0。

本轮已否证、不要再试的三条：给卡片加 `content-visibility:auto`（Layout 21→160ms、LayoutCount 1→23、Task +28%）；换掉封面图或关掉投影/渐变/`backdrop-filter`（Task 略升，均在噪声内）；把滚动成本归给"每帧挂载卡片"（300 卡常驻，DOM 仅 12 条 settle 后的类切换）。

设置面板若要继续，只剩两个方向且都需新证据：该用例的宿主 p95 主要由软件合成的整屏叠加重绘决定（`settings` 的 TaskDuration 544–900ms，而 Layout+Style+Script 合计仅 117ms），真实 GPU 桌面上并不存在，故不宜再按该 p95 优化；若用户实际使用中仍感到首次打开卡顿，再考虑预热其余静态页或缩小弹层节点数。

`data-scrolling` 这条线已经关闭：加规则（16:33）与减规则（17:20）两个方向都测过，结论是这个开关本身就该去掉——祖先属性每翻转一次就要重算整棵书库子树，代价与规则条数关系不大，与"被失效的元素数"直接相关。以后若要按滚动状态改样式，先算清楚它会失效多少元素。

已知局限如实保留：**11-17 11:45 起已修正**——产品默认硬件加速落地后，私有桌面批次已拿到 `Direct3D11`（此前「私有桌面下 Chromium GPU 共享上下文创建失败」是旧代码强制 `QT_QUICK_BACKEND=software` 所致，非环境固有）。软件合成口径仅剩「`software` 回退模式」批次；`validForComparison` 与前台审计采样密度（2–12 个采样点，覆盖强度不稳定）的局限仍成立。

可比较基线仍只能来自可见桌面采样（用户安排）。豁免口径保持只覆盖三类窗口、只按批开启。

- [续接提示词](新会话启动提示词.md#继续任务-20261105)

## 9. 阶段更新规范

- 用新证据更新当前条目和最近验证时间。详细运行证据保存在原测试目录，历史候选保留原判定和失败记录。
- 阶段或退出门槛确有变化时同步对应计划章节。会话恢复以本文件第 8 节为准。

## 10. 状态变更记录

### 2026-11-17 「不闪屏+丝滑」方案落地（14:38）：主窗口改不透明直角，绕开透明合成冲突

用户要求「不闪屏+丝滑」兼得，深挖闪白根因后落地。

- **根因结论（已验证）**：闪白 = **透明窗口（`WA_TranslucentBackground`）+ 硬件加速**下，QtWebEngine 的 widget/backing-store 交接整帧丢失（v2.1.7 docstring 原文 "Accelerated Quick composition can lose entire content frames even while Chromium's rAF timings look healthy"）。非业务代码 bug，是 QtWebEngine 平台级限制（QTBUG-41960 系列）。滚动触发的重新栅格化让交接空档最易暴露。
- **方案（已落地）**：主窗口（`DesktopWindow`）改**不透明直角窗口**——`WA_TranslucentBackground=False`、`setAutoFillBackground(True)`、`QMainWindow { background:#f7f9fc }`；`_configure_main_web_view` 改不透明（page 背景 `#f7f9fc`，不再透明）；`RoundedWebEngineView` 的 `CornerClip`（软件 alpha 擦除）**仅悬浮窗启用，主窗口跳过**。悬浮窗（`FloatingReaderWindow`）**保持透明不变**（半透明朗读窗必须透明）。前端 `--main-window-radius: 0px`。
- **圆角取舍**：Win10(19043) 无系统圆角、`SetWindowRgn` 无抗锯齿（阶梯锯齿硬限制）。曾试 22px 蒙版（用户反馈颗粒感）→ 8px（用户嫌难看）→ **最终直角**（干净无锯齿）。
- **验证（已验证）**：私有桌面批次 `visible-accept-private-20261117-142113` + 真实上屏 `--hold` 三次（142238/143319/143642）。**`graphicsApis=Direct3D11`（硬件保留）、`translucent=False`（绕开透明合成）**；用户现场确认「丝滑 + 不闪白」；`driverExitCode` 从 1→0（不透明窗口尺寸更稳定，`renderer-calibration` 的 `NO_CLICK_AREA` 尺寸漂移问题一并消失）。
- **改动文件**：`novelreader/qt_host.py`（不透明+直角+`_apply_window_corners` 恢复 clearMask+DWM 偏好语义，移除 SetWindowRgn 蒙版）、`novelreader/qt_corners.py`（CornerClip 仅 floating）、`prototype/src/styles.css`（`--main-window-radius: 0px`，需 `npm run build`）。产品渲染逻辑 `qt_rendering.py` 未再改动（仍默认硬件加速）。
- **遗留**：①悬浮窗仍为透明窗口 + 硬件加速，理论上仍有低频闪白风险，但用户未反馈悬浮窗闪白（小窗 + 低频滚动）；②打包版需重新打包才带上本次改动；③测试工具 candidate 语义漂移（qt-default 现标 transparent-software 实走硬件）仍未修正，待后续厘清。

### 2026-11-17 B 人工通道验收（14:02）：真实上屏 + 真实音频，D3D11 确证；修复 10 分钟超时缺陷

用户配合跑 B 人工通道 `visible-accept-active-20261117-140208-f14beccd`（`--desktop active --hold --audio`）。

- **已验证**：真实上屏（console 会话、AMD 双屏）+ 真实音频（`--audio`），`host.json` `graphicsApis=["GraphicsApi.Direct3D11"]`、`size=[1280,720]`、`visible/exposed=true`；`hostExitCode=0`、`driverExitCode=0`、`errors=[]`、`residualPids=[]`。**真实上屏 GPU 后端 D3D11 确证**，补齐 11:45 私有桌面验证的最后一块。
- **主观观察项（用户现场观察，未结构化）**：闪帧/拖缩/跨屏/浮窗往返/真实朗读由用户实际观察确认。"闪白"历史回归仍需用户长期实际使用观察。
- **发现并修复工具缺陷（测试工具，产品零改动）**：`desktop-lab/qt_host.py` 的 `QTimer.singleShot(600000, finish)` 10 分钟硬超时会把 `--hold` 人工观察窗口强制关闭（首启 13:43 开窗、13:53 超时关窗）。修复：`visible_accept.py` 在 `--hold` 时传 `QY_LAB_HOLD=1`；`qt_host.py` 读到此变量则跳过 600s 超时（自动批次保留防挂死）。两文件 `py_compile` 通过。

### 2026-11-17 渲染模式开关落地验证（11:45）：私有桌面已拿到 Direct3D11，默认硬件加速生效

用户「继续任务20261105」后选「验证落地效果」。跑私有桌面批次 `visible-accept-private-20261117-114528-009ec942`（`--candidate qt-default --desktop private`，产品代码已改默认硬件加速）。

- **已验证（决定性）**：`host.json` 的 `graphicsApis = ["GraphicsApi.Direct3D11"]`、`configured = system`、`qtQuickBackend = None`（不再设 software）、`translucent = True`（圆角透明保留）。对照 09:40 旧代码同环境两批 `094052`/`094226` 均为 `Software` / `software-composition`。**产品落地「默认硬件加速」后，宿主在私有桌面（此前记录「拿不到 GPU」的环境）即拿到 Direct3D11 GPU 后端**——这是「渲染模式开关」从「已实现未验证」转为「已验证」的关键证据。
- **离线逻辑复核**：`configure_rendering` 四场景——无设置/`hardware`/`default` 均返回 `system`（不设 `QT_QUICK_BACKEND`），仅 `software` 走软件合成并加 `--disable-gpu`。与 11:31 记录一致。
- **未验证（环境限制）**：本批 driver 退出码 1，`renderer-calibration` 因窗口尺寸从 1280×720 漂移到 1024×576（私有桌面固有 DPI 缩放）报 `NO_CLICK_AREA:.book-open`，`book-hover` 帧时间未测到。该失败与产品落地无关；`book-hover` 16.7ms 是硬件合成的同一因果链（11:00 `qt-hardware` 上屏对照已证 83.4→16.8ms、12 用例全达标），GPU 后端切换已确证，无需重复上屏。
- **待确认（测试工具语义漂移，未改）**：`desktop-lab/qt_host.py:21` 将 `qt-default`（`QY_LAB_MODE=transparent-software`）映射为 `QYREADER_RENDER_MODE=default`，产品 `qt_rendering.py` 已改 `default≠software→system`，故 `qt-default` 现在实际走硬件加速，但工具的 candidate help 文案与 metadata `mode` 字段仍标注 `transparent-software`，会误导后续对照读数。留待与用户确认是否修正工具语义。

### 2026-11-17 渲染模式开关落地（11:31）：默认硬件加速 + 可回退软件合成，根因落档

用户选「加开关」方案，把「圆角透明」与「丝滑」同时保留。本条目登记结论分类与改动状态，详细根因分析见 [卡顿根因分析](卡顿根因分析.md)。

- **已确认事实**：卡顿根因是 `QT_QUICK_BACKEND=software` 连带让 Chromium 禁用 GPU（`gl=disabled, angle=none`），滚动/悬停动画的合成与栅格工作全部落到 CPU 主线程——10:29 上屏验收的 `book-hover` 83.4ms 即为此路径的稳定属性。**透明窗口本身不是根因**（不透明+软件合成对照 GPU 同样被禁用）。
- **已确认事实（实验证据）**：三个渲染模式帧时间对照——透明+软件合成 83.4ms、透明+强制 GPU（`--use-angle=d3d11`）333ms（`canSupportThreadedTextureMailbox=False` 反而更慢）、**透明+硬件合成（transparent-hardware）16.7ms**，12 用例全达标且圆角保留。据此默认值定为 `hardware`。
- **已实现未验证**：代码改动已落地（`qt_rendering.py` 默认硬件加速、`qt_main.py` 读持久化偏好、`storage.py`/`app_service.py`/`qt_bridge.py`/`bridge.js`/`App.jsx` 增加 `renderMode` 开关及设置项），测试 `test_qt_rendering` 4 项 / `test_app_service` 5 项 / `test:bridge` 61 项通过、`npm run build` 通过。但**尚未重启真实宿主验证默认硬件加速在透明窗下实际拿到 GPU、也未验证"闪白"是否随硬件合成重现**（v2.1.7 历史问题）。
- **待确认**：`hardware` 模式下透明窗是否稳定拿到 GPU 且不闪白，需重启软件 + 实际使用观察；打包版需重新打包 exe。



用户选 ①（上屏验收），首次跑 `--desktop active` 自动通道。批次 `visible-accept-active-20261117-102928-71f8f468`，41 秒干净退出：driver/host 退出码 0/0、errors 0、残留 0、`expectations` 三真（`visible`/`exposed`=true、`dontShowOnScreen`/`transparentForInput`=false）。产品零改动。

- **决定性结果**：`graphicsApis=['GraphicsApi.Software','GraphicsApi.Software']`、`qtQuickBackend=software`。窗口真上屏到 console 会话、AMD Radeon 双屏（DISPLAY1 + LECOO B2431E，均 1.25 DPR、60Hz），Chromium 仍走软件合成。`host.stderr` 两条：`Failed to create GLES3 context, fallback to GLES2` + `ContextResult::kFatalFailure: Failed to create shared context for virtualization`——与私有桌面**完全相同**。→ 否证预登记第 5 节"上屏后拿硬件光栅"的假设：上屏没拿到 GPU。
- 12 用例 p95（判据对照）：`book-hover` **83.4**（≤21，超 4 倍，与隐藏 83.3–100 完全一致）、`settings-open-tabs-close` **50.0**（≤21，隐藏 66.6→上屏 50.0，有降但仍超）、其余全过：book-menu-open-close 16.8（≤100）、library-down/up/reverse 33.3/16.7/16.8（≤33.4 且 >50ms<1%）、open-reader-settle 16.7、reader-scroll 16.7、directory-scroll 16.8、floating-hover-animation 16.8（≤21）。
- **Q1/Q2 判定**：仍未达标。`book-hover` 83.4 上屏后纹丝不动，确认是软件合成路径的稳定属性（长帧在合成/栅格侧，非主线程）；`settings` 上屏后 66.6→50.0（真实桌面的 DWM/vsync 带来部分改善）但不足以翻盘。
- **GLES3 失败根因未定位**：嫌疑是透明承载（transparent mode 下 Chromium 无法建 GPU 共享上下文）或驱动/QtWebEngine，**不是 flag**——此前 `QY_ARM_CHROMIUM_FLAGS=none` 已证构造耗时不变。要定位需另起一条线（如 `opaque-hardware` 对照臂），本轮未做。
- 启动全景：`load-finished` 3552.8ms，构造 3278.6ms，与前几批一致；journal 20 事件、无缺失阶段。
- 未做：B 人工通道（闪帧/拖缩/跨屏/最大化恢复/浮窗往返/真实朗读，需 `--hold --audio` 人工按回车）。证据 `visible-accept-active-20261117-102928-71f8f468/`（已 git exclude）。

### 2026-11-17 音量按钮诊断相位 `volume-split`（10:20）：工具就绪，待宿主批次

用户选第 8 节第 7 条，给 `desktop-lab` 加"点音量按钮"诊断相位，宿主侧直接量化 volume-deferral 收益。产品零改动，2 文件只增。

- 调用链（只读查证）：音量按钮 `[aria-label^="音量"]`（`player-bar`，label 动态 `音量 N`）→ `onSettings({volume})` → `updateReaderSettings` → `invokeReader("updateReaderSettings")` → Python `updateReaderSettings`（`qt_bridge.py:745`）→ `_apply_speech_settings`（`:1782`）→ `set_voice/set_rate/set_sentence_gap/set_volume`。静音态（`_state` 非 playing/paused）下 `set_volume` 只记期望值、不枚举；其余 setter 合计 <4ms（第 8 节第 1 条已证）。
- 改动：`desktop-lab/benchmark.mjs` 新增 `measureVolumeSplit()`——传输层打点（包装 `__QY_DESKTOP__.invoke` 或 `webChannelTransport.send/onmessage`，记 out/in 时间戳与是否含 `updateReaderSettings`）；`openReader()` 后 `c.wait` 音量按钮，连点 4 次、每次以 label 变化为就绪条件、串行 +250ms settle；主流程加 `report.volumeSplit` 分支与 `comparisonExclusionReason`；`takeShots`/`openReader` 通用路径/`floatingTests` 三处排除 `volumeSplit`。`desktop-lab/run.py` `--phase` choices 加 `volume-split`。
- 设计要点：**跳过 `floatingTests`**——`host('float')` 会启动悬浮朗读进入 playing，把"静音态改音量"污染成"播放中改音量"，破坏测量前提。音量 label 变化是"响应已落地并反映到 UI"的就绪信号；`before` 自适应读 DOM，不假设初始 volume。
- 验证：`py_compile run.py` 通过；`node --check benchmark.mjs` 通过；argparse 确认 `volume-split` 为合法 phase。**未跑宿主批次**（需桌面空档 + 授权），判据 `report.volumeSplit.rounds[].timeline` 中 `updateReaderSettings` 的 out→in 往返应 ~几 ms（修复前 140–208ms）。
- 命令：`.venv/Scripts/python.exe -B desktop-lab/run.py --candidate qt-default --phase volume-split --render-path native-hidden --exempt-system-input-windows --menu-books 300`。

### 2026-11-17 可见渲染路径打通（09:40）：窗口能上屏、隐藏路径未变，21ms 两项仍待上屏判定

新增 `desktop-lab/visible_accept.py`（不改 `run.py` 的审计分支），`qt_host.py` 加默认关闭的 `QY_LAB_VISIBLE`/`QY_LAB_AUDIO` 并让 `metadata()` 报告真实可见性。私有桌面两次管线验证全绿（`driver/host=0/0`、`exposed=true`、残留 0），`book-hover`/`settings` 的 p95 与隐藏批次一致到 0.1ms，说明这两个数与窗口可见性无关，是软件合成路径的稳定属性。隐藏路径未变：冒烟自有可见窗 0 条（80 条全为系统输入指示窗 pid 36816）、300 本性能批次 `exitCode=0`、`cards 64/64`。顺带得到 `edge_tts` 懒加载的首条宿主就地证据（导入 852.8ms vs 同日改前 971.9/1033.4）。**仍未上屏**：21ms 门槛、启动闪帧、拖缩/跨屏/浮窗往返、真实朗读需要用户给一次时段，流程见 `正式桌面验收预登记.md`。产品代码零改动。

### 2026-11-17 `edge_tts` 按需导入：热启动 −0.225 秒，首次 Edge 朗读 +0.244 秒（一次性）

用户"继续"，落地第 8 节第 3 条的甲。产品改动 1 文件 2 处，回归 +3 例。

- 改法：`novelreader/tts_engine.py` 顶层 `try: import edge_tts / except: edge_tts = None` 换成 `_EDGE_TTS_UNLOADED = object()` 哨兵 + `_edge_tts_module()`（首次调用才 import，成功写回模块、失败写回 `None` 并保持不重试）；`synth_audio` 改 `module = _edge_tts_module()` 与 `module.Communicate`。`RuntimeError("edge-tts 未安装")` 文案与抛点位置不变，`_synth_audio_governed` → `EdgeSynthesisError` → 一次性 SAPI 回退整条路径不变。
- **为什么用哨兵**：`edge_tts = None` 在现有代码与 `test_edge_resilience.setUp`（`mock.patch.object(tts, "edge_tts", None)`）里是"未安装"的硬信号。若用 `None` 表示"还没加载"，加载器会覆盖测试桩、并把"忘记打桩"的用例真的放去联网，SAPI 回退也会被误触发。
- 测量（干净子进程，三臂各 3 次）：`startup-new` 689.1/704.1/661.0（中位 **689.1**）vs `startup-old` 922.6/912.6/914.2（中位 **914.2**）→ **−225.1ms**，配对差 219–251；旧臂内部单独计 `edge_tts` 236–238ms；`first-play` 249.0/239.6/244.5（中位 **244.5**）。比 09:05 消融估的 314ms 小，因为那次是"已加载 Qt 的进程内屏蔽 import 的增量"，这次是端到端 A/B；取 −0.22 至 −0.25 秒，占热启动 7–9%。
- 启动路径核对：`import novelreader.qt_host` 之后、`SpeechController()` 之后、`set_voice("zh-CN-XiaoxiaoNeural")` 之后、`list_edge_voices()`（9 个静态音色）之后、`shutdown()` 之后，`edge_tts` 都不在 `sys.modules`。第一次导入落在 `synth_audio`，且在 `asyncio.wait_for` 之外，不吃 30 秒合成预算。
- 回归：新增 `EdgeLazyImportTests` 3 例（子进程断言未加载、加载器幂等且不覆盖 `None`、缺包抛原文案且只调一次加载器）；`python -m unittest discover -s tests -p "test_*.py"` **335 例通过**（原 332+3）。
- 取舍：0.23 秒只能挪不能消。选"第一次 Edge 朗读"，因为用户抱怨的是启动、导入在工作线程不卡 UI、SAPI 用户永不付。备选"窗口出现后后台预热"未采用——启动后约 0.3 秒 GIL 占用会散到界面线程，与 11-16 阅读页预热（79ms 空闲任务丢帧被判失败）同型。
- 未验证：真实宿主首次朗读的主观延迟；宿主启动批次（跨批噪声 2.4–3.2 秒，单批分离不出 0.23 秒）；真实网络下的首次合成（本轮不触网）。
- 证据 `edge-tts-lazy-20261117-0930/`（`结论.md`、`measure-lazy.json`、`measure_lazy.py`），待 git exclude。

### 2026-11-17 宿主两批（09:20）：400 本仍 64 张卡、审计通过；构造 1.0–1.4s 的 93–95% 在 profile/page

用户选"丙"：一次桌面空档同时跑 300 本（同代码对照）与 400 本（规模复核），并让新打点把构造段切开。产品零改动。

- 批次：`qt-default-performance-native-hidden-20261117-092034-df05bd52`（300 本）与 `…-092145-a3fb6fa8`（400 本）。两批页面侧均 `passed=true`、12 用例、`errors=[]`、可见窗违规 0、`hostExitCode=0`、`activeProcesses=0`、无残留 PID 与 CDP 监听。**400 那批审计通过、退出码 0**；300 那批判 `foreground-attribution-failed`——13 个前台采样里 1 个 `hwnd=null/pid=0`（该批 22 次空桌面轮询），按原判据不豁免不重试。
- 规模复核（第 8 节第 2 条）：`libraryDomBefore/After.cards` 300 本 64/64、400 本 64/64，标题分别含 300/400；全量挂载会是 400，**虚拟窗口在 400 本下仍生效**。宿主只在手势前后采静止态，峰值 96 仍是离线探针口径。滚动横向：400 vs 300 的 `library-down` 33.3/311.4 vs 49.9/356.1、`library-up` 16.8/148.2 vs 16.8/152.4、`library-reverse` 16.7/254.9 vs 16.8/190.0，与 18:46 基线（33.3/315.4、16.7/159.1、16.8/218.4）同值域，**无规模趋势**。
- 构造切开（新打点已生效，每批 journal 20 行含 7 条 `product-stage`）：`qapplication-created → mainwindow-constructed` 300 本 **1439.3ms** / 400 本 **1072.5ms**；其中 `view-created → page-created` **1369.0 / 1004.4（95.1% / 93.6%）**，即产品 `qt_host.py` 436–442 行的 `QWebEngineProfile` + 拦截器 + `QWebEnginePage`；`page→speech` 4.6/5.9、`speech→bridge` 15.6/17.4（四个自研服务合计 20.2/23.3ms，1.4%/2.2%）、`bridge→channel` 2.9/2.8、`channel→load` 4.6/3.2、`load→constructed` 16.3/15.2；未打点部分（`super().__init__` + `_init_render_lifecycle`）3.5/3.0ms，闭合误差 ≤0.2%。
- 口径修正：上次说"宿主 vs 离屏差的 1.2 秒属平台"，现在定位到**差额全在 profile/page 这一段**（离屏 338ms vs 宿主 1004–1369ms），不是分散在各处；四个自研服务的构造成本已被两批实测否证（20–23ms）。
- 启动全景两批：合计 **3168.3 / 2447.2ms** = 导入 1033.4/971.9 + `QApplication` 44.2/36.9 + 构造 1439.3/1072.5 + showEvent 118.4/90.8 + 循环→load 273.1/200.8 + 前端加载 246.9/63.9，均在历史 2564–5244 区间内，7 条新增 `product-stage`（每条一次 `fsync`）未观察到抬升（但两批不足以证明零开销）。
- 判断：构造段可以收口——要再动只能改 Chromium 初始化（持久化 profile / 延后建 page），而 page 就是加载 UI 的那个、不能延后，持久化 profile 改变缓存与隐私语义且首次仍要建库，收益不确证。**甲（`edge_tts` 懒加载，−0.31s）仍是唯一已定量、可直接做的启动优化**。尺寸这条线（200–511 本）可收口。
- 证据 `host-batch-scale-startup-20261117-0920/`（`结论.md`、`summary.json`、`summarize.py`），已 git exclude。

### 2026-11-17 启动耗时离线拆解：3.265s 里导入 1.191s、构造 1.576s，edge-tts 占 0.314s

用户"继续任务"，第 8 节第 3 条。宿主批次要空档，先做不占空档的部分：把"脚本起点 → 前端加载完成"拆成可归属的分段，产品零改动。

- 宿主侧（只读汇总 29 份 `startup-stages.jsonl`，28 热 + 1 冷，`summarize_host_stages.py`）：导入 **1191ms**（997–2320）、`QApplication` 39ms（29–90）、主窗构造 **1576ms**（1160–2699）、首次 showEvent 116ms（84–311）、循环→`load-started` 228ms（171–494）、前端加载 101ms（64–169）、**合计 3265ms**（2564–5244）。冷批次（11-16 15:41）导入 **6142ms**、合计 **8823ms**——同一夹具冷热差 5.5 秒全在导入，是磁盘首次读 DLL。
- 导入分解（`measure_import.py` 序列臂，单进程逐段增量、3 次）：`QtCore` 140.4 / `QtGui` +10.5 / `QtWidgets` +5.8 / `QtWebEngineCore` +54.6 / `QtWebEngineWidgets` +3.3 / `novelreader.qt_host` **+947.2**，合计 1145.9ms（982.3–1344.3），与宿主 journal 中位对得上。**Qt 全套只占 0.21s**。
- 消融（`sys.modules[name]=None` 模拟未安装，各 3 次中位）：基线 1080.6 → 屏蔽 `edge_tts` **766.5（−314.1，−29%）**、屏蔽 `pyttsx3` 1010.1（−70.5）、两个都屏蔽 755.8（−324.8，与单屏蔽 edge 只差 10ms，重叠在 comtypes 一侧）。代码核对：`edge_tts` 全文件只出现在 `synth_audio`（422/429）与顶层 try-import，只服务 Edge 音色后端。
- 构造分解（`measure_window.py`，`offscreen` QPA、不 `show()`、真 400 本夹具、真 `DesktopWindow`、构造器包装计时，5 臂中位）：合计 **391.7ms**（373.9–439.5），`QWebEngineProfile` **300.4（77%）**、`QWebEnginePage` 37.8（10%）、`DesktopBridge` 17.3（4%）、`RoundedWebEngineView` 0.4、`QWebChannel` 0.2、`LibraryQueryService`/`SpeechController`/`PlaybackService`/`ReaderService` 各 0.0–0.1ms。**绝对值不可搬运**：宿主同段 1576 vs 离屏 392；`QY_ARM_CHROMIUM_FLAGS=none` 两次仍 391.7/373.9，DPR 1.25 一次 510.8，差的约 1.2s 属平台（原生窗口/真 QPA 下的 Chromium 初始化）。顺带否证"启动时少读一次书库"这类方向——四个自研服务是懒加载，构造不读数据。
- 测试工具改动 1 处（只增不改）：`desktop-lab/qt_host.py` 在 `import novelreader.qt_host as host` 后加 `host._qa_trace = lambda message: journal.mark("product-stage", stage=message)`，把产品已有的 7 个构造子阶段镜像进 journal，下次宿主批次即可切这 1576ms；既有事件名不变，`locate_stage` 取"≤ 时间戳最后一条"不受影响。代价：每条 `mark` 的 `fsync`（估 1–3ms/条）。
- 验证：`py_compile` 通过；`desktop-lab` 离线套件 308 项跑完 307 通过，唯一失败 `test_p2_exit_contract_v10`（历史 P2 v21 归档缺 `controlled-create-failure-512b7236` 子目录，该用例不 import `qt_host`，与本改动无关，未修）。新打点**未在真实宿主验证**（已实现未验证）。
- 下一步三选一：甲 `edge_tts` 改按需导入（−0.31s，需确认 Edge 首句延迟）；乙 跑带 `product-stage` 的宿主批次；丙 把乙并进 200–511 本那条批次（推荐）。
- 证据 `startup-cost-20261117-0915/`（`结论.md`、`summary.json`、`import-cost.json`、`window-construction-*.json`、`host-stages-summary.json`、4 个脚本、`data-400/`），已加 `.git/info/exclude`。

### 2026-11-17 200–511 本的库：宿主入口放开，离线 250/300/400 全部走虚拟窗口

用户引用第 8 节第 2 条（"200–511 本宿主实测，要改测试工具 + 1 分钟空档"）后说"继续"。先改工具、再离线取证，宿主批次留待空档。

- 工具改动 3 处（产品零改动）：`desktop-lab/fixture.py` 的 `--books` 由 `[300,600]` 扩到 `[250,300,400,500,600]`；`desktop-lab/run.py` 的 `--menu-books` 同步并补 help、guard 改为"非 300 仅 menu-boundary 与 performance"、`owner.fixtureBooks` 所有相位写入（`benchmark.mjs` 第 18/24/525 行靠它等标题，否则 400 本会等 `300` 超时）；`desktop-lab/benchmark.mjs` 在 `performance` 相位三个滚动用例前后增采 `libraryDomBefore/After`（`.book-card` 数、`scrollTop`、标题），只增字段。
- 工具验证：`py_compile` / `node --check` 通过；`--phase windows --menu-books 400` 被 guard 正确拒绝（`a non-300 fixture is only for the menu-boundary and performance phases`）且不产生批次目录。合法组合会直接开跑宿主批次，无空档时不触发。
- 夹具自检：`--books 400` 1.2 秒生成，`library.json` 400 条、`fixture.json` `books=400`、4.7MB。
- 离线探针 `library-scale-20261117-0900/probe-scale.mjs`（复用 `browser.mjs`，`--books` 参数化、build 支持绝对路径；32×wheel `deltaY=180`、45ms 间隔、400ms settle，累计 5760px）：`scale-250` Task 281ms/Layout 15ms、`scale-300` 228/8、`scale-400` 219/9、`scale-400-b` 261/9，四臂全部 `virtual-window`、挂载恒 64→96、`moved=32`。
- 负向对照 `scale-400-threshold512`：同一 400 本夹具、旧阈值产物 `index-C3BnI7BJ.js`（`virtualLibrary = books.length > 512`）→ `full-mount`、挂 400 张、Task **616ms**、Layout 27ms。探针能区分两种状态，当前产物在 400 本把 Task 压掉约 64%。
- 判据：阈值在 250–400 全部生效（挂载数与库存无关）；无规模趋势（虚拟窗口臂 219–281ms 落在同区间）；绝对值仅软件合成口径，不可外推。
- 未做：宿主批次（需桌面空档与授权）。命令与预期判据（`report.libraryDomBefore/After.cards` 应在 96 附近）写在证据目录 `结论.md`。
- 证据 `library-scale-20261117-0900/`（`结论.md`、`summary.json`、4 个 `scale-*/scale-*.json`、`probe-scale.mjs`、`browser.mjs`、`fixture-400/`），已加 `.git/info/exclude`。

### 2026-11-16 音量改为播放起点应用：静音期改音量的 184ms 枚举归零

用户"继续"。第 8 节第 1 条，但开工程序变了：先读代码确认前提，再动手。

- 前提（只读查证）：`qt_bridge._apply_speech_settings` → `set_volume` 是唯一枚举入口；`_set_process_volume` 全文件只有一个调用点 `_speak_edge_play`（每句播放前），**SAPI 走 `_engine.say()` 完全不调用它**——所以 SAPI 不能直接摘掉 `set_volume` 的应用，必须把应用点补到它自己的播放起点。
- 改动 `novelreader/tts_engine.py`（+45/−9）：`set_volume` 持锁判断状态，值没变直接返回，值变了且 `_state in ("playing","paused")` 才 `_apply_volume`，否则只记 `_volume`、保持待应用；新增 `_apply_volume`（成功且值仍是最新才记账，失败待重试）与 `_apply_pending_volume`（播放起点入口，已一致则零开销）；`_speak_sapi` 在 `say()` 前补一次；`_speak_edge_play` 原 `_set_process_volume(self._volume)` 换成 `_apply_pending_volume()`（`_mci_set_volume` 保留）。
- 证据 A（`measure_volume_change.py`，真实 pycaw、本机 7 个会话、测量进程自身无音频流）：静音改音量旧路径 **208.4/184.5/140.9ms（中位 184.5）→ 新路径 0.0/0.0ms**；播放中改 222.1/204.9/177.3ms（**保持即时**，不变）。旁证：旧路径三轮 `oldPathResolved` 全为 false——静音时枚举跑完 140–208ms 却找不到本进程会话，本来就没有作用对象。
- 证据 B（`measure_open_backend.py` 三批 18 次开书）：`set_volume` 全部 0.0ms、`_set_process_volume` **0 次调用**、`_apply_speech_settings` 最大 4.1ms、worker 23.0–30.6ms（中位 24.7）、开书总耗时 31.4–60.1ms。
- **口径更正**：19:50 那份证据把"重复开书 216–228ms 里 198–203ms 是 `set_volume`"当成了当批数据，复核 `open-book-backend-20261116-1955/timings-*.json` 后可见那批已是上一轮修复后的记录（`set_volume` 首次 0.5–0.8ms、重复 0.0ms），198–203ms 来自更早的 profile 批次。所以本轮对开书没有"再省半秒"，只关掉了"进程首次且音量值与默认不同时会枚举一次"这条残留。
- 测试：`tests/test_speech_volume.py` 由 7 例改扩为 14 例（新增静音延迟、暂停即时、播放起点落地、失败重试、SAPI 起点先于 `say`），全量 **332 例通过**（原 325）。
- 前端产物与测试工具零改动（仍 `index-Q-TfAU_F.js`，`sha256 c68b2f1f…`）。证据 `volume-deferral-20261116-2015/`（`结论.md`、`summary.json`、两份原始 timings、两个 harness、`summarize.py`）。
- 局限：SAPI 全新进程首句前可能还没有音频会话，那一次 apply 会失败、首句沿用默认音量——与改动前等价（改前在开书时调用同样无会话），不是本轮倒退；彻底解决要用 `ISpVoice::Volume`，未做。未做听音与宿主批次。

### 2026-11-16 打开正文的主项在后端：每次开书都在枚举音频会话（250–480ms），已修

用户"继续"。先给真实宿主打点（新增诊断相位 `open-split`，在页面 `qt.webChannelTransport` 的 `send`/`onmessage` 上记录时间戳，只测不改）：

- `pointerdown` → `openReaderBook` 发出 5.5–13.9ms → requestId 回执 ~17ms → **`readerOpened` 事件 367–419ms** → 首个正文块 → 下一帧 **30–55ms**。打开始终是"等后端"，渲染只占几十毫秒；上一轮"128ms 是渲染提交"的判断只覆盖了末尾那一小段。
- 离线边车 `measure_open_backend.py`（真实 `desktop-lab/service.py`、真库真缓存、只套 `perf_counter`）拆 worker：重复开书 216–228ms，其中 **`_apply_speech_settings` 201–207ms → `set_volume` 198–203ms → `_set_process_volume` 198ms**；`open_book` 21–25ms（`read_cache` 16–19ms）、`get_session_content` 1ms、`bind_session` 0.7ms。
- 单独测 `AudioUtilities.GetAllSessions()`：253.6 / 299.1 / 311.4 / 481.3ms（7 个会话）。首次开书 0.6ms 是因为工作线程 COM 未初始化、异常后走 MCI 回退；一旦 COM 可用，之后每次开书、每次改阅读设置都要付这个枚举。
- 修复（`novelreader/tts_engine.py`，+39/−9）：`set_volume` 值没变就不再申请 OS 音量（进程会话音量会保持，播放起点 `_speak_edge_play` 本来就会重新应用；应用失败不记录、下次重试）；`_set_process_volume` 缓存 `ISimpleAudioVolume`，失效时清空重解析。新增 `tests/test_speech_volume.py` 7 例，全量 325 例通过。
- 宿主 A/B（同相位、同终点、各三次）：重复开书 **298.1/411.3/567.5 → 202.2/209.0/178.4ms**（中位 411→202），`readerOpened` 到达 367→88ms；字号一次设置往返 **409.4 → 54.8/66.4/50.9ms**。首次开书不变（仍付一次枚举）。
- 标准 `performance` 批次本轮四批（195102/195216/195523/195624）：`open-reader` ready 391.3/218.3/119.2/191.3（中位 204.8），改动前今日中位 275.5；但同批 `book-hover` `TaskDuration` 449→899ms，机器负载波动大，**批次级只作参考**，判断以 `open-split` 的相位 A/B 为准。
- 测试工具改动：`desktop-lab/benchmark.mjs` 新增 `open-split` 相位（`sha256 19a1dfbf…`），`desktop-lab/run.py` 相位白名单加同名项；`open-reader` 原样保留。前端产物未重建（仍 `index-Q-TfAU_F.js`，`sha256 c68b2f1f…`）。
- 否证记录：`fewBlocks`（40→3 块）在 metrics 口径下 `TaskDuration` 0.105/0.151/0.156、`LayoutDuration` 0.031/0.034/0.035，对基线 0.108/0.098/0.174 与 0.043/0.031/0.045 无收益 → "首屏只提交 8–10 块"这条方向关闭。

### 2026-11-16 阅读页结构空闲预热：离线降七成、宿主零收益，已回退并修正布局口径

用户"先做1"。实现：空闲时把真实 `NativeReader`（合成 state、30 段中文、默认 `微软雅黑 17px/1.5`）渲染进 `visibility:hidden` 宿主，宿主按 `.content-area` 实测矩形定位，调度串在设置预热之后，两帧后卸除。

- 离线（tracing，每臂 3 次）：窗口内 Layout 31/29/45→9.3/14.2/11.5ms、`LayoutDuration` 0.031–0.045→0.009–0.014s、卡顿段 46–69→17–31ms、脏对象仍 337/394；预热自身 79ms `longtask`、199 元素、宿主 664px 高。
- 宿主 19:25 批次（产物 `index-D6FC2Ozb.js`，页面侧 `passed` 12 用例）：`TaskDuration` 0.1283→0.1278、`LayoutDuration` 0.0073→0.0089、长任务 64→65ms、打开耗时 258→273ms、p95 133.3 不变——零收益。
- 代价：`library-down` `>50ms` 帧 0→3（2.1%，触到 1% 判据）、最长帧 50→83.3ms；`book-hover` 最长帧 116.6→200ms。
- **口径修正**：宿主首次阅读页布局一直只有 7.3–8.0ms，离线 tracing 抬高约 4 倍；"128ms 里七成是布局"在真实宿主上不成立（65ms 长任务：脚本 20ms、布局 9ms，其余样式/绘制/合成）。
- 处理：源码与样式回退，重建产物与 18:33 **逐字节相同**（`index-Q-TfAU_F.js`，`sha256 c68b2f1f…`；`index-BUgJh7pn.css`），产品零残留。批次退出码 1 仅因 1390 条系统输入指示窗可见性违规（`InputSwitch.dll`），非本程序窗口。

### 2026-11-16 打开正文 128ms 拆解：一次性首次布局占七成，打开耗时的大头在后端

- 用户说"继续"后推进第 8 节第 2 条。新证据目录 `open-reader-cost-20261116-1900/`：`probe-open.mjs`（与宿主 `open-reader` 同选择器、同就绪条件、同终点，`mouseMoved→mousePressed→mouseReleased`，命中后等下一帧 rAF）、`analyze_open_cost.py`（marker 窗口内主线程任务并集、事件并集与嵌套感知 self time、`FunctionCall` 按函数名聚合、Layout 脏对象、阶段墙钟/占用）、`browser.mjs`（沿用 `virtual-window-20261116-1800` 的离线链路）。
- 阶段标记打在应用真正用的传输层（包 `__QY_DESKTOP__.invoke/subscribe` 打 `console.timeStamp`）：指针到 `openReaderBook` 发出 6–10ms（task 4–7）、请求到响应 17–28（12–27）、响应到 `readerOpened` 事件 **257–375（task 18–32，占用 7%–9%）**、事件到就绪 **46–69（task 45–69，占用 ~100%）**。
- 卡顿段构成（baseline 三次）：主线程任务 80–136（中位 91）、Layout **31–45（中位 43）**、`FunctionCall` 55–92（中位 67）、样式 4–8、Paint 2–4。窗口里 4 次 Layout，只有 `dirty=337/394` 那次慢（41.38/29.02/40.28ms），其余 0.14–1.35ms；`FunctionCall` 最大项是 React 调度器 flush（`index-Q-TfAU_F.js:25:1371`，5 次共 52.9ms）。
- 七臂（每臂 3 次，`prewarmText` 6 次，产品零改动）：`fewChapters` 1000→30 章 Layout 31（30–38）、`fewBlocks` 40→3 块 34（31–35）、`noPaint` 30（29–32）——都不低于 baseline 43（31–45）；`warm` 同书第二次 Layout **3**（2.64–3.04）、`warmOther` 异书 **5**（3.99–5.78），卡顿段 56→10–14；`prewarmText` 用隐藏宿主按阅读字体排 40 段中文（21px/17px 各 3 次）`LayoutDuration` 仍 0.030–0.031s，**文字预热无效**。
- 结论：128ms = 4–7 输入分发 + 12–27 请求与 `OPENING` 渲染 + 18–32 等待期零散 + **45–69 数据到位后连续渲染**（内含一次 27–45ms 首次布局）。这约 30ms 是会话内一次性、可复用，与章节数无关、与段落量弱相关（约 10ms）、与绘制无关。打开墙钟的 55%–70% 是后端 `open_book`，主线程只占 7%–9%。
- 局限：软件合成口径、tracing 抬高绝对值；`open`/`FunctionCall` 批间抖动 ±20%–40%（`Layout` 冷/暖差异远大于抖动，判断以此为准）；fixture 的 300 本书共用同一份正文，暖臂无法完全分开"同一份文本"与"同一层结构"。第 8 节改为：阅读页结构空闲预热（需授权）/ 后端开书定位 / 200–511 本宿主实测 / 启动耗时拆解。

### 2026-11-16 `open-reader` 采样加长：133ms 是单次过渡帧，正文表面不卡

- 改动只在测试工具：`desktop-lab/benchmark.mjs` 在 `open-reader` 之后、`reader-scroll` 之前插入 `await measure('open-reader-settle',async()=>{await sleep(1500);return{windowMs:1500}})`。`open-reader` 原样保留（同选择器、同就绪条件、同 p95 口径），历史五批仍可比。`sha256` `18aea73d…`→`1517ef4a…`；产品源码与 `prototype/dist` 零改动。
- 首批 `qt-default-performance-native-hidden-20261116-185312-3ad61d69`：`passed`、12 用例、10 检查、异常 0、可见性违规 0、退出码 0、40s。`open-reader` 11 帧 p95 133.3（未变）；`open-reader-settle` 91 帧 p95 **16.7**、最长 **16.8**、>50ms 帧 **0**、Task 32.2ms/1500ms（2.1%）、Layout 0。
- 结论：133ms 是打开那一次的一帧（Task 128.3ms 与之对应），正文打开后不卡。打开耗时 `pointerdown→ready→next rAF` 335.6/331.5→275.5/258.0ms，与卡片数减少一致。
- 同批其余 11 用例 p95 与 18:46 完全一致，多插 1.5 秒静止未改变后续用例口径；Task 在批次间 ±10%～15% 抖动、p95 不变（用户活动）。
- 第 8 节改为：200–511 本宿主实测（下一步）、打开正文 128ms 拆解、启动耗时拆解。

### 2026-11-16 宿主批次验证：阈值 200 成立，三个滚动用例 Task 降四成五，不回滚

- 批次 `qt-default-performance-native-hidden-20261116-184645-c0c4fcfd`：`passed=true`、11 用例、10 检查、`errors=[]`、`visibleViolations=0`、退出码 0、34 秒；参数与 17:20/17:21 一致（`--candidate qt-default --render-path native-hidden --phase performance --exempt-system-input-windows`），产物 `index-Q-TfAU_F.js`。
- `library-down` Task 590.9/594.8→**315.4ms**、Layout 49.1→28.3、Style 0.8→8.0、p95 33.3 不变、最长帧 66.7 不变；`library-up` 308.0/299.4→**159.1ms**、Layout 51.0→14.0、最长帧 66.7→49.9、超 50ms 帧 1→0；`library-reverse` 407.7→**218.4ms**、p95 16.8 不变。
- 其余 8 用例 p95 全部与基线相同；溢出收益：`book-hover` 624.8→353.2、`book-menu-open-close` 184.5→126.3、`open-reader` 156.3→126.7。
- 预登记点名的失败形态（Task 降但 p95 恶化）没有出现，软件合成下跨批封面栅格没有变成可见卡顿帧，**阈值保留 200**。
- 第 8 节改为：`open-reader` 采样加长（下一步）、200–511 区间宿主实测、启动耗时拆解。

### 2026-11-16 阈值 512→200 落地：书库滚动主线程降一半（宿主验证见上一条）

- 用户 18:33 授权按推荐执行。`prototype/src/App.jsx` 第 395 行改为 `books.length > 200`，附三行注释说明取值依据（窗口 64–96 张，200 本 = 2.5 个窗口；更小无收益）；自定义排序仍全量挂载。
- 重建：CSS 不变 `index-BUgJh7pn.css`，JS `index-C3BnI7BJ.js` → `index-Q-TfAU_F.js`（588555 B，`sha256 c68b2f1f…`）；产品测试 61+8+4 全过。
- 新产物离线复测两次：Task 218.3/216.0ms（旧 459.2/548.3）、HitTest 73.0/73.2（旧 267.9/319.8）、Layout 8.0/8.2（旧 20.2/21.5）、p95 16.9（不变）、挂载 64→96、`scrollHeight` 32854 不变。
- 虚拟窗口下筛选回归六步（`probe-filter.mjs`）：300 项/96 挂载 → 100 项/68 → 1 项/1 → 0 项/0 → 清空 300 项/64 → 深滚 20000/96，`scrollHeight` 依次 32854/11272/912/684/32854/32854，页面异常 0。
- 未验：宿主批次（软件合成下跨批封面栅格）、200–511 本区间实测、真实 GPU 桌面。

### 2026-11-16 虚拟窗口阈值离线实验：300 本走虚拟路径，Task 降四到五成，但未落地

- 用户说"继续"后推进第 8 节第 1 条。做法不改产品：`dist-current` 用当前源码重建（与发布物 `index-BUgJh7pn.css`+`index-C3BnI7BJ.js` 同名同字节），`dist-variant-120` 只把 `books.length > 512` 改成 `> 120`，两者并列测量；构建完源码立即还原，`sha256` 与实验前一致，`prototype/dist` 未触碰（mtime 17:23）。
- 32×wheel/5580px 两次：Task 459.2/548.3→285.5/238.6ms、HitTest 267.9/319.8→98.7/82.6ms、Layout 20.2/21.5→10.0/8.4ms、p95 16.8–16.9ms（不变）、挂载 300 常驻→64→96。
- 72×wheel/12960px：1549.0→549.0ms（-65%）；跨批 3 次（+32/-32、+32/-32、+32），合计新增 96/移除 64 节点，帧最长 17.3ms，无 long task，`scrollHeight` 32854 不变。打开书库 Task 205–245 vs 169–209ms，只能算没变慢。
- 判断：离线判据"Task 与 p95 同时不劣"成立，但**没有改阈值**——宿主软件合成下跨批新挂载封面的栅格成本在离线口径里不存在。第 8 节改为"宿主批次 → 阈值取值 → open-reader 采样 → 启动拆解"。
- 记录限制：长手势两臂的 trace 在读取时渲染进程断开（`CDP_DISCONNECTED`），其 Task 取自 `Performance.getMetrics`；只测 300 本；窗口在 8 行边界前不前进，挂载数 64→96 而非恒定。

### 2026-11-16 书库滚动剩余成本归因：命中测试是主项，`content-visibility` 与"封面/装饰"均否证

- 用户 17:45 选「甲」。在同一真实 300 本夹具、同一 `library-down` 手势（32×wheel deltaY180、45ms 间隔、5580px）下跑七个对照臂，每臂只摘一类成本：基线 451/480ms、指针在卡片上 340、去封面 490、去装饰 503、`content-visibility` 614、不绘制 183、只剩 40 张卡 125（均为主线程任务量）。
- 归因结果：66–67 次 `HitTest` 合计 260–281ms（占主线程 58%，4.2ms/次），指针落到卡片上即 155ms；Layout 21ms、Style 0.4ms、Paint 31ms、解码 0ms。自算嵌套 self time 合计 450.2ms，与 `TaskDuration` 452ms 差 0.4%。
- 三条否证：封面与装饰无收益；`content-visibility:auto` 使 Layout 21→160ms、LayoutCount 1→23、Task +28%；"每帧挂载卡片"不成立（300 卡常驻，DOM 仅 12 条 settle 后类切换）。
- 产品零改动，纯离线；第 8 节改为"虚拟窗口阈值实验（需授权）/ open-reader 采样 / 启动拆解"，并登记三条不要再试的方向。

### 2026-11-16 反向验证并移除 `data-scrolling` 滚动悬停门控

- 用户 17:10 选「甲」。离线在真实 300 本夹具上逐条减规则，直接测"写属性 + 强制 style/layout"的耗时与失效元素数：0 条 0.1ms、1 条 6.65ms（1500 元素）、3 条 6.5ms、6 条 11.4ms（2100 元素）；改用自定义属性方案反而 38.5ms、4923 元素。翻转本身 **零 Layout 事件**，此前"滚动起点 Layout 51–64ms 来自该开关"的判断被否证。
- 真实宿主两批（17:20、17:21，无门控构建 `index-BUgJh7pn.css`）一致：`library-down` Style 68.2→0.6/0.8ms、Task 767.9→590.9/594.8ms；`library-up` Style 72.0→0.5ms、Task 479.8→308.0/299.4ms；`library-reverse` Style 65.6→0.0ms、Task 583.0→407.7ms；其余 8 个用例（含 `book-hover` Style 55.7→56.2，说明悬停样式仍在工作）不变。p95 不变，因软件合成的整屏光栅才是瓶颈。
- 改动：`styles.css` 移除 6 条规则的祖先条件、保留 `:hover` 本身并加注释说明原因；`App.jsx` 保留 `data-scrolling` 发布逻辑（不再驱动样式，仅作 desktop-lab 检查的滚动状态信号），仅更新注释。
- 行为变化需用户确认：滚动中指针下的书卡不再被冻结装饰。离线复核发现合成 wheel 事件后 Chromium 不重算 hover（`duringScroll` 两条均 `hovering=false`），因此该夹具本身看不到抖动代价。
- 两批审计均判 `foreground-attribution-failed`（K1 采样 8 次含空读、K2 仅 4 次含 1 次空读且前台进程中途从 2544 变 17744），页面侧完整、可见性违规 0、退出码 0。第 8 节改为"滚动用例剩余主线程成本 / open-reader 采样 / 启动拆解"。

### 2026-11-16 设置面板首次打开优化：定位为首用文本塑形并改为空闲预热

- 用户 16:38 选「甲」。先离线定位：否证「打开设置触发全页重排」——只有 104/9587 个节点被标记脏，弹层自身 78 个节点；真实成本是会话内首用文本塑形（首次 Layout 35.83ms，同会话第二次 1.04ms；首次切「常规」9.47→0.71ms）。
- 改动：`App.jsx` 在书库就绪后延迟 300ms，用 `requestIdleCallback` 把「朗读与悬浮」「常规」两页渲染一次到隐藏宿主，两帧后移除（音色/离线/备份页挂载即拉数据，排除）；`styles.css` 新增 `.settings-warmup-host`（`visibility:hidden` + `contain:layout style paint` + `pointer-events:none`）。
- 离线复测：首次打开 Layout 1.4–2.6ms、首次切「常规」0.95–2.20ms、首次打开到下一帧 62→17–22ms；宿主卫生确认预热发生在卡片就绪（244ms）与首屏（140ms）之后，796ms 挂载、812ms 移除，无焦点抢占、无异常、无 longtask；产品测试 61+8+4 全过。
- 真实宿主三批：17:04 页面完整但审计判退出阶段窗口销毁竞态（驱动结束后 0.65s）+ 前台空读数；17:06 审计通过但被机器争用整体拖慢 1.5–2 倍（含无关用例）；17:07 审计通过、无争用，全用例在基线值域内。三批均原样保留，未为凑数据重跑。
- 说明：本改动是把一次性成本从点击路径移到空闲期（约 +45ms 空闲布局），不是消除；基准脚本计时前已预开一次设置，故宿主 p95 看不到收益。第 8 节改为 data-scrolling 反向验证 / open-reader 采样 / 启动耗时三项。

### 2026-11-16 滚动路径优化尝试否证并回退

- 用户 16:29 选「甲」后，按"每卡 blur 与 will-change 是滚动瓶颈"的假设改 2 条 CSS（仅 `data-scrolling` 期间生效）。
- 干净批次（16:34，审计通过、退出码 0）否证该假设：无任何用例改善，`library-up` Layout 51–64ms→172ms、Style 61–85ms→221ms、p95 16.8→33.3ms；`library-reverse` Layout 0→55ms。原因是新增 `[data-scrolling="true"]` 规则扩大 subtree-wide 失效，成本对规则数量超线性。
- 两条规则已删除，重建后产物与 11-12 版本逐字节等价（同名同字节数），产品代码无残留改动。第 6 节登记本次废弃方案，第 8 节改为 settings / open-reader 采样 / 启动耗时三项。

### 2026-11-16 补测两批：得到五批分布并查明前台采样密度依赖外部事件

- 用户 16:08 回复「继续」，补跑 2 次安静批次。16:08 批前台 1/4 空读数（t+33.05s）判失败、未重试；16:09 批干净通过（审计零失败、违规 0、退出码 0、Job 归零、无残留）。
- 新查明：前台采样只在 start/end 与"前台发生变化"的 poll 追加，五批采样数 17/13/12/4/2、poll 数 15/11/10/2/0；故"通过/失败"很大程度反映桌面前台活动量而非被测程序行为，16:09 的通过仅有 2 个端点采样、覆盖最弱。判据与豁免口径均未改动，该局限已登记。
- 五批 p50 一律 16.7–16.8ms（软件合成 60fps 顶格），p95 中位数：settings 66.6、open-reader 133.4、book-hover 100.0、menu 49.9、library-down 33.4；`open-reader` 每批仅 14–21 帧、p95 不可靠。第 8 节改为"按热点推进优化（open-reader 需先加长采样）"与"启动耗时离线拆解"两项。

### 2026-11-16 安静桌面重跑：performance 相位干净通过，旧结论撤回

- 用户指出 15:54 重跑期间实际动过鼠标，该批不满足"不动键鼠"前提，据此得出的"严格前台判据不可满足"结论撤回（时间线也支持：两次不合格集中在批次前 9 秒，伴随 130 毫秒内三次前台切换）。
- 16:03 真正安静桌面重跑一次：`qtHiddenAudit.passed=true`、违规 0、前台 12/12 采样有效且全属 Job 外、退出码 0、Job 归零、无残留，页面 11 用例 10 检查全过，豁免 1377 窗。判据与豁免口径均未改动。批间波动明显，第 8 节改为"补测取中位数 + 离线拆启动耗时"。

### 2026-11-16 performance 重跑：空读数 7→2（该批前提不成立，结论已撤回）

- 用户 15:54 选择 A（判据不改、只换时机）。重跑一次 performance：页面侧完整（`passed=true`、11 用例、异常 0），清理干净；前台 13 次采样 2 次不合格（首批 7/17），所有带 PID 读数均属 Job 外进程。
- 事后确认该批期间用户实际操作鼠标，故不能作为安静桌面证据；当轮据此写的"判据不可满足"结论已由 16:03 批次推翻并撤回，判据保持不变。

### 2026-11-16 performance 诊断批次：页面侧通过、前台判据失败

- 用户 15:50 选择甲。带同一豁免开关执行一次 performance 相位：`report.json` `passed=true`、11 用例、10 检查、页面异常 0，豁免 1306 窗、违规 0、退出码 0、Job 归零、无残留。
- 审计失败项 `foreground-attribution-failed`：17 次前台采样 7 次 NULL，非连续、约 60–150ms 恢复，与 11-06 Tauri B1 同类，根因仍未定位。数据为软件合成口径且 `validForComparison=false`，登记为诊断参考。第 8 节改为前台空值三选一。

### 2026-11-16 窄范围豁免后隐藏冒烟首次通过

- 用户 15:44 确认选 A（窄范围豁免后复跑）。`run.py` 新增 opt-in 开关 `--exempt-system-input-windows`：类名精确命中三类之一且注册模块 basename 匹配才豁免，其余情形（含查询失败、身份变化、模块不符）仍判违规并停批；豁免逐条记入 owner、停批记录与所有权记录。默认不带开关时行为与原严格判据完全一致。
- 15:47 批次结果：`qtHiddenAudit.passed=true`、违规 0、豁免 114 窗、退出码 0、Job 归零、无残留；页面 `page-ready-confirmed`（300 卡、`nativeChannel`、QtWebEngine 6.8.3），首次到达页面就绪。仍为软件合成，且该口径按既有规则被排除在性能对比之外。离线用例增至 22 项（新增 6 项豁免断言），既有回归 22 + 7 项通过。

### 2026-11-16 首次真实隐藏启动诊断定位首故障

- 用户 15:40 授权直接执行一次。批次按预登记启动，使用新阶段日志与模块采集，取得首个可见窗的阶段（`qapplication-created` 后 0.416 秒、主窗构造前 1.298 秒）与注册模块（`C:\Windows\System32\InputSwitch.dll`）。判据未改，批次按原口径停批并完整保留。下一步改为由用户决定严格判据与窄范围豁免二选一。

### 2026-11-16 完成启动诊断离线准备与归档回放

- 按 11 月 12 日后的第 8 节要求，补齐 `qt_host.py` 双时钟阶段边界、`run.py` 停批阶段定位与首个可见窗注册模块采集。离线验证 45 项断言用例（新增 16 项 + 既有回归 29 项）全部通过，回放归档停批确认事件顺序、归属链与 GLES 时序，0 次真实宿主启动。

### 2026-11-16 补齐旧任务恢复入口

- 按最近一轮已归档的 Qt 冒烟、Quick 宿主与离线证据补录当前状态和恢复位置。文档补录沿用原阶段结论及验收口径。
