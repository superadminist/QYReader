# QYReader 后续优化执行记录

日期：2026-10-22（Asia/Shanghai）。工作目录：`D:\phpstudy_pro\WWW\DDNovelReader`。基线 HEAD：`431a393`，版本保持 2.2.0。

## 交付状态与边界

六个阶段的代码、Qt/demo Bridge、类型及后台验证均已实现，生产前端已重建。**真实桌面/托盘/扬声器、联网 Edge 与实际 Kokoro 性能验收尚未进行**，不将模拟测试称作真实音频或安装包验收。开发阶段未改版本、打标签、推送、打包或发布；用户随后授权本地 Git 提交，本次仅提交优化代码、测试与执行记录。

保留唯一 `SpeechController → PlaybackService → DesktopBridge`；缓存服务只生成音频，不创建播放控制器。使用隔离 `DOUBAO_NOVEL_DATA`、模拟音频与 QCore 测试。未启动桌面阅读器、Computer Use、系统鼠标键盘操作或声音播放；无界面浏览器通过 Playwright headless Chrome 加 `--mute-audio` 验证，不显示窗口。Qt 环境变量仅在测试进程中设为 offscreen，未改机器持久配置。

既有 `build.bat`、`prototype/tests/stage3-qt-cdp.mjs`、`sample/星火.docx`、`sample/星火.epub` 及原交接内容未改动；计划文档仅追加执行入口。未 reset/clean/restore、整目录覆盖或批量暂存。

## 第 1 阶段：睡眠定时

- 完成 15/30/60、自定义 1–720 整数分钟、读完本章及取消入口，主窗/悬浮窗使用宿主同一快照显示；自定义输入使用小弹窗、键盘限制与焦点恢复。
- 定时服务可注入时钟，期限在暂停及系统休眠后继续生效，不持久化活动定时。手动停止/退出取消，切书取消章末计划，同章导航保留。
- 章末门槛位于底层 `_run_session()` 跨章之前，独立 `sleep_stopped` 事件不会误用整书 finished。事件带计划版本及 speech generation，旧计划不能覆盖新倒计时。到期先恢复试听上下文，再停止并走原进度 flush 链。
- 修复 Edge 缓冲结束后在 paused 状态误首播的问题；MCI 首播/恢复及 SAPI 发声前均检查停止条件。
- 文件：`novelreader/sleep_timer.py`、`playback_service.py`、`tts_engine.py`、`qt_bridge.py`、`prototype/src/SleepTimerControl.jsx`、`App.jsx`、`bridge.js`、`bridge.d.ts`、`styles.css`。
- 验证：`test_sleep_timer.py` 3 项、`test_sleep_timer_review.py` 8 项；覆盖注入时钟、暂停、覆盖/取消、恢复后过期、三引擎边界、空章/末章/Markdown、试听冲突、旧代次、Qt 最新进度落盘。浏览器验证自定义上下界、Escape/Enter 和返回焦点。
- 未验：真实 Qt 两窗/托盘和系统休眠后扬声器边界。代码与后台验证完成后推进第 2 阶段。

## 第 2 阶段：Edge 章节预生成与缓存管理

- 新增后台 `OfflineCacheService` 与统一管理面板；当前章、后续若干章、自选范围、显式整本选择，创建立即返回 jobId，后台准备/扫描。
- 支持进度/占用、暂停继续、取消保留音频、仅校验、缺片补齐、确认清理；通过原 `_synth_audio_governed(...purpose=cache)` 使用既有优先级与退避，无第二合成通道或自动关机入口。
- `offline-jobs-v1.json` 保存内容/切句/引擎/音色/语速/模型指纹及相对文件路径。旧目录可读取，缺少校验证明的音频不被管理器宣称完整。新音频使用文本及音频 SHA256 旁车，播放按当前文本校验；内容冲突时旧任务失效。
- 移除旧 `start_book_cache()` 给当前 `_book_id` 赋值的副作用。清理校验任务路径/选定范围，保护播放书籍、共享文件，删除前再次检查占用。
- 文件：`novelreader/offline_cache_service.py`、`tts_engine.py`、`prototype/src/OfflineCachePanel.jsx`，以及共享 Qt/App/Bridge/类型/样式。
- 验证：`test_offline_cache_service.py` 与 Qt 集成中的 B 书缓存/A 书播放隔离；覆盖幂等、内容变化、暂停取消/重启、缺片、失败/空间不足、原路径命中、治理器调用与清理保护。既有 Edge 调度/退避测试通过。浏览器验证自选 1–2 章请求与排队显示。
- 未验：真实 Edge 联网生成与断网后 Windows 播放；未发整书网络请求。后台完成后推进第 3 阶段。

## 第 3 阶段：Kokoro 章节预生成与持久保留

- 接入相同任务/界面，通过 `KokoroService.request(priority=30)` 逐句低优先级生成；固定模型包散列/模型版本/音色/语速，模型不兼容时暂停。
- `offline-audio-refs-v1.json` 按任务/章节保存引用，共享文本只生成一份。保留及任务依赖文件不参与 500 MiB 临时淘汰，显式清理只释放对应引用；磁盘不足保留已完成内容。
- 自定义音频目录与 Windows 扩展路径一致。已准备 WAV 无需加载模型也可回放/验证；下一句缺模型的预取失败不阻止当前已缓存句播放，正式缺片仍给出模型未就绪错误。
- 所有关闭后写入均受服务锁与任务代次约束；宿主保留尚未退出的旧任务句柄，Kokoro Future/preload 未结束时阻止恢复替换。
- 文件：`novelreader/kokoro_service.py`、`offline_cache_service.py`、`tts_engine.py`、统一面板与共享契约。
- 验证：离线服务合计 17 项，既有 Kokoro 服务 12 项及 Kokoro 播放 7 项；覆盖共享引用、临时淘汰、模型切换、空间不足、取消/重启、缺模型缓存命中、清理期间开播以及关闭后迟到回调。
- 未验：实际模型冷生成、首句等待、总耗时/音频时长、RTF、句间等待、峰值内存、真实后台负载下响应及扬声器。没有采用历史 v2.1.9 的 RTF 作为本轮数据。后台完成后推进第 4 阶段。

## 第 4 阶段：统一音色中心

- 设置页保留三引擎分组，增加中文名称/ID/引擎搜索、收藏、状态及不可用原因；收藏存 `library.json.settings.voice_favorites`，消失的系统音色仍保留。
- Edge、系统、Kokoro 试听均校验实际音色表，使用相同中文文案和唯一 PlaybackService。支持快速替换、取消、错误反馈；结束/异常/定时到期恢复原书/章节/位置/音色，原来在播的书保持暂停，试听不保存所选音色或累计听书时间。
- Edge 标注需联网，以实际试听错误/回退说明连接问题；没有为状态标签增加主动联网探测。浏览器 demo 明示本地试听边界，不伪造音频成功。
- 文件：`novelreader/voice_preferences.py`、`playback_service.py`、`qt_bridge.py`、`prototype/src/VoiceCenter.jsx`、`ReaderFeatures.jsx`、App/Bridge/类型/样式。
- 验证：Qt 集成覆盖三引擎目录校验、跨重建收藏、缺失系统音色、缺模型拒绝、快速切换/取消、异步错误与原进度/音色恢复。浏览器验证中文搜索、收藏与不可用状态。
- 未验：三类真实音色的扬声器效果、无爆音及实时网络故障场景。后台完成后推进第 5 阶段。

## 第 5 阶段：一键备份与恢复

- 新增后台盘点、生成、校验预览、恢复、取消任务与设置页面。默认书架/正文/源副本/进度/笔记/分类/收藏/统计，音频与模型可选，先估算大小，缺失内容单独报告。
- 版本化 ZIP 清单逐文件记录大小及 SHA256；SQLite 使用一致性 backup API。恢复拒绝绝对路径/穿越/特殊文件/链接/重复或未登记文件、超限与散列错误；先在暂存区校验。
- 保留 ID/笔记锚点/未知字段，重新定位正文、源文件、音频与模型路径；即使不包含模型文件也保留模型版本选择，以供音频缓存命中；不修改原外部源文件。恢复前保存可再次导入的 `before-restore.zip` 及原文件回滚目录，替换失败/取消会回滚。
- 恢复期间停止播放与 writer/activity/cache/model 写入并阻止全部数据修改入口（含原生几何保存）。成功或失败均重建服务，前端清理失效阅读会话，仍复用原控制器。退出请求先取消并等待回滚，维护时不刷新旧会话进度。
- 文件：`novelreader/backup_service.py`、`qt_bridge.py`、`qt_host.py`、`playback_service.py`、`prototype/src/BackupPanel.jsx`、App/Bridge/类型。
- 验证：`test_backup_service.py` 10 项：跨目录恢复后 ReaderService 真正读取正文、笔记/分类/收藏/稳定 ID/未知字段、WAL 一致性、恶意或损坏包、空间不足/取消/中途替换回滚，以及标准恢复前快照可重导入。Qt 集成验证全动作、维护阻断、失败/同步启动失败、退出等待及唯一控制器。
- 未验：真实 Qt 文件选择/用户确认交互、大模型及大书库实际耗时、操作系统强制结束进程/断电中断。禁止以真实用户书架做破坏性恢复测试。后台完成后推进第 6 阶段。

## 第 6 阶段：书架批量管理

- 内容库加入多选模式、当前筛选全选/撤选、全部清空、跨筛选已选数量；ID 保存在父组件，不随虚拟卡片卸载丢失。多选期间暂停拖动，卡片/键盘操作用于选中。
- 支持分类设置/清除、标签并集/差集、人工已读/阅读中/未读及显式恢复自动判断；执行前显示确认数量，不连带删除书籍或源文件。
- `OrganizationService` 在同一 `library_write_lock` 内先校验全部 ID/patch，再从最新数据一次原子保存。非法/已删/重复 ID、未知分类标签、空操作整批不写，保留进度/笔记与未知元数据。
- 文件：`novelreader/feature_store.py`、`prototype/src/BatchLibraryControls.jsx`、App/Bridge/类型/样式。
- 验证：`test_library_batch.py` 6 项，包括保存失败不覆盖和并发进度写入；demo 事务/标签语义测试通过。浏览器从全选当前 4 本到确认修改，界面显示成功和仍保留的选择。
- 未验：真实 Qt 鼠标键盘、超大书架虚拟滚动中的交互性能。

## 最终后台验证

所有命令从仓库或 `prototype/` 执行，测试数据目录随机放在系统 Temp。

```powershell
$env:DOUBAO_NOVEL_DATA = Join-Path $env:TEMP ('qyreader-tests-' + [guid]::NewGuid().ToString('N'))
$env:QT_QPA_PLATFORM = 'offscreen'
.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_*.py'
# prototype/，使用本机 Node 24.18.0（默认 PATH 的旧 Node 不支持测试语法）
$env:Path = 'D:\Program Files\nodejs;' + $env:Path
node --test tests/*.test.mjs
npm run build
npm run test:sites
git diff --check
```

- Python：310 项通过（其中音频全为模拟；QCore 不创建前台窗口）。
- 前端全部 `*.test.mjs`：72 项通过，包含 Bridge/新增功能/排序/Sites/旧阶段兼容契约。
- Bridge 类型声明使用 Babel 的 TypeScript dts 模式通过语法解析；没有将其称作 tsc 语义类型检查。
- Vite 与 Sites 构建布局通过；已生成 `prototype/dist/client`、`dist/server/index.js`、`dist/.openai/hosting.json`。
- `git diff --check` 通过，只有仓库既有 LF/CRLF 提示。
- Browser 技能未列出（Browser plugin not available）；依据前端验证技能使用本地 Playwright headless，未安装新依赖。主窗 1240×820（白天/护眼/夜间）和 800×680，悬浮窗 448×295；验证非空页面、正确标题/URL、无框架覆盖层及页面错误、按钮可点击、表单上下界与键盘焦点、离线任务请求、定时显示及正文与控制栏无重叠。
- 普通 demo 设置/书架页 1360×960：批量确认、音色搜索、离线入口、备份本地功能提示通过；有一次 favicon 404，不是应用脚本错误。正式内存夹具的错误及缺失资源列表为空。
- 最终生产构建在 `http://127.0.0.1:4174/` 使用 headless Chrome 再次冒烟：标题启远阅读、4 张卡片、音色收藏/搜索、跨筛选批量修改、离线与备份入口通过，脚本错误、缺失资源和框架覆盖层均为 0。
- 已通过各自执行会话关闭本轮 Vite 开发/预览服务，确认 5174、4174 端口不再响应；headless 浏览器已退出。
- 临时浏览器夹具/截图保存在本聊天 visualization 目录，未进入仓库；不会写入用户日常数据。截图名：`sleep-main-day/eye/night/small.png`、`sleep-floating.png`、`offline-task.png`、`voice-center.png`、`batch-library.png`。

## 下一步

本轮可独立完成的实现与后台验证已处理。余下为用户另行安排的真实桌面/托盘、短倒计时及章末扬声器、Edge 真实缓存离线回放、Kokoro 实际生成性能、真实文件选择与大型备份/虚拟列表验收。本轮本地 Git 提交已获用户授权；版本号调整、推送、Windows 打包及发布继续等待独立交付指令；现有 v2.2.0 构建产物不重做。
