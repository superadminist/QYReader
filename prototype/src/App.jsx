import { memo, useCallback, useEffect, useReducer, useRef, useState } from "react";
import {
  ArrowLeft,
  Article,
  BookOpen,
  Books,
  CaretLeft,
  CaretRight,
  CornersOut,
  Crosshair,
  DotsThreeVertical,
  FileArrowUp,
  GearSix,
  Headphones,
  LinkSimple,
  List,
  MagnifyingGlass,
  Minus,
  Moon,
  Pause,
  Play,
  Plus,
  PushPin,
  Resize,
  SidebarSimple,
  SpeakerHigh,
  TextAa,
  Trash,
  UploadSimple,
  WifiHigh,
  X,
} from "@phosphor-icons/react";
import { connectBridge } from "./bridge.js";
import { floatingLyricTransition, floatingSentenceIdentity } from "./floatingLyrics.js";
import {
  floatingFontWheelChange,
  floatingPickerColor,
  floatingTextColorPatch,
  mergeFloatingState,
  settingsPatchIds,
} from "./floatingSettings.js";
import { windowControlPresentation } from "./windowControls.js";
import { shouldApplyAudioWindow, windowContainsSentence } from "./readerWindowSync.js";
import { readerPositionFromPointer } from "./readerPosition.js";

const EMPTY_CONTROLS = {
  minimizeWindow() {},
  toggleMaximizeWindow() {},
  toggleFullscreen() {},
  closeWindow() {},
  startWindowMove() {},
  startWindowResize() {},
};

const DEFAULT_APP_PREFERENCES = {
  theme: "护眼",
  colorScheme: "light",
  autoOpenLast: true,
  closeToTray: false,
  autoCheckUpdates: true,
  startupBookId: "",
};

const DEFAULT_SOFTWARE_UPDATE = {
  status: "idle",
  currentVersion: "2.1.1",
  latestVersion: "",
  lastCheckedAt: "",
  message: "尚未检查更新。",
  releaseUrl: "https://github.com/superadminist/QYReader/releases",
  publishedAt: "",
  releaseNotes: "",
  progressPercent: 0,
  downloadedBytes: 0,
  totalBytes: 0,
  canDownload: false,
  canInstall: false,
};

const DEFAULT_SPEECH_STATE = {
  settings: { ttsVoiceId: "", ttsRate: 200, sentenceGapSeconds: 0.1 },
  voices: [{ id: "", label: "系统默认音色", backend: "sapi", requiresNetwork: false }],
  loadingLocalVoices: false,
  localVoiceError: "",
};

const EMPTY_CAPABILITIES = {
  fileImport: false,
  pasteImport: false,
  webImport: false,
  audioImport: false,
  reader: false,
  tts: false,
  floatingReader: false,
};

const EMPTY_IMPORT_STATE = {
  status: "idle",
  jobId: "",
  completed: 0,
  total: 0,
  succeeded: 0,
  failed: 0,
  message: "",
  tone: "info",
};

const EMPTY_READER_STATE = {
  phase: "idle",
  requestId: "",
  requestedBookId: "",
  data: null,
  error: "",
  windowLoading: false,
  pendingCommand: "",
  search: { status: "idle", requestId: "", query: "", page: null, error: "" },
  bookmarks: { status: "idle", page: null, error: "" },
};

const EMPTY_FLOATING_STATE = {
  visible: false,
  sessionId: "",
  bookId: "",
  settings: { geometry: "", topmost: false, backgroundOpacity: 1, fontSize: 20, followReaderFont: true, background: "light", bilingual: false, textColor: "auto", hoverDisplayEnabled: true },
  playback: { status: "idle", position: { chapterIndex: 0, charOffset: 0, progressPercent: 0 }, sentence: null, requestedBackend: "sapi", activeBackend: null, fallbackActive: false },
  context: { chapterIndex: 0, chapterTitle: "", previous: null, current: null, next: null },
};

const NETWORK_WAIT_NOTICE = {
  kind: "waiting",
  message: "网络有点慢，正在连接语音…",
};
const NETWORK_FALLBACK_NOTICE = {
  kind: "fallback",
  message: "网络异常，正在使用系统语音；恢复后会自动切回所选音色",
};
const NETWORK_RECOVERED_NOTICE = {
  kind: "recovered",
  message: "网络已恢复，已切回所选音色",
};

function usePlaybackNetworkNotice(initialNotice = null) {
  const [notice, setNotice] = useState(initialNotice);
  const hideTimerRef = useRef(null);
  const handlePlaybackEvent = useCallback((event) => {
    if (event.reason === "buffering") {
      window.clearTimeout(hideTimerRef.current);
      setNotice(NETWORK_WAIT_NOTICE);
      return;
    }
    if (event.reason === "fallback" && event.error?.code === "EDGE_OFFLINE_FALLBACK") {
      window.clearTimeout(hideTimerRef.current);
      setNotice(NETWORK_FALLBACK_NOTICE);
      return;
    }
    if (event.reason === "recovered") {
      window.clearTimeout(hideTimerRef.current);
      setNotice(NETWORK_RECOVERED_NOTICE);
      hideTimerRef.current = window.setTimeout(() => setNotice(null), 4000);
      return;
    }
    if (event.reason === "sentenceStart") {
      setNotice((current) => current?.kind === "waiting" ? null : current);
    } else if (event.reason === "state") {
      if (event.playback?.fallbackActive) {
        setNotice((current) => current?.kind === "recovered" ? current : NETWORK_FALLBACK_NOTICE);
      } else {
        setNotice((current) => ["fallback", "waiting"].includes(current?.kind) ? null : current);
      }
    } else if (["finished", "error"].includes(event.reason)) {
      window.clearTimeout(hideTimerRef.current);
      setNotice(null);
    }
  }, []);
  useEffect(() => () => window.clearTimeout(hideTimerRef.current), []);
  return [notice, handlePlaybackEvent];
}

function NetworkStatusHint({ notice, compact = false }) {
  if (!notice) return null;
  return (
    <div
      className={`network-status-hint ${notice.kind} ${compact ? "compact" : ""}`}
      role="status"
      aria-label={notice.message}
      title={notice.message}
    >
      <span className="network-status-icon" aria-hidden="true"><WifiHigh weight="bold" /></span>
      <span className="network-status-copy">{notice.message}</span>
    </div>
  );
}

function readerReducer(state, action) {
  switch (action.type) {
    case "OPENING":
      return { ...EMPTY_READER_STATE, phase: "opening", requestedBookId: action.bookId };
    case "OPEN_ACCEPTED":
      return state.phase === "opening" ? { ...state, requestId: action.requestId } : state;
    case "OPENED":
      return { ...EMPTY_READER_STATE, phase: "ready", requestId: action.requestId, requestedBookId: action.data.book.id, data: action.data };
    case "FAILED":
      return { ...EMPTY_READER_STATE, phase: "error", requestedBookId: state.requestedBookId, error: action.error };
    case "RESET":
      return { ...EMPTY_READER_STATE };
    case "WINDOW_LOADING":
      return { ...state, windowLoading: true };
    case "WINDOW":
      return state.data ? { ...state, windowLoading: false, data: { ...state.data, window: action.window } } : state;
    case "NAVIGATED":
      return state.data ? { ...state, windowLoading: false, data: { ...state.data, position: action.data.position, window: action.data.window, playback: action.data.playback } } : state;
    case "POSITION":
      return state.data ? { ...state, data: { ...state.data, position: action.position, playback: { ...state.data.playback, position: action.position } } } : state;
    case "PLAYBACK_PENDING":
      return { ...state, pendingCommand: action.command };
    case "PLAYBACK":
      return state.data ? { ...state, pendingCommand: "", data: { ...state.data, position: action.playback.position, playback: action.playback } } : state;
    case "SETTINGS":
      return state.data ? { ...state, data: { ...state.data, settings: action.settings } } : state;
    case "SEARCH_LOADING":
      return { ...state, search: { status: "loading", requestId: action.requestId || "", query: action.query, page: null, error: "" } };
    case "SEARCH_RESULT":
      return { ...state, search: { ...state.search, status: "ready", page: action.page, error: "" } };
    case "SEARCH_ERROR":
      return { ...state, search: { ...state.search, status: "error", page: null, error: action.error } };
    case "BOOKMARKS_LOADING":
      return { ...state, bookmarks: { status: "loading", page: null, error: "" } };
    case "BOOKMARKS":
      return { ...state, bookmarks: { status: "ready", page: action.page, error: "" } };
    case "BOOKMARKS_ERROR":
      return { ...state, bookmarks: { status: "error", page: null, error: action.error } };
    default:
      return state;
  }
}

const chapters = [
  "序言：为什么要重新理解运气",
  "第一章　财富与选择",
  "第二章　时间的复利",
  "第三章　幸运的结构",
  "第四章　长期主义",
  "第五章　保持在场",
  "第六章　运气的成分",
  "第七章　创造自己的机会",
  "结语：做一个清醒的乐观者",
];

const paragraphs = [
  "每年300万美元在大多数人眼里是一笔大钱，但是在另一些人眼里却不值一提。",
  "财富并不只是一串数字，它更像一种选择权：你能决定把时间留给谁，也能决定拒绝什么。",
  "创造财富的法则，往往只是代表了财富创造的方式；真正重要的是理解自己愿意用什么交换，又不愿失去什么。",
  "如果你想赚100万美元，就不得不接受一段长期而安静的积累。可是不难想象，把人生压缩到三四年，承受较大的压力，通常会让判断变得狭窄。",
  "所以，运气不是等待。它来自持续行动、开放连接，以及在机会出现时仍然保持准备。",
];

function IconButton({ label, children, active = false, disabled = false, onClick, className = "" }) {
  return (
    <button className={`icon-button ${active ? "active" : ""} ${className}`} aria-label={label} title={label} disabled={disabled} onClick={onClick}>
      {children}
    </button>
  );
}

function Rail({ page, setPage, readerEnabled, audioEnabled, darkMode, onToggleDark, onOpenSettings }) {
  return (
    <aside className="rail">
      <div className="brand-mark"><BookOpen weight="fill" /></div>
      <nav aria-label="主导航">
        <IconButton label="内容库" active={page === "library"} onClick={() => setPage("library")}><Books weight={page === "library" ? "fill" : "regular"} /></IconButton>
        <IconButton label="阅读器" active={page === "reader"} onClick={readerEnabled ? () => setPage("reader") : undefined}><Article weight={page === "reader" ? "fill" : "regular"} /></IconButton>
        <IconButton label="音频内容" className={!audioEnabled ? "disabled" : ""}><Headphones /></IconButton>
      </nav>
      <div className="rail-bottom">
        <IconButton label={darkMode ? "切换浅色模式" : "深色模式"} active={darkMode} onClick={onToggleDark}><Moon weight={darkMode ? "fill" : "regular"} /></IconButton>
        <IconButton label="设置" onClick={onOpenSettings}><GearSix /></IconButton>
      </div>
    </aside>
  );
}

function WindowTitlebar({ controls, desktopMode, windowState }) {
  const windowPresentation = windowControlPresentation(windowState);
  const isTitlebarAction = (target) => target.closest("button, input, [data-no-window-drag]");
  const startMove = (event) => {
    if (!desktopMode || event.button !== 0 || isTitlebarAction(event.target)) return;
    controls.startWindowMove();
  };
  const toggleMaximize = (event) => {
    if (!desktopMode || isTitlebarAction(event.target)) return;
    controls.toggleMaximizeWindow();
  };
  return (
    <header className="mac-titlebar" onPointerDown={startMove} onDoubleClick={toggleMaximize}>
      <div className="app-title">启远阅读</div>
      <div className="titlebar-actions" data-no-window-drag><IconButton label="搜索"><MagnifyingGlass /></IconButton><div className="avatar">D</div></div>
      <div className="window-controls" data-no-window-drag>
        <button type="button" className="window-control" aria-label="最小化窗口" title="最小化窗口" onClick={controls.minimizeWindow}>
          <span className="window-control-icon minimize" aria-hidden="true" />
        </button>
        <button type="button" className="window-control" aria-label={windowPresentation.maximizeLabel} title={windowPresentation.maximizeLabel} onClick={controls.toggleMaximizeWindow}>
          <span className={`window-control-icon ${windowPresentation.maximizeIcon}`} aria-hidden="true" />
        </button>
        <button type="button" className="window-control close" aria-label="关闭窗口" title="关闭窗口" onClick={controls.closeWindow}>
          <span className="window-control-icon close" aria-hidden="true" />
        </button>
      </div>
    </header>
  );
}

function Library({
  books,
  error,
  loading,
  openBook,
  removeBook,
  openPaste,
  selectFiles,
  showUnavailable,
  capabilities,
  readerEnabled,
  importState,
  cancelImport,
  openAfterImportBookId,
}) {
  const [query, setQuery] = useState("");
  const [bookMenu, setBookMenu] = useState(null);
  const [bookToRemove, setBookToRemove] = useState(null);
  const [removing, setRemoving] = useState(false);
  const [removeError, setRemoveError] = useState("");
  useEffect(() => {
    if (!bookMenu) return undefined;
    const closeMenu = () => setBookMenu(null);
    const onKeyDown = (event) => { if (event.key === "Escape") closeMenu(); };
    window.addEventListener("pointerdown", closeMenu);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("pointerdown", closeMenu);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [bookMenu]);
  const showBookMenu = (event, book) => {
    event.preventDefault();
    event.stopPropagation();
    setBookMenu({ book, x: Math.min(event.clientX, window.innerWidth - 210), y: Math.min(event.clientY, window.innerHeight - 76) });
  };
  const confirmRemove = async () => {
    if (!bookToRemove || removing) return;
    setRemoving(true);
    setRemoveError("");
    const error = await removeBook(bookToRemove);
    setRemoving(false);
    if (error) setRemoveError(error);
    else setBookToRemove(null);
  };
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const visibleBooks = normalizedQuery
    ? books.filter((book) => book.title.toLocaleLowerCase().includes(normalizedQuery))
    : books;
  const importing = ["selecting", "confirming", "processing", "cancelling"].includes(importState.status);
  return (
    <section className="library-page">
      <div className="library-heading">
        <div><p className="eyebrow">我的内容</p><h1>内容库</h1><p className="subtle">让文字成为可以随时聆听的陪伴。</p></div>
        <label className="search-field"><MagnifyingGlass /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索书籍或文章" /></label>
      </div>
      <div className="import-grid">
        <button className="import-card primary" aria-disabled={!capabilities.pasteImport || importing} onClick={capabilities.pasteImport && !importing ? openPaste : undefined}><span className="import-icon"><Article weight="fill" /></span><span><strong>粘贴文本</strong><small>快速开始一段朗读</small></span><CaretRight /></button>
        <button className="import-card" aria-disabled="true" onClick={() => showUnavailable("网页正文提取将在后续版本支持，当前不会发起网页抓取或创建空内容。") }><span className="import-icon blue"><LinkSimple weight="bold" /></span><span><strong>网页链接</strong><small>后续支持 · 当前不抓取网页</small></span><CaretRight /></button>
        <button className="import-card" aria-disabled="true" onClick={() => showUnavailable("音频导入与语音转写暂未支持，现有朗读功能不会被当作音频转写使用。") }><span className="import-icon violet"><Headphones weight="fill" /></span><span><strong>播客 / 音频</strong><small>暂未支持 · 不会创建音频内容</small></span><CaretRight /></button>
        <button className="import-card" aria-disabled={!capabilities.fileImport || importing} onClick={capabilities.fileImport && !importing ? selectFiles : undefined}><span className="import-icon mint"><FileArrowUp weight="fill" /></span><span><strong>导入文件</strong><small>TXT、EPUB、DOCX、PDF</small></span><CaretRight /></button>
      </div>
      {error ? <div className="library-error" role="alert">{error}</div> : null}
      {importState.message ? <div className={`import-notice ${importState.tone || "info"}`} role="status">{importState.message}</div> : null}
      {["processing", "cancelling"].includes(importState.status) ? (
        <div className="import-progress" aria-label="导入进度">
          <div><strong>{importState.status === "cancelling" ? "正在取消导入…" : "正在导入内容…"}</strong><span>{importState.completed} / {importState.total}</span></div>
          <progress value={importState.completed} max={Math.max(1, importState.total)} />
          <button className="secondary-button" onClick={cancelImport} disabled={importState.status === "cancelling"}>取消导入</button>
        </div>
      ) : null}
      <div className="section-title"><div><h2>最近阅读</h2><span>{visibleBooks.length} 项内容</span></div><button className="quiet-button"><List /> 列表</button></div>
      <div className="book-grid">
        {visibleBooks.map((book) => (
          <div key={book.id} className={`book-card ${book.id === openAfterImportBookId ? "just-imported" : ""}`} onContextMenu={(event) => showBookMenu(event, book)}>
            <button className="book-open" aria-label={`阅读 ${book.title}`} aria-disabled={!readerEnabled} onClick={() => openBook(book)}>
              <div className="cover-wrap"><img src={book.coverUrl} alt="" /><span className="format-badge">{book.format || "TXT"}</span><span className="resume-pill"><Play weight="fill" /> 继续</span></div>
              <strong>{book.title}</strong><small>{book.currentChapterTitle || book.author || "尚未开始阅读"}</small><div className="book-progress"><span style={{ width: `${book.progressPercent}%` }} /></div><em>{book.progressPercent}%</em>
            </button>
            <button className="book-more" aria-label={`${book.title}的更多操作`} title="更多操作" onClick={(event) => showBookMenu(event, book)}><DotsThreeVertical weight="bold" /></button>
          </div>
        ))}
        {loading ? <div className="library-loading">正在读取内容库…</div> : null}
        {!loading && visibleBooks.length === 0 ? (
          <div className="library-empty">
            <strong>{books.length === 0 ? "内容库还是空的" : "没有匹配的内容"}</strong>
            <span>{books.length === 0 ? "导入文件或粘贴文本即可开始朗读" : "换个关键词，或清空搜索后查看全部内容"}</span>
            {books.length > 0 ? <button className="secondary-button" onClick={() => setQuery("")}>清空搜索</button> : null}
          </div>
        ) : null}
      </div>
      {bookMenu ? <div className="book-context-menu" role="menu" style={{ left: Math.max(8, bookMenu.x), top: Math.max(8, bookMenu.y) }} onPointerDown={(event) => event.stopPropagation()}><button role="menuitem" onClick={() => { setBookToRemove(bookMenu.book); setRemoveError(""); setBookMenu(null); }}><Trash /> 从内容库移除</button></div> : null}
      {bookToRemove ? <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && !removing && setBookToRemove(null)}><div className="paste-modal remove-book-modal" role="alertdialog" aria-modal="true" aria-labelledby="remove-book-title" aria-describedby="remove-book-detail"><div className="modal-header"><div><span className="modal-icon remove"><Trash /></span><div><h2 id="remove-book-title">移出内容库？</h2><p id="remove-book-detail">“{bookToRemove.title}”将从内容库移除，阅读进度也会移除。原文件和应用缓存会保留。</p></div></div></div>{removeError ? <p className="modal-error" role="alert">{removeError}</p> : null}<div className="remove-book-actions"><button className="secondary-button" disabled={removing} onClick={() => setBookToRemove(null)}>取消</button><button className="remove-book-confirm" disabled={removing} onClick={confirmRemove}>{removing ? "正在移除…" : "确认移除"}</button></div></div></div> : null}
    </section>
  );
}

const WINDOW_EDGES = ["top", "right", "bottom", "left", "topRight", "bottomRight", "bottomLeft", "topLeft"];

function WindowResizeHandles({ controls }) {
  return WINDOW_EDGES.map((edge) => (
    <div
      key={edge}
      className={`window-resize-handle ${edge}`}
      aria-hidden="true"
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        event.preventDefault();
        controls.startWindowResize(edge);
      }}
    />
  ));
}

function DemoReaderToolbar({ onBack, fontSize, setFontSize, floating, setFloating }) {
  return (
    <div className="reader-toolbar">
      <div className="toolbar-group"><IconButton label="返回内容库" onClick={onBack}><ArrowLeft /></IconButton><IconButton label="显示或隐藏目录"><SidebarSimple /></IconButton><span className="toolbar-title">财富自由之路</span></div>
      <div className="toolbar-group toolbar-center"><IconButton label="缩小字号" onClick={() => setFontSize(Math.max(17, fontSize - 1))}><Minus /></IconButton><span className="font-value">{fontSize}</span><IconButton label="放大字号" onClick={() => setFontSize(Math.min(28, fontSize + 1))}><Plus /></IconButton><IconButton label="阅读排版"><TextAa /></IconButton></div>
      <div className="toolbar-group"><button className={`floating-toggle ${floating ? "on" : ""}`} onClick={() => setFloating(true)}><CornersOut /> 悬浮朗读</button><IconButton label="更多设置"><GearSix /></IconButton></div>
    </div>
  );
}

function DemoPlayer({ playing, setPlaying, setFloating, networkNotice, onLocate }) {
  const [progress, setProgress] = useState(43);
  useEffect(() => {
    if (!playing) return undefined;
    const timer = window.setInterval(() => setProgress((value) => (value >= 100 ? 0 : value + 0.3)), 180);
    return () => window.clearInterval(timer);
  }, [playing]);
  return (
    <div className="player-bar">
      <div className="player-copy"><strong>第六章　运气的成分</strong>{networkNotice ? <NetworkStatusHint notice={networkNotice} /> : <small>正在朗读第 18 段</small>}</div>
      <div className="player-controls"><IconButton label="上一句"><CaretLeft weight="bold" /></IconButton><button className="play-button" aria-label={playing ? "暂停" : "播放"} onClick={() => setPlaying(!playing)}>{playing ? <Pause weight="fill" /> : <Play weight="fill" />}</button><IconButton label="下一句"><CaretRight weight="bold" /></IconButton></div>
      <div className="player-slider"><span>08:24</span><input type="range" min="0" max="100" value={progress} onChange={(event) => setProgress(Number(event.target.value))} /><span>19:42</span></div>
      <div className="player-tools"><button className="speed">1.0×</button><IconButton label="音量"><SpeakerHigh /></IconButton><IconButton label="定位当前朗读" onClick={onLocate}><Crosshair /></IconButton><IconButton label="打开悬浮朗读" onClick={() => setFloating(true)}><CornersOut /></IconButton></div>
    </div>
  );
}

function DemoReader({ setPage, fontSize, setFontSize, playing, setPlaying, floating, setFloating, networkNotice }) {
  const [chapter, setChapter] = useState(6);
  const sheetRef = useRef(null);
  return (
    <section className="reader-page">
      <DemoReaderToolbar onBack={() => setPage("library")} fontSize={fontSize} setFontSize={setFontSize} floating={floating} setFloating={setFloating} />
      <div className="reader-layout">
        <aside className="toc-panel"><div className="toc-title"><span>目录</span><small>9 章</small></div><div className="toc-list">{chapters.map((item, index) => <button key={item} className={chapter === index ? "selected" : ""} onClick={() => setChapter(index)}><span>{String(index + 1).padStart(2, "0")}</span>{item}</button>)}</div><div className="toc-footer"><UploadSimple /> 已同步阅读进度</div></aside>
        <article ref={sheetRef} className="reading-sheet" style={{ "--reading-size": `${fontSize}px` }}><p className="chapter-index">CHAPTER 06</p><h1>运气的成分</h1><div className="title-rule" /><div className="reading-copy">{paragraphs.map((paragraph, index) => <p key={paragraph} className={index === 0 ? "speaking" : ""}>{paragraph}</p>)}</div><div className="page-count">126 / 298</div></article>
      </div>
      <DemoPlayer playing={playing} setPlaying={setPlaying} setFloating={setFloating} networkNotice={networkNotice} onLocate={() => sheetRef.current?.querySelector(".reading-copy .speaking")?.scrollIntoView({ block: "center", behavior: "smooth" })} />
    </section>
  );
}

function DemoFloatingReader({ playing, setPlaying, onClose, onReturnToMain }) {
  const dragRef = useRef(null);
  const resizeRef = useRef(null);
  const initialWidth = Math.min(560, window.innerWidth - 96);
  const [position, setPosition] = useState({ x: Math.max(24, window.innerWidth - initialWidth - 120), y: 90 });
  const [size, setSize] = useState({ width: initialWidth, height: 270 });
  const startDrag = (event) => {
    if (event.target.closest("button, input")) return;
    dragRef.current = { x: event.clientX, y: event.clientY, left: position.x, top: position.y };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const drag = (event) => {
    if (!dragRef.current) return;
    setPosition({ x: Math.max(8, dragRef.current.left + event.clientX - dragRef.current.x), y: Math.max(8, dragRef.current.top + event.clientY - dragRef.current.y) });
  };
  const startResize = (event) => {
    event.stopPropagation();
    resizeRef.current = { x: event.clientX, y: event.clientY, width: size.width, height: size.height };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const resize = (event) => {
    if (!resizeRef.current) return;
    const maxWidth = Math.max(370, window.innerWidth - position.x - 10);
    const maxHeight = Math.max(238, window.innerHeight - position.y - 10);
    setSize({
      width: Math.min(maxWidth, Math.max(370, resizeRef.current.width + event.clientX - resizeRef.current.x)),
      height: Math.min(maxHeight, Math.max(238, resizeRef.current.height + event.clientY - resizeRef.current.y)),
    });
  };
  return (
    <div className="floating-reader" style={{ left: position.x, top: position.y, width: size.width, height: size.height }}>
      <div className="floating-dragbar" onPointerDown={startDrag} onPointerMove={drag} onPointerUp={() => { dragRef.current = null; }}>
        <div><span className="live-dot" /> 第六章　运气的成分</div><div className="floating-window-actions"><IconButton label="固定在最前"><PushPin /></IconButton><IconButton label="返回主面板" onClick={onReturnToMain}><CornersOut /></IconButton><IconButton label="关闭悬浮窗" onClick={onClose}><X /></IconButton></div>
      </div>
      <div className="floating-content"><p className="context-line">创造财富的法则，往往只是代表了财富创造的方式。</p><p className="current-line">每年300万美元在大多数人眼里是一笔大钱，但是在另一些人眼里却不值一提。</p><p className="next-line">300万美元算什么？</p></div>
      <div className="floating-controls"><div className="control-cluster"><IconButton label="上一句"><CaretLeft weight="fill" /></IconButton><button className="floating-play" aria-label={playing ? "暂停" : "播放"} onClick={() => setPlaying(!playing)}>{playing ? <Pause weight="fill" /> : <Play weight="fill" />}</button><IconButton label="下一句"><CaretRight weight="fill" /></IconButton></div><div className="mini-progress"><span /></div><button className="floating-resize-control" aria-label="拖动调整悬浮窗大小" title="拖动调整悬浮窗大小" onPointerDown={startResize} onPointerMove={resize} onPointerUp={() => { resizeRef.current = null; }} onPointerCancel={() => { resizeRef.current = null; }}><Resize weight="bold" /></button></div>
    </div>
  );
}

function FloatingSentence({ tone, sentence, emptyText }) {
  const identity = sentence ? `${sentence.chapterIndex}:${sentence.startOffset}` : `${tone}:empty`;
  return <p className={`floating-sentence ${tone}`} data-sentence-role={tone} data-sentence-id={identity}>{sentence?.text || emptyText}</p>;
}

function FloatingLyricLayer({ context, className = "", hidden = false }) {
  return (
    <div className={`floating-lyric-layer ${className}`} aria-hidden={hidden ? "true" : undefined} data-current-sentence-id={floatingSentenceIdentity(context.current)}>
      <FloatingSentence tone="previous" sentence={context.previous} emptyText="已经到达本章开头" />
      <FloatingSentence tone="current" sentence={context.current} emptyText="开始朗读后，这里会显示当前句" />
      <FloatingSentence tone="next" sentence={context.next} emptyText="已经到达本章结尾" />
    </div>
  );
}

function NativeFloatingReader({ state, loading, error, networkNotice, pointerInside, onPointerInsideChange, pendingCommand, pendingSetting, onCommand, onSettings, onClose, onReturnToMain, onMove, onResize }) {
  const { settings, playback, context } = state;
  const playing = playback.status === "playing";
  const canControlPlayback = Boolean(state.sessionId) && !pendingCommand;
  const settingPending = (key) => pendingSetting?.includes(key);
  const rootRef = useRef(null);
  const contentRef = useRef(null);
  const fontTimerRef = useRef(null);
  const opacityTimerRef = useRef(null);
  const lyricTimerRef = useRef(null);
  const renderedContextRef = useRef(context);
  const fontSizeRef = useRef(settings.fontSize);
  const followReaderFontRef = useRef(settings.followReaderFont);
  const opacityRef = useRef(settings.backgroundOpacity);
  const [visibleFontSize, setVisibleFontSize] = useState(settings.fontSize);
  const [visibleOpacity, setVisibleOpacity] = useState(settings.backgroundOpacity);
  const [renderedContext, setRenderedContext] = useState(context);
  const [departingLyric, setDepartingLyric] = useState(null);
  const [lyricDirection, setLyricDirection] = useState("");
  const hoverDisplayEnabled = settings.hoverDisplayEnabled !== false;
  const interactionVisible = pointerInside;
  const effectiveNetworkNotice = networkNotice || (playback.fallbackActive ? NETWORK_FALLBACK_NOTICE : null);

  useEffect(() => {
    fontSizeRef.current = settings.fontSize;
    setVisibleFontSize(settings.fontSize);
  }, [settings.fontSize]);
  useEffect(() => {
    followReaderFontRef.current = settings.followReaderFont;
  }, [settings.followReaderFont]);
  useEffect(() => {
    opacityRef.current = settings.backgroundOpacity;
    setVisibleOpacity(settings.backgroundOpacity);
  }, [settings.backgroundOpacity]);
  useEffect(() => () => {
    clearTimeout(fontTimerRef.current);
    clearTimeout(opacityTimerRef.current);
    clearTimeout(lyricTimerRef.current);
  }, []);
  useEffect(() => {
    const previous = renderedContextRef.current;
    const transition = floatingLyricTransition(previous, context);
    renderedContextRef.current = context;
    setRenderedContext(context);
    if (!transition.changed) return;
    setDepartingLyric({ context: previous, direction: transition.direction });
    setLyricDirection(transition.direction);
    clearTimeout(lyricTimerRef.current);
    lyricTimerRef.current = setTimeout(() => {
      setDepartingLyric(null);
      setLyricDirection("");
    }, 240);
  }, [context]);
  useEffect(() => {
    const root = rootRef.current;
    const content = contentRef.current;
    if (!root || !content) return undefined;
    let frame = 0;
    const fit = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        root.dataset.contextMode = "all";
        if (hoverDisplayEnabled && !pointerInside) {
          const current = content.querySelector('[data-sentence-role="current"]');
          content.scrollTop = content.scrollHeight > content.clientHeight + 1 && current
            ? Math.max(0, current.offsetTop - (content.clientHeight - current.offsetHeight) / 2)
            : 0;
          return;
        }
        if (content.scrollHeight > content.clientHeight + 1) root.dataset.contextMode = "current-next";
        if (content.scrollHeight > content.clientHeight + 1) root.dataset.contextMode = "current-only";
        content.scrollTop = 0;
      });
    };
    const observer = new ResizeObserver(fit);
    observer.observe(root);
    observer.observe(content);
    fit();
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [renderedContext.previous?.text, renderedContext.current?.text, renderedContext.next?.text, visibleFontSize, error, hoverDisplayEnabled, pointerInside]);
  const changeFontByWheel = (event) => {
    event.preventDefault();
    const change = floatingFontWheelChange(
      fontSizeRef.current,
      followReaderFontRef.current,
      event.deltaY,
    );
    if (!change) return;
    fontSizeRef.current = change.fontSize;
    setVisibleFontSize(change.fontSize);
    clearTimeout(fontTimerRef.current);
    if (change.immediate) {
      followReaderFontRef.current = false;
      onSettings(change.patch);
      return;
    }
    fontTimerRef.current = setTimeout(() => onSettings(change.patch), 250);
  };
  useEffect(() => {
    const content = contentRef.current;
    if (!content) return undefined;
    content.addEventListener("wheel", changeFontByWheel, { passive: false });
    return () => content.removeEventListener("wheel", changeFontByWheel);
  }, [onSettings]);
  const changeBackgroundOpacity = (value) => {
    const next = Math.max(0, Math.min(100, Number(value))) / 100;
    opacityRef.current = next;
    setVisibleOpacity(next);
    clearTimeout(opacityTimerRef.current);
    opacityTimerRef.current = setTimeout(() => onSettings({ backgroundOpacity: next }), 180);
  };
  const startMove = (event) => {
    if (event.button !== 0 || event.target.closest("button, input")) return;
    event.preventDefault();
    onMove();
  };

  return (
    <main
      ref={rootRef}
      className={`native-floating-surface background-${settings.background}`}
      data-testid="native-floating-reader"
      data-window-visible={state.visible ? "true" : "false"}
      data-pointer-inside={pointerInside ? "true" : "false"}
      data-hover-display-enabled={hoverDisplayEnabled ? "true" : "false"}
      data-interaction-visible={interactionVisible ? "true" : "false"}
      data-context-mode="all"
      onPointerEnter={() => onPointerInsideChange(true)}
      onPointerLeave={() => onPointerInsideChange(false)}
      style={{
        "--floating-font-size": `${visibleFontSize}px`,
        "--floating-panel-opacity": visibleOpacity,
        "--floating-custom-text": settings.textColor === "auto" ? "var(--floating-text-default)" : settings.textColor,
        backdropFilter: visibleOpacity === 0 ? "none" : undefined,
        WebkitBackdropFilter: visibleOpacity === 0 ? "none" : undefined,
      }}
    >
      <WindowResizeHandles controls={{ startWindowResize: onResize }} />
      <header className="floating-dragbar" onPointerDown={startMove}>
        <div><span className={`live-dot ${playing ? "playing" : ""}`} /><span className="floating-chapter">{context.chapterTitle || "悬浮朗读"}</span><span className="floating-status">{loading ? "正在同步" : playing ? "正在朗读" : playback.status === "paused" ? "已暂停" : "已就绪"}</span></div>
        <div className="floating-window-actions">
          <IconButton label={settings.topmost ? "取消置顶" : "置顶悬浮窗"} active={settings.topmost} onClick={settingPending("topmost") ? undefined : () => onSettings({ topmost: !settings.topmost })}><PushPin weight={settings.topmost ? "fill" : "regular"} /></IconButton>
          <IconButton label="返回主面板" onClick={onReturnToMain}><CornersOut /></IconButton>
          <IconButton label="关闭悬浮窗" onClick={onClose}><X /></IconButton>
        </div>
      </header>
      <section ref={contentRef} className="floating-content" aria-live="polite" title="滚动鼠标滚轮可调整字号">
        <FloatingLyricLayer context={renderedContext} className={lyricDirection ? `active enter-${lyricDirection}` : "active"} />
        {departingLyric ? <FloatingLyricLayer context={departingLyric.context} className={`departing exit-${departingLyric.direction}`} hidden /> : null}
      </section>
      {error ? <div className="floating-error" role="alert">{error}</div> : effectiveNetworkNotice ? <div className="floating-network-slot"><NetworkStatusHint notice={effectiveNetworkNotice} compact /></div> : null}
      <footer className="floating-controls">
        <div className="control-cluster">
          <IconButton label="上一句" onClick={canControlPlayback ? () => onCommand("previousSentence") : undefined}><CaretLeft weight="fill" /></IconButton>
          <button className="floating-play" aria-label={playing ? "暂停" : "播放"} disabled={!canControlPlayback} onClick={() => onCommand(playing ? "pause" : "play")}>{playing ? <Pause weight="fill" /> : <Play weight="fill" />}</button>
          <IconButton label="下一句" onClick={canControlPlayback ? () => onCommand("nextSentence") : undefined}><CaretRight weight="fill" /></IconButton>
        </div>
        <label className="floating-opacity-control">
          <span>背景 {Math.round(visibleOpacity * 100)}%</span>
          <input aria-label="悬浮窗背景透明度" type="range" min="0" max="100" step="5" value={Math.round(visibleOpacity * 100)} disabled={settingPending("backgroundOpacity")} onChange={(event) => changeBackgroundOpacity(event.target.value)} />
        </label>
        <button
          className="floating-resize-control"
          aria-label="拖动调整悬浮窗大小"
          title="拖动调整悬浮窗大小"
          onPointerDown={(event) => {
            if (event.button !== 0) return;
            event.preventDefault();
            onResize("bottomRight");
          }}
        ><Resize weight="bold" /></button>
      </footer>
    </main>
  );
}

function FloatingApplication() {
  const qaMode = new URLSearchParams(window.location.search).get("qa");
  const [floatingState, setFloatingState] = useState(null);
  const [error, setError] = useState("");
  const [networkNotice, handlePlaybackEvent] = usePlaybackNetworkNotice(qaMode === "network" ? NETWORK_FALLBACK_NOTICE : null);
  const [pendingCommand, setPendingCommand] = useState("");
  const [pendingSettings, setPendingSettings] = useState([]);
  const [pointerInside, setPointerInside] = useState(false);
  const connectionRef = useRef(null);

  useEffect(() => {
    document.documentElement.dataset.surface = "floating";
    return () => { delete document.documentElement.dataset.surface; };
  }, []);

  useEffect(() => {
    let active = true;
    connectBridge().then(async (connection) => {
      if (!active) {
        connection.dispose();
        return;
      }
      connectionRef.current = connection;
      connection.onBridgeError((raw) => {
        if (!active) return;
        try { setError(JSON.parse(raw).message || "悬浮朗读通信失败。"); } catch { setError("悬浮朗读通信失败。"); }
      });
      connection.onFloatingReaderChanged((event) => {
        if (!active) return;
        setFloatingState(event.state);
        setPendingCommand("");
        if (event.state.playback.status !== "error") setError("");
      });
      connection.onReaderPlaybackChanged((event) => {
        if (active) handlePlaybackEvent(event);
      });
      connection.onFloatingPointerChanged((inside) => {
        if (active) setPointerInside(inside);
      });
      try {
        const response = connection.mode === "demo" ? await connection.floating.show() : await connection.floating.getState();
        if (active) setFloatingState(response.data);
      } catch (caught) {
        if (active) setError(caught.message || "无法读取悬浮朗读状态。");
      }
    }).catch((caught) => {
      if (active) setError(caught.message || "无法连接桌面程序。");
    });
    return () => {
      active = false;
      connectionRef.current?.dispose();
      connectionRef.current = null;
    };
  }, []);

  const controlPlayback = async (command) => {
    const connection = connectionRef.current;
    const sessionId = floatingState?.sessionId;
    if (!connection || !sessionId) {
      setError("请先在主窗口打开一本内容。");
      return;
    }
    setPendingCommand(command);
    try {
      const response = await connection.reader.controlPlayback({ sessionId, command });
      if (!response.data.accepted) setPendingCommand("");
    } catch (caught) {
      setPendingCommand("");
      setError(caught.message || "播放控制失败。");
    }
  };
  const updateSettings = async (patch) => {
    const connection = connectionRef.current;
    if (!connection) return;
    const keys = Object.keys(patch);
    const previousValues = Object.fromEntries(
      keys.map((key) => [key, floatingState?.settings?.[key]]),
    );
    setPendingSettings((current) => [...new Set([...current, ...keys])]);
    setFloatingState((current) => mergeFloatingState(current, patch));
    try {
      const response = await connection.floating.updateSettings({ patch });
      setFloatingState(response.data);
    } catch (caught) {
      setFloatingState((current) => mergeFloatingState(current, previousValues));
      setError(caught.message || "悬浮朗读设置保存失败。");
    } finally {
      setPendingSettings((current) => current.filter((key) => !keys.includes(key)));
    }
  };
  const close = async () => {
    try {
      await connectionRef.current?.floating.close();
      setFloatingState((previous) => previous ? { ...previous, visible: false } : previous);
    } catch (caught) {
      setError(caught.message || "无法关闭悬浮朗读窗。");
    }
  };
  const returnToMain = async () => {
    try {
      await connectionRef.current?.floating.returnToMain();
      setFloatingState((previous) => previous ? { ...previous, visible: false } : previous);
    } catch (caught) {
      setError(caught.message || "无法返回主面板。");
    }
  };
  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
      } else if (event.code === "Space" && !(event.target instanceof HTMLElement && event.target.closest("button, input"))) {
        event.preventDefault();
        controlPlayback(floatingState?.playback.status === "playing" ? "pause" : "play");
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [floatingState]);
  const state = floatingState || EMPTY_FLOATING_STATE;
  return (
    <div className="floating-surface-stage">
      <NativeFloatingReader
        state={state}
        pointerInside={pointerInside}
        onPointerInsideChange={setPointerInside}
        loading={!floatingState}
        error={error}
        networkNotice={networkNotice}
        pendingCommand={pendingCommand}
        pendingSetting={pendingSettings}
        onCommand={controlPlayback}
        onSettings={updateSettings}
        onClose={close}
        onReturnToMain={returnToMain}
        onMove={() => connectionRef.current?.floating.startWindowMove()}
        onResize={(edge) => connectionRef.current?.floating.startWindowResize(edge)}
      />
    </div>
  );
}

function PasteModal({ onClose, onImport, demoMode }) {
  const [title, setTitle] = useState(demoMode ? "运气的成分" : "");
  const [text, setText] = useState(demoMode ? "每年300万美元在大多数人眼里是一笔大钱，但是在另一些人眼里却不值一提。" : "");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const submit = async () => {
    if (!text.trim()) {
      setSubmitError("正文不能为空，请粘贴要朗读的内容。");
      return;
    }
    setSubmitting(true);
    setSubmitError("");
    const error = await onImport({ title, text });
    if (error) {
      setSubmitError(error);
      setSubmitting(false);
    }
  };
  return (
    <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && !submitting && onClose()}><div className="paste-modal" role="dialog" aria-modal="true" aria-labelledby="paste-title"><div className="modal-header"><div><span className="modal-icon"><Article weight="fill" /></span><div><h2 id="paste-title">粘贴文本</h2><p>将一段文字快速加入内容库</p></div></div><IconButton label="关闭" onClick={submitting ? undefined : onClose}><X /></IconButton></div><label className="field-label">标题<input value={title} onChange={(event) => setTitle(event.target.value)} disabled={submitting} placeholder="可选，留空将使用正文首行" /></label><label className="field-label">正文<textarea value={text} onChange={(event) => setText(event.target.value)} disabled={submitting} placeholder="粘贴要朗读的正文" /></label><div className="modal-footer"><span>{text.length} 个字符</span>{submitError ? <span className="modal-error" role="alert">{submitError}</span> : null}<div><button className="secondary-button" onClick={onClose} disabled={submitting}>取消</button><button className="primary-button" onClick={submit} disabled={submitting}>{submitting ? "正在加入…" : "加入并阅读"}</button></div></div></div></div>
  );
}

function sliceCodePoints(text, start, end) {
  return Array.from(text).slice(start, end).join("");
}

const ReaderTextBlockView = memo(function ReaderTextBlockView({ block, highlightStart, highlightEnd, readerStart, paragraphMode, firstLineIndent }) {
  const hasHighlight = highlightStart !== null && highlightEnd !== null && highlightStart < highlightEnd;
  const className = `reader-text-block mode-${paragraphMode} ${block.startsParagraph ? "paragraph-start" : "paragraph-continuation"}`;
  const style = { textIndent: block.startsParagraph && firstLineIndent ? "2em" : 0 };
  const codePointLength = Array.from(block.text).length;
  const start = hasHighlight ? Math.max(0, Math.min(codePointLength, highlightStart - block.startOffset)) : null;
  const end = hasHighlight ? Math.max(start, Math.min(codePointLength, highlightEnd - block.startOffset)) : null;
  const localReaderStart = readerStart !== null && readerStart >= block.startOffset && readerStart <= block.endOffset
    ? Math.max(0, Math.min(codePointLength, readerStart - block.startOffset))
    : null;
  const textRange = (from, to, highlighted = false) => {
    if (from >= to && localReaderStart !== from) return null;
    const markerInside = localReaderStart !== null
      && localReaderStart >= from
      && (localReaderStart < to || (localReaderStart === codePointLength && to === codePointLength));
    const content = markerInside
      ? <>{sliceCodePoints(block.text, from, localReaderStart)}<span className="reader-start-marker" aria-hidden="true" />{sliceCodePoints(block.text, localReaderStart, to)}</>
      : sliceCodePoints(block.text, from, to);
    return highlighted ? <mark>{content}</mark> : content;
  };
  return (
    <p className={className} style={style} data-reader-block data-start-offset={block.startOffset}>
      {hasHighlight
        ? <>{textRange(0, start)}{textRange(start, end, true)}{textRange(end, codePointLength)}</>
        : textRange(0, codePointLength)}
    </p>
  );
});

const ReaderCopyView = memo(function ReaderCopyView({ blocks, sentenceStart, sentenceEnd, readerStart, chapterIndex, onChooseStart, paragraphMode, firstLineIndent }) {
  const handlePointerUp = (event) => {
    const target = readerPositionFromPointer(event.currentTarget, event, chapterIndex);
    if (target) onChooseStart(target);
  };
  return <div className="reading-copy" onPointerUp={handlePointerUp} title="单击或选中文字，可从该位置开始朗读">{blocks.map((block, index) => {
    const overlaps = sentenceStart !== null && sentenceEnd > block.startOffset && sentenceStart < block.endOffset;
    const highlightStart = overlaps ? Math.max(sentenceStart, block.startOffset) : null;
    const highlightEnd = overlaps ? Math.min(sentenceEnd, block.endOffset) : null;
    return <div id={`native-reader-block-${index}`} key={block.id}><ReaderTextBlockView block={block} highlightStart={highlightStart} highlightEnd={highlightEnd} readerStart={readerStart} paragraphMode={paragraphMode} firstLineIndent={firstLineIndent} /></div>;
  })}</div>;
});

function NativeReaderToolbar({ data, panelMode, setPanelMode, onBack, onSettings, floatingAvailable, floatingVisible, onFloatingToggle, onOpenSettings }) {
  const { settings } = data;
  return (
    <div className="reader-toolbar">
      <div className="toolbar-group"><IconButton label="返回内容库" onClick={onBack}><ArrowLeft /></IconButton><IconButton label="目录" active={panelMode === "toc"} onClick={() => setPanelMode("toc")}><SidebarSimple /></IconButton><span className="toolbar-title">{data.book.title}</span></div>
      <div className="toolbar-group toolbar-center"><IconButton label="缩小字号" onClick={() => onSettings({ fontSize: Math.max(12, settings.fontSize - 1) })}><Minus /></IconButton><span className="font-value">{settings.fontSize}</span><IconButton label="放大字号" onClick={() => onSettings({ fontSize: Math.min(40, settings.fontSize + 1) })}><Plus /></IconButton><button className="speed" onClick={() => onSettings({ paragraphMode: settings.paragraphMode % 3 + 1 })}><TextAa /> 排版 {settings.paragraphMode}</button></div>
      <div className="toolbar-group"><IconButton label="书内搜索" active={panelMode === "search"} onClick={() => setPanelMode("search")}><MagnifyingGlass /></IconButton><IconButton label="书签" active={panelMode === "bookmarks"} onClick={() => setPanelMode("bookmarks")}><PushPin /></IconButton>{floatingAvailable ? <IconButton label="切换到悬浮朗读" active={floatingVisible} onClick={onFloatingToggle}><CornersOut /></IconButton> : null}<IconButton label="更多设置" onClick={onOpenSettings}><GearSix /></IconButton></div>
    </div>
  );
}

function NativePlayer({ playback, chapterTitle, pendingCommand, selectedStart, onCommand, onNavigate, onSettings, onLocate, settings, networkNotice }) {
  const [seekPercent, setSeekPercent] = useState(playback.position.progressPercent);
  const seekingRef = useRef(false);
  useEffect(() => {
    if (!seekingRef.current) setSeekPercent(playback.position.progressPercent);
  }, [playback.position.progressPercent]);
  const playing = playback.status === "playing";
  const disabled = Boolean(pendingCommand);
  const effectiveNetworkNotice = networkNotice || (playback.fallbackActive ? NETWORK_FALLBACK_NOTICE : null);
  return (
    <div className="player-bar">
      <div className="player-copy"><strong>{chapterTitle}</strong>{effectiveNetworkNotice ? <NetworkStatusHint notice={effectiveNetworkNotice} /> : <small>{selectedStart && !playing ? "已选择朗读起点，点击播放即可从这里开始" : playback.sentence ? `正在朗读：${playback.sentence.text}` : playback.status === "paused" ? "朗读已暂停" : "阅读进度已同步"}</small>}</div>
      <div className="player-controls"><IconButton label="上一句" onClick={disabled ? undefined : () => onCommand("previousSentence")}><CaretLeft weight="bold" /></IconButton><button className="play-button" aria-label={playing ? "暂停" : "播放"} disabled={disabled} onClick={() => onCommand(playing ? "pause" : "play")}>{playing ? <Pause weight="fill" /> : <Play weight="fill" />}</button><IconButton label="下一句" onClick={disabled ? undefined : () => onCommand("nextSentence")}><CaretRight weight="bold" /></IconButton></div>
      <div className="player-slider"><span>{seekPercent.toFixed(1)}%</span><input type="range" min="0" max="100" step="0.1" value={seekPercent} onPointerDown={() => { seekingRef.current = true; }} onChange={(event) => setSeekPercent(Number(event.target.value))} onPointerUp={(event) => { seekingRef.current = false; onNavigate({ kind: "percent", percent: Number(event.currentTarget.value) }); }} /><span>100%</span></div>
      <div className="player-tools"><button className="speed" onClick={() => onSettings({ ttsRate: settings.ttsRate >= 300 ? 120 : settings.ttsRate + 20 })}>{settings.ttsRate}</button><IconButton label={`音量 ${settings.volume}`} onClick={() => onSettings({ volume: settings.volume >= 100 ? 50 : Math.min(100, settings.volume + 10) })}><SpeakerHigh /></IconButton><IconButton label="定位当前朗读" disabled={!playback.sentence} onClick={onLocate}><Crosshair /></IconButton><IconButton label="停止朗读" onClick={disabled ? undefined : () => onCommand("stop")}><X /></IconButton></div>
    </div>
  );
}

function NativeReader({ state, networkNotice, selectedStart, onChooseStart, onBack, onNavigate, onGetWindow, onUpdatePosition, onSearch, onLoadBookmarks, onAddBookmark, onRemoveBookmark, onCommand, onSettings, floatingAvailable, floatingVisible, onFloatingToggle, onOpenSettings }) {
  const [panelMode, setPanelMode] = useState("toc");
  const [query, setQuery] = useState("");
  const scrollTimerRef = useRef(null);
  const readingSheetRef = useRef(null);
  const locateRequestedRef = useRef("");
  const data = state.data;
  const playback = data?.playback;
  const windowData = data?.window;
  const sentence = playback && windowData && playback.sentence?.chapterIndex === windowData.chapterIndex ? playback.sentence : null;
  const chapterTitle = data?.book.chapters[data.position.chapterIndex]?.title || windowData?.chapterTitle || "";
  const currentSentenceTarget = () => {
    if (!sentence || !windowData) return null;
    const sheet = readingSheetRef.current;
    const mark = sheet?.querySelector(".reading-copy mark");
    if (mark) return mark;
    const index = windowData.blocks.findIndex((block) => block.startOffset <= sentence.startOffset && sentence.startOffset < block.endOffset);
    return index >= 0 ? sheet?.querySelector(`#native-reader-block-${index}`) : null;
  };

  useEffect(() => () => window.clearTimeout(scrollTimerRef.current), []);
  useEffect(() => {
    if (playback?.status !== "idle") {
      window.clearTimeout(scrollTimerRef.current);
      scrollTimerRef.current = null;
    }
  }, [playback?.status]);
  useEffect(() => {
    if (!sentence || !windowData) return;
    const requested = `${sentence.chapterIndex}:${sentence.startOffset}` === locateRequestedRef.current;
    const target = currentSentenceTarget();
    if (requested && target) locateRequestedRef.current = "";
    if (!target) return;
    const viewport = readingSheetRef.current.getBoundingClientRect();
    const mark = target.getBoundingClientRect();
    if (!requested && mark.top >= viewport.top + 16 && mark.bottom <= viewport.bottom - 16) return;
    target.scrollIntoView({ block: "center", behavior: requested ? "smooth" : "auto" });
  }, [sentence?.chapterIndex, sentence?.startOffset, windowData]);

  if (state.phase === "opening") return <section className="reader-page reader-message"><div><strong>正在打开真实内容…</strong><span>正在恢复章节与阅读进度</span></div></section>;
  if (state.phase !== "ready" || !data) return <section className="reader-page reader-message"><div><strong>无法打开阅读器</strong><span>{state.error || "请返回内容库后重试。"}</span><button className="secondary-button" onClick={onBack}>返回内容库</button></div></section>;

  const changePanel = (mode) => {
    setPanelMode(mode);
    if (mode === "bookmarks" && state.bookmarks.status === "idle") onLoadBookmarks();
  };
  const submitSearch = (event) => {
    event.preventDefault();
    if (query.trim()) onSearch(query.trim());
  };
  const navigate = (target) => {
    window.clearTimeout(scrollTimerRef.current);
    scrollTimerRef.current = null;
    locateRequestedRef.current = "";
    onNavigate(target);
  };
  const locateCurrentSentence = () => {
    const current = playback.sentence;
    if (!current) return;
    const inWindow = current.chapterIndex === windowData.chapterIndex
      && current.startOffset >= windowData.windowStartOffset
      && current.startOffset < windowData.windowEndOffset;
    const target = inWindow ? currentSentenceTarget() : null;
    if (target) {
      window.clearTimeout(scrollTimerRef.current);
      scrollTimerRef.current = null;
      target.scrollIntoView({ block: "center", behavior: "smooth" });
      return;
    }
    locateRequestedRef.current = `${current.chapterIndex}:${current.startOffset}`;
    onGetWindow(current.chapterIndex, current.startOffset);
  };
  const handleScroll = (event) => {
    // Scrolls caused by highlighting can finish after Pause.  Never let them
    // navigate the shared audio session while it is playing or paused.
    if (playback.status !== "idle") return;
    const container = event.currentTarget;
    window.clearTimeout(scrollTimerRef.current);
    scrollTimerRef.current = window.setTimeout(() => {
      if (playback.status !== "idle") return;
      const blocks = [...container.querySelectorAll("[data-reader-block]")];
      const top = container.getBoundingClientRect().top;
      const visible = blocks.find((node) => node.getBoundingClientRect().bottom >= top + 8) || blocks.at(-1);
      if (visible) onUpdatePosition(windowData.chapterIndex, Number(visible.dataset.startOffset));
    }, 500);
  };

  return (
    <section className="reader-page native-reader">
      <NativeReaderToolbar data={data} panelMode={panelMode} setPanelMode={changePanel} onBack={onBack} onSettings={onSettings} floatingAvailable={floatingAvailable} floatingVisible={floatingVisible} onFloatingToggle={onFloatingToggle} onOpenSettings={onOpenSettings} />
      <div className="reader-layout">
        <aside className="toc-panel">
          <div className="toc-title"><span>{panelMode === "toc" ? "目录" : panelMode === "search" ? "书内搜索" : "书签"}</span><small>{panelMode === "toc" ? `${data.book.chapters.length} 章` : ""}</small></div>
          {panelMode === "toc" ? <div className="toc-list">{data.book.chapters.map((chapter) => <button key={chapter.index} className={data.position.chapterIndex === chapter.index ? "selected" : ""} onClick={() => navigate({ kind: "position", chapterIndex: chapter.index, charOffset: 0 })}><span>{String(chapter.index + 1).padStart(2, "0")}</span>{chapter.title}</button>)}</div> : null}
          {panelMode === "search" ? <div className="reader-side-content"><form onSubmit={submitSearch}><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="输入关键词后回车" /><button className="primary-button" type="submit">搜索</button></form>{state.search.status === "loading" ? <p>正在搜索真实正文…</p> : null}{state.search.error ? <p className="reader-side-error">{state.search.error}</p> : null}{state.search.page?.results.map((result) => <button key={result.id} className="reader-side-result" onClick={() => navigate({ kind: "position", chapterIndex: result.chapterIndex, charOffset: result.startOffset })}><strong>{result.chapterTitle}</strong><span>{result.excerpt}</span></button>)}{state.search.status === "ready" && state.search.page?.total === 0 ? <p>没有匹配内容</p> : null}</div> : null}
          {panelMode === "bookmarks" ? <div className="reader-side-content">{playback.sentence ? <button className="primary-button bookmark-current" onClick={() => onAddBookmark(playback.sentence)}>收藏当前句</button> : <p>开始朗读后可收藏当前句。</p>}{state.bookmarks.status === "loading" ? <p>正在读取书签…</p> : null}{state.bookmarks.error ? <p className="reader-side-error">{state.bookmarks.error}</p> : null}{state.bookmarks.page?.items.map((bookmark) => <div key={bookmark.id} className="reader-bookmark"><button onClick={() => navigate({ kind: "position", chapterIndex: bookmark.chapterIndex, charOffset: bookmark.startOffset })}><strong>{bookmark.chapterTitle}</strong><span>{bookmark.text}</span></button><button aria-label={`删除书签 ${bookmark.text}`} onClick={() => onRemoveBookmark(bookmark.id)}><X /></button></div>)}{state.bookmarks.status === "ready" && state.bookmarks.page?.total === 0 ? <p>暂无书签</p> : null}</div> : null}
          <div className="toc-footer"><UploadSimple /> 已同步阅读进度</div>
        </aside>
        <article ref={readingSheetRef} className={`reading-sheet paragraph-mode-${data.settings.paragraphMode}`} style={{ "--reading-size": `${data.settings.fontSize}px`, "--reading-line-height": data.settings.lineSpacing, fontFamily: data.settings.fontFamily }} onScroll={handleScroll}>
          <p className="chapter-index">CHAPTER {String(windowData.chapterIndex + 1).padStart(2, "0")}</p><h1>{windowData.chapterTitle}</h1><div className="title-rule" />
          {state.windowLoading ? <div className="reader-window-loading">正在加载正文窗口…</div> : null}
          {windowData.hasBefore ? <button className="window-load-button" onClick={() => onGetWindow(windowData.chapterIndex, windowData.windowStartOffset)}>加载前文</button> : null}
          <ReaderCopyView blocks={windowData.blocks} sentenceStart={sentence?.startOffset ?? null} sentenceEnd={sentence?.endOffset ?? null} readerStart={selectedStart?.chapterIndex === windowData.chapterIndex ? selectedStart.charOffset : null} chapterIndex={windowData.chapterIndex} onChooseStart={onChooseStart} paragraphMode={data.settings.paragraphMode} firstLineIndent={data.settings.firstLineIndent} />
          {windowData.hasAfter ? <button className="window-load-button" onClick={() => onGetWindow(windowData.chapterIndex, windowData.windowEndOffset)}>加载后文</button> : null}
          <div className="page-count">{data.position.progressPercent.toFixed(1)}%</div>
        </article>
      </div>
      <NativePlayer playback={playback} chapterTitle={chapterTitle} pendingCommand={state.pendingCommand} selectedStart={selectedStart} onCommand={onCommand} onNavigate={navigate} onSettings={onSettings} onLocate={locateCurrentSentence} settings={data.settings} networkNotice={networkNotice} />
    </section>
  );
}

function ImportConfirmationModal({ selection, onClose, onStart }) {
  const [confirmLargeFiles, setConfirmLargeFiles] = useState(false);
  const [duplicateMode, setDuplicateMode] = useState("cancel");
  const supportedCount = selection.items.filter((item) => item.supported).length;
  return (
    <div className="modal-backdrop"><div className="paste-modal import-confirmation" role="dialog" aria-modal="true" aria-labelledby="import-confirm-title">
      <div className="modal-header"><div><span className="modal-icon"><FileArrowUp weight="fill" /></span><div><h2 id="import-confirm-title">确认导入</h2><p>已选择 {selection.total} 个文件，其中 {supportedCount} 个格式受支持</p></div></div><IconButton label="关闭" onClick={onClose}><X /></IconButton></div>
      <div className="selection-list">{selection.items.map((item) => <div key={item.itemId} className={!item.supported ? "unsupported" : ""}><strong>{item.name}</strong><span>{item.format || "未知格式"}{item.large ? " · 大文件" : ""}{item.duplicate.exists ? ` · 已存在「${item.duplicate.title}」` : ""}{!item.supported ? " · 不支持" : ""}</span></div>)}</div>
      {selection.largeFileCount > 0 ? <label className="confirmation-row"><input type="checkbox" checked={confirmLargeFiles} onChange={(event) => setConfirmLargeFiles(event.target.checked)} />我确认导入 {selection.largeFileCount} 个大文件</label> : null}
      {selection.duplicateCount > 0 ? <label className="field-label">重复内容处理<select value={duplicateMode} onChange={(event) => setDuplicateMode(event.target.value)}><option value="cancel">跳过重复内容</option><option value="overwrite">覆盖并沿用已有解析</option><option value="reparse">重新预处理文本</option></select></label> : null}
      <div className="confirmation-actions"><button className="secondary-button" onClick={onClose}>取消</button><button className="primary-button" disabled={supportedCount === 0 || (selection.largeFileCount > 0 && !confirmLargeFiles)} onClick={() => onStart({ selectionId: selection.selectionId, confirmLargeFiles, duplicateMode })}>开始导入</button></div>
    </div></div>
  );
}

function SettingsRange({ label, value, min, max, step, disabled, formatValue, onCommit }) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = (nextValue) => {
    const numericValue = Number(nextValue);
    if (numericValue !== value) onCommit(numericValue);
  };
  return (
    <label className="settings-field slider-field">
      <span>{label} <strong>{formatValue(draft)}</strong></span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={draft}
        disabled={disabled}
        onChange={(event) => setDraft(Number(event.target.value))}
        onPointerUp={(event) => commit(event.currentTarget.value)}
        onKeyUp={(event) => commit(event.currentTarget.value)}
        onBlur={(event) => commit(event.currentTarget.value)}
      />
    </label>
  );
}

function formatUpdateTime(value) {
  if (!value) return "尚未检查";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "尚未检查";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).format(date);
}

function SettingsModal({ preferences, speech, floatingSettings, version, softwareUpdate, pending, onUpdateApp, onUpdateSpeech, onUpdateFloating, onCheckUpdate, onDownloadUpdate, onSkipUpdate, onInstallUpdate, onOpenUpdatePage, onClose }) {
  const [activeTab, setActiveTab] = useState("reading");
  const themes = ["白天", "护眼", "米黄", "夜间"];
  const edgeVoices = speech.voices.filter((voice) => voice.backend === "edge");
  const localVoices = speech.voices.filter((voice) => voice.backend === "sapi");
  const customTextColor = floatingSettings.textColor !== "auto";
  const isPending = (scope, key) => pending.includes(`${scope}.${key}`);
  const pickerColor = floatingPickerColor(floatingSettings);
  const tabs = [
    ["reading", "朗读与悬浮"],
    ["general", "常规"],
    ["updates", "更新与关于"],
  ];
  return (
    <div className="modal-backdrop"><div className="paste-modal settings-modal" role="dialog" aria-modal="true" aria-labelledby="settings-title">
      <div className="modal-header settings-modal-header"><div><span className="modal-icon"><GearSix weight="fill" /></span><div><h2 id="settings-title">设置</h2><p>每项修改都会立即反馈，并自动保存</p></div></div><IconButton label="关闭设置" onClick={onClose}><X /></IconButton></div>
      <div className="settings-layout">
        <nav className="settings-nav" role="tablist" aria-label="设置分类">
          {tabs.map(([value, label]) => <button key={value} role="tab" aria-selected={activeTab === value} className={activeTab === value ? "selected" : ""} onClick={() => setActiveTab(value)}>{label}</button>)}
        </nav>
        <div className="settings-scroll" data-settings-tab={activeTab}>
          {activeTab === "general" ? <>
            <section className="settings-section"><h3>界面主题</h3><div className="theme-options">{themes.map((theme) => <button key={theme} className={preferences.theme === theme ? "selected" : ""} disabled={isPending("app", "theme")} onClick={() => onUpdateApp({ theme })}>{theme}</button>)}</div></section>
            <section className="settings-section"><h3>启动与关闭</h3>
              <label className="confirmation-row"><input type="checkbox" checked={preferences.autoOpenLast} disabled={isPending("app", "autoOpenLast")} onChange={(event) => onUpdateApp({ autoOpenLast: event.target.checked })} />启动时自动打开上次阅读内容</label>
              <label className="confirmation-row"><input type="checkbox" checked={preferences.closeToTray} disabled={isPending("app", "closeToTray")} onChange={(event) => onUpdateApp({ closeToTray: event.target.checked })} />点击关闭按钮时最小化到系统托盘（关闭此开关则退出程序）</label>
            </section>
            <section className="settings-section"><h3>缓存与数据</h3><p>书架、正文缓存、源文件备份与语音缓存保存在 QYReader 本地数据目录；应用不会上传阅读内容。</p></section>
          </> : null}
          {activeTab === "reading" ? <>
            <section className="settings-section speech-settings"><h3>朗读设置</h3>
              <label className="settings-field"><span>朗读音色</span><select value={speech.settings.ttsVoiceId} disabled={isPending("speech", "ttsVoiceId")} onChange={(event) => onUpdateSpeech({ ttsVoiceId: event.target.value })}>
                <optgroup label="Edge 神经音色（需联网）">{edgeVoices.map((voice) => <option key={voice.id} value={voice.id}>{voice.label}</option>)}</optgroup>
                <optgroup label="本地系统音色（离线）">{localVoices.map((voice) => <option key={voice.id || "system-default"} value={voice.id}>{voice.label}</option>)}</optgroup>
              </select></label>
              {speech.loadingLocalVoices ? <p className="settings-hint">正在读取 Windows 本地音色…</p> : null}
              {speech.localVoiceError ? <p className="settings-hint warning">{speech.localVoiceError}</p> : null}
              <SettingsRange label="语速" min={80} max={400} step={10} value={speech.settings.ttsRate} disabled={isPending("speech", "ttsRate")} formatValue={(value) => `${(value / 200).toFixed(2)}×`} onCommit={(ttsRate) => onUpdateSpeech({ ttsRate })} />
              <SettingsRange label="句间停顿" min={0} max={1} step={0.05} value={speech.settings.sentenceGapSeconds} disabled={isPending("speech", "sentenceGapSeconds")} formatValue={(value) => `${Number(value).toFixed(2)} 秒`} onCommit={(sentenceGapSeconds) => onUpdateSpeech({ sentenceGapSeconds })} />
              <p className="settings-hint inline">切换音色或语速时，正在朗读的当前句会使用新设置重新开始，文字与声音保持一致。</p>
            </section>
            <section className="settings-section floating-settings-section"><h3>悬浮朗读</h3>
              <div className="settings-field"><span>悬浮窗背景</span><div className="theme-options compact">{[["light", "浅色"], ["sepia", "米黄"], ["dark", "深色"]].map(([value, label]) => <button key={value} className={floatingSettings.background === value ? "selected" : ""} disabled={isPending("floating", "background")} onClick={() => onUpdateFloating({ background: value })}>{label}</button>)}</div></div>
              <label className="confirmation-row"><input type="checkbox" checked={floatingSettings.hoverDisplayEnabled} disabled={isPending("floating", "hoverDisplayEnabled")} onChange={(event) => onUpdateFloating({ hoverDisplayEnabled: event.target.checked })} />鼠标移开时显示上一段和下一段</label>
              <label className="confirmation-row"><input type="checkbox" checked={floatingSettings.followReaderFont} disabled={isPending("floating", "followReaderFont")} onChange={(event) => onUpdateFloating({ followReaderFont: event.target.checked })} />跟随主阅读器字号（滚轮调字号后自动关闭）</label>
              <div className="settings-field color-setting"><span>朗读字体颜色</span><div><input aria-label="悬浮窗朗读字体颜色" title="选择颜色后立即切换为自定义配色" type="color" value={pickerColor} onChange={(event) => { const patch = floatingTextColorPatch(event.target.value); if (patch) onUpdateFloating(patch); }} /><button className={!customTextColor ? "selected" : ""} onClick={() => onUpdateFloating({ textColor: "auto" })}>自动配色</button><span className="color-setting-value">{customTextColor ? floatingSettings.textColor : "选择颜色即使用"}</span></div></div>
            </section>
          </> : null}
          {activeTab === "updates" ? <>
            <section className="settings-section software-update-section"><h3>软件更新</h3>
              <div className="update-detail-row"><span>当前版本</span><strong>v{version || softwareUpdate.currentVersion}</strong></div>
              <label className="confirmation-row"><input type="checkbox" checked={preferences.autoCheckUpdates} disabled={isPending("app", "autoCheckUpdates")} onChange={(event) => onUpdateApp({ autoCheckUpdates: event.target.checked })} />启动时自动检查正式版更新</label>
              <div className={`update-status-card status-${softwareUpdate.status}`}><span className="update-status-dot" /><div><strong>检查状态</strong><p>{softwareUpdate.message}</p><small>上次检查：{formatUpdateTime(softwareUpdate.lastCheckedAt)}</small></div></div>
              {softwareUpdate.status === "downloading" ? <div className="update-progress" aria-label={`更新下载进度 ${softwareUpdate.progressPercent}%`}><span style={{ width: `${softwareUpdate.progressPercent}%` }} /></div> : null}
              <div className="update-actions">
                <button className="secondary-button" disabled={["checking", "downloading", "installing"].includes(softwareUpdate.status)} onClick={onCheckUpdate}>{softwareUpdate.status === "checking" ? "正在检查…" : "检查更新"}</button>
                {softwareUpdate.canDownload ? <button className="primary-button" onClick={onDownloadUpdate}>查看并下载</button> : null}
                {softwareUpdate.canInstall ? <button className="primary-button" onClick={onInstallUpdate}>立即安装</button> : null}
                {softwareUpdate.status === "available" ? <button className="secondary-button" onClick={onSkipUpdate}>跳过 v{softwareUpdate.latestVersion}</button> : null}
                <button className="secondary-button" onClick={() => onOpenUpdatePage("project")}>项目主页</button>
              </div>
              <p className="update-security-note">仅下载版本匹配的 Windows 安装包；SHA256 校验通过后才允许安装。</p>
            </section>
            <section className="settings-section about-section"><h3>关于</h3><p>启远阅读（QYReader） {version || "2.1.1"} · Qt WebEngine 桌面版</p></section>
          </> : null}
        </div>
      </div>
    </div></div>
  );
}

function UpdateAvailableModal({ update, onDownload, onSkip, onOpenRelease, onClose }) {
  const notes = update.releaseNotes?.trim() || "本次更新暂未提供详细说明，可打开完整发布页查看。";
  return (
    <div className="modal-backdrop update-prompt-backdrop"><div className="paste-modal update-prompt-modal" role="dialog" aria-modal="true" aria-labelledby="update-prompt-title">
      <div className="modal-header"><div><span className="modal-icon update"><GearSix weight="fill" /></span><div><h2 id="update-prompt-title">发现新版本 v{update.latestVersion}</h2><p>当前版本 v{update.currentVersion} · 更新前先看看优化内容</p></div></div><IconButton label="稍后再说" onClick={onClose}><X /></IconButton></div>
      <section className="release-notes-card"><h3>本次更新内容</h3><pre>{notes}</pre></section>
      <p className="update-security-note">下载后会先完成 SHA256 安全校验，不会静默安装。</p>
      <div className="update-prompt-actions">
        <button className="secondary-button" onClick={onOpenRelease}>查看完整说明</button>
        <button className="secondary-button" onClick={onSkip}>跳过此版本</button>
        <button className="secondary-button" onClick={onClose}>稍后再说</button>
        <button className="primary-button" onClick={onDownload}>下载更新</button>
      </div>
    </div></div>
  );
}

function MainApplication() {
  const qaMode = new URLSearchParams(window.location.search).get("qa");
  const qaFloating = qaMode === "floating";
  const qaNetwork = qaMode === "network";
  const qaUpdate = qaMode === "update";
  const qaEmptyLibrary = qaMode === "empty-library";
  const nativeTransportAvailable = Boolean(window.qt?.webChannelTransport);
  const demoQaFloating = qaFloating && !nativeTransportAvailable;
  const connectionRef = useRef(null);
  const [page, setPage] = useState(demoQaFloating || qaNetwork ? "reader" : "library");
  const [books, setBooks] = useState([]);
  const [libraryLoading, setLibraryLoading] = useState(true);
  const [bridgeError, setBridgeError] = useState("");
  const [bridgeMode, setBridgeMode] = useState(nativeTransportAvailable ? "native" : "demo");
  const [windowControls, setWindowControls] = useState(EMPTY_CONTROLS);
  const [windowState, setWindowState] = useState({ isMaximized: false, isFullScreen: false });
  const [capabilities, setCapabilities] = useState(EMPTY_CAPABILITIES);
  const [importState, setImportState] = useState(() => ({ ...EMPTY_IMPORT_STATE }));
  const [importSelection, setImportSelection] = useState(null);
  const [openAfterImportBookId, setOpenAfterImportBookId] = useState("");
  const [pasteOpen, setPasteOpen] = useState(false);
  const [floating, setFloating] = useState(demoQaFloating);
  const [playing, setPlaying] = useState(demoQaFloating || qaNetwork);
  const [fontSize, setFontSize] = useState(21);
  const [nativeFloatingState, setNativeFloatingState] = useState(null);
  const [appPreferences, setAppPreferences] = useState(DEFAULT_APP_PREFERENCES);
  const [speechState, setSpeechState] = useState(DEFAULT_SPEECH_STATE);
  const [appVersion, setAppVersion] = useState("2.1.1");
  const [softwareUpdate, setSoftwareUpdate] = useState(DEFAULT_SOFTWARE_UPDATE);
  const [updatePromptVersion, setUpdatePromptVersion] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [networkNotice, handlePlaybackEvent] = usePlaybackNetworkNotice(qaNetwork ? NETWORK_FALLBACK_NOTICE : null);
  const settingsPendingRef = useRef(new Set());
  const [settingsPending, setSettingsPending] = useState([]);
  const [readerState, dispatchReader] = useReducer(readerReducer, EMPTY_READER_STATE);
  const [selectedReaderStart, setSelectedReaderStart] = useState(null);
  const readerOpenRequestRef = useRef("");
  const readerSessionRef = useRef("");
  const readerDataRef = useRef(null);
  const readerStartTargetRef = useRef(null);
  const playbackSequenceRef = useRef(-1);
  const readerWindowRequestRef = useRef(0);
  const audioWindowPendingRef = useRef("");
  const readerSearchRequestRef = useRef("");
  const pendingOpenIntentRef = useRef(null);
  const consumedOpenIntentsRef = useRef(new Set());
  const startupIntentConsumedRef = useRef(false);
  const updateCheckStartedRef = useRef(false);
  const dismissedUpdateVersionsRef = useRef(new Set());

  useEffect(() => {
    let active = true;
    const readBridgeMessage = (raw) => {
      try {
        return JSON.parse(raw).message || "桌面操作失败。";
      } catch {
        return "桌面操作失败。";
      }
    };
    const attachConnection = (connected) => {
      if (!active) {
        connected.dispose();
        return;
      }
      connectionRef.current?.dispose();
      connectionRef.current = connected;
      setBridgeMode(connected.mode);
      setBooks(connected.mode === "demo" && qaEmptyLibrary ? [] : connected.initialState.data.library.books);
      setCapabilities(connected.initialState.data.capabilities);
      setAppPreferences(connected.initialState.data.preferences);
      setSpeechState(connected.initialState.data.speech);
      setWindowState(connected.initialState.data.window);
      setAppVersion(connected.initialState.data.app.version);
      setSoftwareUpdate(connected.initialState.data.softwareUpdate);
      setWindowControls(connected.controls);
      if (qaUpdate && connected.mode === "demo") {
        updateCheckStartedRef.current = true;
        setSoftwareUpdate({
          ...connected.initialState.data.softwareUpdate,
          status: "available",
          latestVersion: "2.1.2",
          message: "发现新版本 QYReader 2.1.2，可以查看优化内容后决定是否更新。",
          releaseUrl: "https://github.com/superadminist/QYReader/releases/tag/v2.1.2",
          publishedAt: "2026-09-15T08:00:00Z",
          releaseNotes: "## 本次优化\n\n- 修复悬浮窗暂停时文字跳到下一句\n- 朗读音色和语速切换立即生效\n- 设置中心改为紧凑分页并修复滚动闪烁",
          canDownload: true,
        });
      }
      connected.onBridgeError((raw) => {
        if (active) setBridgeError(readBridgeMessage(raw));
      });
      connected.onAppPreferencesChanged((preferences) => {
        if (active) setAppPreferences(preferences);
      });
      connected.onSpeechPreferencesChanged((speech) => {
        if (active) setSpeechState(speech);
      });
      connected.onSoftwareUpdateChanged((state) => {
        if (active) setSoftwareUpdate(state);
      });
      connected.onWindowStateChanged((nextWindowState) => {
        if (active) setWindowState(nextWindowState);
      });
      connected.onImportProgress((event) => {
        if (!active) return;
        setImportState((previous) => previous.jobId && previous.jobId !== event.jobId ? previous : {
          ...previous,
          status: "processing",
          jobId: event.jobId,
          completed: event.completed,
          total: event.total,
          succeeded: event.succeeded,
          failed: event.failed,
          message: event.error?.message || `正在处理「${event.item.name}」`,
          tone: event.error ? "warning" : "info",
        });
      });
      connected.onImportFinished(async (event) => {
        if (!active) return;
        const firstFailure = event.results.find((item) => item.status === "failed")?.error?.message;
        const succeeded = event.succeeded > 0;
        const partial = succeeded && event.failed > 0;
        const message = event.state === "cancelled"
          ? `导入已取消，已处理 ${event.processed} / ${event.total} 项。`
          : partial
            ? `已导入 ${event.succeeded} 项，${event.failed} 项失败。${firstFailure ? ` ${firstFailure}` : ""}`
            : succeeded
              ? `已成功导入 ${event.succeeded} 项；真实阅读器将在阶段 3 接入。`
              : firstFailure || "导入失败，内容库未新增可用内容。";
        setImportState({
          status: event.state === "cancelled" ? "cancelled" : partial ? "partial" : succeeded ? "succeeded" : "failed",
          jobId: event.jobId,
          completed: event.processed,
          total: event.total,
          succeeded: event.succeeded,
          failed: event.failed,
          message,
          tone: event.state === "cancelled" ? "info" : partial ? "warning" : succeeded ? "success" : "error",
        });
        setPasteOpen(false);
        setImportSelection(null);
        setOpenAfterImportBookId(event.openAfterImportBookId);
        if (connected.mode === "native" && event.openAfterImportBookId) pendingOpenIntentRef.current = { jobId: event.jobId, bookId: event.openAfterImportBookId, status: "waitingRefresh" };
        setPage("library");
        if (connected.mode === "demo") {
          setBooks([...connected.initialState.data.library.books]);
          return;
        }
        try {
          const refreshed = await connectBridge();
          attachConnection(refreshed);
          const intent = pendingOpenIntentRef.current;
          const intentKey = intent ? `${intent.jobId}:${intent.bookId}` : "";
          const canOpen = intent
            && refreshed.initialState.data.capabilities.reader
            && refreshed.initialState.data.library.books.some((book) => book.id === intent.bookId)
            && !consumedOpenIntentsRef.current.has(intentKey);
          if (canOpen) {
            intent.status = "opening";
            consumedOpenIntentsRef.current.add(intentKey);
            await beginReaderOpen(refreshed, intent.bookId);
          }
        } catch (error) {
          if (active) setBridgeError(error.message || "导入完成，但内容库刷新失败。");
        }
      });
      connected.onReaderOpened((event) => {
        if (!active || event.requestId !== readerOpenRequestRef.current) return;
        if (!event.ok || !event.data) {
          const message = event.error?.message || "无法打开真实内容。";
          dispatchReader({ type: "FAILED", error: message });
          readerSessionRef.current = "";
          readerDataRef.current = null;
          readerStartTargetRef.current = null;
          setSelectedReaderStart(null);
          pendingOpenIntentRef.current = null;
          setImportState({ ...EMPTY_IMPORT_STATE, status: "failed", message, tone: "error" });
          setPage("library");
          return;
        }
        readerSessionRef.current = event.data.sessionId;
        readerDataRef.current = event.data;
        readerStartTargetRef.current = null;
        setSelectedReaderStart(null);
        playbackSequenceRef.current = -1;
        readerWindowRequestRef.current += 1;
        audioWindowPendingRef.current = "";
        pendingOpenIntentRef.current = null;
        dispatchReader({ type: "OPENED", requestId: event.requestId, data: event.data });
        setPage("reader");
      });
      connected.onReaderSearchFinished((event) => {
        if (!active || event.sessionId !== readerSessionRef.current || event.requestId !== readerSearchRequestRef.current) return;
        if (event.ok && event.data) dispatchReader({ type: "SEARCH_RESULT", page: event.data });
        else dispatchReader({ type: "SEARCH_ERROR", error: event.error?.message || "书内搜索失败。" });
      });
      connected.onReaderPlaybackChanged(async (event) => {
        if (!active || event.sessionId !== readerSessionRef.current || event.sequence <= playbackSequenceRef.current) return;
        playbackSequenceRef.current = event.sequence;
        handlePlaybackEvent(event);
        const current = readerDataRef.current;
        if (!current) return;
        readerDataRef.current = { ...current, position: event.playback.position, playback: event.playback };
        dispatchReader({ type: "PLAYBACK", playback: event.playback });
        if (event.error && event.error.code !== "EDGE_OFFLINE_FALLBACK") setBridgeError(event.error.message);
        const sentence = event.playback.sentence;
        const currentWindow = readerDataRef.current.window;
        if (event.reason !== "sentenceStart" || !sentence || windowContainsSentence(currentWindow, sentence)) return;
        const sentenceKey = `${event.sessionId}:${sentence.chapterIndex}:${sentence.startOffset}`;
        if (audioWindowPendingRef.current?.key === sentenceKey) return;
        const requestId = ++readerWindowRequestRef.current;
        audioWindowPendingRef.current = { key: sentenceKey, requestId };
        try {
          const response = await connected.reader.getWindow({ sessionId: event.sessionId, chapterIndex: sentence.chapterIndex, anchorOffset: sentence.startOffset });
          if (!active || event.sessionId !== readerSessionRef.current
            || !shouldApplyAudioWindow(requestId, readerWindowRequestRef.current, sentence, readerDataRef.current?.playback, response.data)) return;
          readerDataRef.current = { ...readerDataRef.current, window: response.data };
          dispatchReader({ type: "WINDOW", window: response.data });
        } catch (error) {
          if (active && requestId === readerWindowRequestRef.current) setBridgeError(error.message || "无法加载当前朗读位置。");
        } finally {
          if (audioWindowPendingRef.current?.requestId === requestId) audioWindowPendingRef.current = null;
        }
      });
      connected.onFloatingReaderChanged((event) => {
        if (active) setNativeFloatingState(event.state);
      });
      connected.floating.getState().then((response) => {
        if (active && connectionRef.current === connected) setNativeFloatingState(response.data);
      }).catch((error) => {
        if (active && connected.initialState.data.capabilities.floatingReader) setBridgeError(error.message || "无法读取悬浮朗读状态。");
      });
      if (!startupIntentConsumedRef.current) {
        startupIntentConsumedRef.current = true;
        const startupBookId = connected.initialState.data.preferences.startupBookId;
        const canAutoOpen = connected.mode === "native"
          && connected.initialState.data.capabilities.reader
          && connected.initialState.data.library.books.some((book) => book.id === startupBookId);
        if (canAutoOpen) beginReaderOpen(connected, startupBookId);
      }
      if (!updateCheckStartedRef.current && connected.initialState.data.preferences.autoCheckUpdates) {
        updateCheckStartedRef.current = true;
        connected.updates.check({ manual: false }).then((response) => {
          if (active && connectionRef.current === connected) setSoftwareUpdate(response.data);
        }).catch((error) => {
          if (active) setBridgeError(error.message || "自动检查更新失败。");
        });
      }
      setLibraryLoading(false);
    };
    connectBridge().then(attachConnection).catch((error) => {
      if (!active) return;
      const failedConnection = error.connection;
      if (failedConnection) attachConnection(failedConnection);
      setBooks(error.initialData?.library?.books || []);
      setCapabilities(error.initialData?.capabilities || EMPTY_CAPABILITIES);
      setAppPreferences(error.initialData?.preferences || DEFAULT_APP_PREFERENCES);
      setAppVersion(error.initialData?.app?.version || "2.1.1");
      setSoftwareUpdate(error.initialData?.softwareUpdate || DEFAULT_SOFTWARE_UPDATE);
      setBridgeError(error.message || "无法连接桌面程序。");
      setLibraryLoading(false);
    });
    return () => {
      active = false;
      connectionRef.current?.dispose();
      connectionRef.current = null;
    };
  }, []);

  useEffect(() => {
    const version = softwareUpdate.latestVersion;
    if (
      softwareUpdate.status === "available"
      && version
      && !dismissedUpdateVersionsRef.current.has(version)
    ) {
      setUpdatePromptVersion(version);
    } else if (softwareUpdate.status !== "available") {
      setUpdatePromptVersion("");
    }
  }, [softwareUpdate.status, softwareUpdate.latestVersion]);

  const beginReaderOpen = async (connection, bookId) => {
    readerOpenRequestRef.current = "";
    readerSessionRef.current = "";
    readerDataRef.current = null;
    dispatchReader({ type: "OPENING", bookId });
    setPage("reader");
    try {
      const response = await connection.reader.openBook(bookId);
      readerOpenRequestRef.current = response.data.requestId;
      dispatchReader({ type: "OPEN_ACCEPTED", requestId: response.data.requestId });
    } catch (error) {
      const message = error.message || "无法打开真实内容。";
      dispatchReader({ type: "FAILED", error: message });
      setImportState({ ...EMPTY_IMPORT_STATE, status: "failed", message, tone: "error" });
      setPage("library");
    }
  };

  const selectFiles = async () => {
    const connection = connectionRef.current;
    if (!connection) return;
    setImportState({ ...EMPTY_IMPORT_STATE, status: "selecting", message: "正在选择文件…" });
    try {
      const response = await connection.imports.selectFiles();
      if (response.data.cancelled) {
        setImportState({ ...EMPTY_IMPORT_STATE });
        return;
      }
      setImportSelection(response.data);
      setImportState({ ...EMPTY_IMPORT_STATE, status: "confirming" });
    } catch (error) {
      setImportState({ ...EMPTY_IMPORT_STATE, status: "failed", message: error.message || "无法选择导入文件。", tone: "error" });
    }
  };
  const startFileImport = async (input) => {
    const connection = connectionRef.current;
    if (!connection || !importSelection) return;
    setImportSelection(null);
    setImportState({ ...EMPTY_IMPORT_STATE, status: "processing", total: importSelection.total, message: "导入任务正在排队…" });
    try {
      const response = await connection.imports.startFileImport(input);
      setImportState((previous) => ({ ...previous, jobId: response.data.jobId }));
    } catch (error) {
      setImportState({ ...EMPTY_IMPORT_STATE, status: "failed", message: error.message || "无法开始文件导入。", tone: "error" });
    }
  };
  const startPasteImport = async (input) => {
    const connection = connectionRef.current;
    if (!connection) return "桌面通信尚未就绪。";
    setImportState({ ...EMPTY_IMPORT_STATE, status: "processing", total: 1, message: "正在加入粘贴内容…" });
    try {
      const response = await connection.imports.startPasteImport(input);
      setImportState((previous) => ({ ...previous, jobId: response.data.jobId }));
      return "";
    } catch (error) {
      const message = error.message || "无法加入粘贴内容。";
      setImportState({ ...EMPTY_IMPORT_STATE, status: "failed", message, tone: "error" });
      return message;
    }
  };
  const cancelImport = async () => {
    const connection = connectionRef.current;
    if (!connection || !importState.jobId) return;
    setImportState((previous) => ({ ...previous, status: "cancelling", message: "正在取消导入…" }));
    try {
      const response = await connection.imports.cancelImport(importState.jobId);
      if (!response.data.cancelRequested) {
        setImportState((previous) => ({ ...previous, status: "processing", message: "当前导入任务无法取消。", tone: "warning" }));
      }
    } catch (error) {
      setImportState((previous) => ({ ...previous, status: "processing", message: error.message || "取消导入失败。", tone: "error" }));
    }
  };
  const openBook = (book) => {
    if (bridgeMode === "demo") {
      setPage("reader");
      setPasteOpen(false);
      return;
    }
    const connection = connectionRef.current;
    if (!connection || !capabilities.reader) {
      setImportState({ ...EMPTY_IMPORT_STATE, status: "unavailable", message: "真实阅读器当前不可用。", tone: "warning" });
      return;
    }
    setOpenAfterImportBookId(book.id);
    setPasteOpen(false);
    beginReaderOpen(connection, book.id);
  };
  const removeBook = async (book) => {
    const connection = connectionRef.current;
    if (!connection) return "桌面通信尚未就绪。";
    try {
      await connection.library.removeBook(book.id);
      setBooks((previous) => previous.filter((item) => item.id !== book.id));
      setOpenAfterImportBookId((previous) => previous === book.id ? "" : previous);
      return "";
    } catch (error) {
      return error.message || "移除内容失败，请稍后重试。";
    }
  };
  const getReaderWindow = async (chapterIndex, anchorOffset) => {
    const connection = connectionRef.current;
    const sessionId = readerSessionRef.current;
    if (!connection || !sessionId) return;
    const requestId = ++readerWindowRequestRef.current;
    audioWindowPendingRef.current = "";
    dispatchReader({ type: "WINDOW_LOADING" });
    try {
      const response = await connection.reader.getWindow({ sessionId, chapterIndex, anchorOffset });
      if (sessionId !== readerSessionRef.current || requestId !== readerWindowRequestRef.current) return;
      readerDataRef.current = { ...readerDataRef.current, window: response.data };
      dispatchReader({ type: "WINDOW", window: response.data });
    } catch (error) {
      if (requestId === readerWindowRequestRef.current) dispatchReader({ type: "FAILED", error: error.message || "正文窗口加载失败。" });
    }
  };
  const clearReaderStart = () => {
    readerStartTargetRef.current = null;
    setSelectedReaderStart(null);
  };
  const chooseReaderStart = (target) => {
    readerStartTargetRef.current = target;
    setSelectedReaderStart(target);
  };
  const navigateReader = async (target, { keepReaderStart = false } = {}) => {
    const connection = connectionRef.current;
    const sessionId = readerSessionRef.current;
    if (!connection || !sessionId) return false;
    if (!keepReaderStart) clearReaderStart();
    const requestId = ++readerWindowRequestRef.current;
    audioWindowPendingRef.current = "";
    dispatchReader({ type: "WINDOW_LOADING" });
    try {
      const response = await connection.reader.navigate({ sessionId, target });
      if (sessionId !== readerSessionRef.current || requestId !== readerWindowRequestRef.current) return false;
      readerDataRef.current = { ...readerDataRef.current, position: response.data.position, window: response.data.window, playback: response.data.playback };
      dispatchReader({ type: "NAVIGATED", data: response.data });
      return true;
    } catch (error) {
      if (requestId === readerWindowRequestRef.current) {
        setBridgeError(error.message || "无法跳转到目标位置。");
        dispatchReader({ type: "WINDOW", window: readerDataRef.current.window });
      }
      return false;
    }
  };
  const updateReaderPosition = async (chapterIndex, charOffset) => {
    const connection = connectionRef.current;
    const sessionId = readerSessionRef.current;
    if (!connection || !sessionId) return;
    try {
      const response = await connection.reader.updatePosition({ sessionId, chapterIndex, charOffset });
      if (sessionId !== readerSessionRef.current || !response.data.updated) return;
      readerDataRef.current = { ...readerDataRef.current, position: response.data.position, playback: { ...readerDataRef.current.playback, position: response.data.position } };
      dispatchReader({ type: "POSITION", position: response.data.position });
    } catch (error) {
      setBridgeError(error.message || "阅读进度同步失败。");
    }
  };
  const searchReader = async (query) => {
    const connection = connectionRef.current;
    const sessionId = readerSessionRef.current;
    if (!connection || !sessionId) return;
    dispatchReader({ type: "SEARCH_LOADING", query });
    try {
      const response = await connection.reader.search({ sessionId, query, cursor: "" });
      readerSearchRequestRef.current = response.data.requestId;
      dispatchReader({ type: "SEARCH_LOADING", query, requestId: response.data.requestId });
    } catch (error) {
      dispatchReader({ type: "SEARCH_ERROR", error: error.message || "书内搜索失败。" });
    }
  };
  const loadReaderBookmarks = async () => {
    const connection = connectionRef.current;
    const sessionId = readerSessionRef.current;
    if (!connection || !sessionId) return;
    dispatchReader({ type: "BOOKMARKS_LOADING" });
    try {
      const response = await connection.reader.listBookmarks({ sessionId, cursor: "" });
      if (sessionId === readerSessionRef.current) dispatchReader({ type: "BOOKMARKS", page: response.data });
    } catch (error) {
      dispatchReader({ type: "BOOKMARKS_ERROR", error: error.message || "书签读取失败。" });
    }
  };
  const addReaderBookmark = async (sentence) => {
    const connection = connectionRef.current;
    const sessionId = readerSessionRef.current;
    if (!connection || !sessionId) return;
    try {
      await connection.reader.addBookmark({ sessionId, chapterIndex: sentence.chapterIndex, startOffset: sentence.startOffset, endOffset: sentence.endOffset, note: "" });
      await loadReaderBookmarks();
    } catch (error) {
      dispatchReader({ type: "BOOKMARKS_ERROR", error: error.message || "书签添加失败。" });
    }
  };
  const removeReaderBookmark = async (bookmarkId) => {
    const connection = connectionRef.current;
    const sessionId = readerSessionRef.current;
    if (!connection || !sessionId) return;
    try {
      await connection.reader.removeBookmark({ sessionId, bookmarkId });
      await loadReaderBookmarks();
    } catch (error) {
      dispatchReader({ type: "BOOKMARKS_ERROR", error: error.message || "书签删除失败。" });
    }
  };
  const controlReaderPlayback = async (command) => {
    const connection = connectionRef.current;
    const sessionId = readerSessionRef.current;
    if (!connection || !sessionId) return;
    if (command === "play" && readerStartTargetRef.current) {
      const selectedStart = readerStartTargetRef.current;
      const positioned = await navigateReader(selectedStart, { keepReaderStart: true });
      if (!positioned) return;
      clearReaderStart();
    }
    dispatchReader({ type: "PLAYBACK_PENDING", command });
    try {
      const response = await connection.reader.controlPlayback({ sessionId, command });
      if (!response.data.accepted) dispatchReader({ type: "PLAYBACK", playback: readerDataRef.current.playback });
    } catch (error) {
      dispatchReader({ type: "PLAYBACK", playback: readerDataRef.current.playback });
      setBridgeError(error.message || "播放控制失败。");
    }
  };
  const updateReaderSettings = async (patch) => {
    const connection = connectionRef.current;
    const sessionId = readerSessionRef.current;
    if (!connection || !sessionId) return;
    try {
      const response = await connection.reader.updateSettings({ sessionId, patch });
      readerDataRef.current = { ...readerDataRef.current, settings: response.data };
      dispatchReader({ type: "SETTINGS", settings: response.data });
    } catch (error) {
      setBridgeError(error.message || "阅读设置保存失败。");
    }
  };
  const switchToFloatingReader = async () => {
    const connection = connectionRef.current;
    if (!connection || !capabilities.floatingReader) return;
    try {
      const response = await connection.floating.show();
      setNativeFloatingState(response.data);
    } catch (error) {
      setBridgeError(error.message || "悬浮朗读窗操作失败。");
    }
  };
  const toggleFloatingReader = async () => {
    if (!nativeFloatingState?.visible) return switchToFloatingReader();
    try {
      await connectionRef.current?.floating.close();
      setNativeFloatingState((previous) => previous ? { ...previous, visible: false } : previous);
    } catch (error) {
      setBridgeError(error.message || "悬浮朗读窗操作失败。");
    }
  };
  const beginSettingsSave = (scope, patch) => {
    const ids = settingsPatchIds(scope, patch);
    if (ids.some((id) => settingsPendingRef.current.has(id))) return null;
    ids.forEach((id) => settingsPendingRef.current.add(id));
    setSettingsPending([...settingsPendingRef.current]);
    return ids;
  };
  const finishSettingsSave = (ids) => {
    ids.forEach((id) => settingsPendingRef.current.delete(id));
    setSettingsPending([...settingsPendingRef.current]);
  };
  const updateAppPreferences = async (patch) => {
    const connection = connectionRef.current;
    if (!connection) return;
    const pendingIds = beginSettingsSave("app", patch);
    if (!pendingIds) return;
    const previousPreferences = appPreferences;
    setAppPreferences((current) => {
      const next = { ...current, ...patch };
      if (patch.theme) next.colorScheme = patch.theme === "夜间" ? "dark" : "light";
      return next;
    });
    try {
      const response = await connection.app.updatePreferences({ patch });
      setAppPreferences(response.data);
      if (patch.autoCheckUpdates === true) {
        updateCheckStartedRef.current = true;
        connection.updates.check({ manual: false }).then((updateResponse) => {
          if (connectionRef.current === connection) setSoftwareUpdate(updateResponse.data);
        }).catch((error) => {
          setBridgeError(error.message || "自动检查更新失败。");
        });
      }
    } catch (error) {
      setAppPreferences(previousPreferences);
      setBridgeError(error.message || "应用设置保存失败。");
    } finally {
      finishSettingsSave(pendingIds);
    }
  };
  const updateSpeechPreferences = async (patch) => {
    const connection = connectionRef.current;
    if (!connection) return;
    const pendingIds = beginSettingsSave("speech", patch);
    if (!pendingIds) return;
    const previousSpeech = speechState;
    const previousReaderSettings = readerDataRef.current?.settings;
    setSpeechState((current) => ({
      ...current,
      settings: { ...current.settings, ...patch },
    }));
    if (readerDataRef.current) {
      const nextSettings = { ...readerDataRef.current.settings, ...patch };
      readerDataRef.current = { ...readerDataRef.current, settings: nextSettings };
      dispatchReader({ type: "SETTINGS", settings: nextSettings });
    }
    try {
      const response = await connection.speech.updatePreferences({ patch });
      setSpeechState(response.data);
      if (readerDataRef.current) {
        const nextSettings = { ...readerDataRef.current.settings, ...response.data.settings };
        readerDataRef.current = { ...readerDataRef.current, settings: nextSettings };
        dispatchReader({ type: "SETTINGS", settings: nextSettings });
      }
    } catch (error) {
      setSpeechState(previousSpeech);
      if (readerDataRef.current && previousReaderSettings) {
        readerDataRef.current = { ...readerDataRef.current, settings: previousReaderSettings };
        dispatchReader({ type: "SETTINGS", settings: previousReaderSettings });
      }
      setBridgeError(error.message || "朗读设置保存失败。");
    } finally {
      finishSettingsSave(pendingIds);
    }
  };
  const updateFloatingPreferences = async (patch) => {
    const connection = connectionRef.current;
    if (!connection) return;
    const readerFontSize = readerDataRef.current?.settings?.fontSize;
    const effectivePatch = patch.followReaderFont === true && Number.isFinite(readerFontSize)
      ? { ...patch, fontSize: readerFontSize }
      : patch;
    const pendingIds = beginSettingsSave("floating", effectivePatch);
    if (!pendingIds) return;
    const previousValues = Object.fromEntries(
      Object.keys(effectivePatch).map((key) => [key, nativeFloatingState?.settings?.[key]]),
    );
    setNativeFloatingState((current) => mergeFloatingState(current, effectivePatch));
    try {
      const response = await connection.floating.updateSettings({ patch: effectivePatch });
      setNativeFloatingState(response.data);
    } catch (error) {
      setNativeFloatingState((current) => mergeFloatingState(current, previousValues));
      setBridgeError(error.message || "悬浮朗读设置保存失败。");
    } finally {
      finishSettingsSave(pendingIds);
    }
  };
  const checkForUpdates = async () => {
    const connection = connectionRef.current;
    if (!connection) return;
    if (softwareUpdate.latestVersion) {
      dismissedUpdateVersionsRef.current.delete(softwareUpdate.latestVersion);
    }
    try {
      const response = await connection.updates.check({ manual: true });
      setSoftwareUpdate(response.data);
    } catch (error) {
      setBridgeError(error.message || "检查更新失败。");
    }
  };
  const downloadUpdate = async () => {
    const connection = connectionRef.current;
    if (!connection || !softwareUpdate.latestVersion) return;
    setUpdatePromptVersion("");
    try {
      const response = await connection.updates.download(softwareUpdate.latestVersion);
      setSoftwareUpdate(response.data);
    } catch (error) {
      setBridgeError(error.message || "下载更新失败。");
    }
  };
  const skipUpdate = async () => {
    const connection = connectionRef.current;
    if (!connection || !softwareUpdate.latestVersion) return;
    dismissedUpdateVersionsRef.current.add(softwareUpdate.latestVersion);
    setUpdatePromptVersion("");
    try {
      const response = await connection.updates.skip(softwareUpdate.latestVersion);
      setSoftwareUpdate(response.data);
    } catch (error) {
      setBridgeError(error.message || "无法跳过该版本。");
    }
  };
  const installUpdate = async () => {
    const connection = connectionRef.current;
    if (!connection) return;
    try {
      const response = await connection.updates.install();
      setSoftwareUpdate(response.data);
    } catch (error) {
      setBridgeError(error.message || "无法启动更新安装程序。");
    }
  };
  const openUpdatePage = async (target) => {
    const connection = connectionRef.current;
    if (!connection) return;
    try {
      await connection.updates.openPage(target);
    } catch (error) {
      setBridgeError(error.message || "无法打开 GitHub 页面。");
    }
  };
  const dismissUpdatePrompt = () => {
    if (softwareUpdate.latestVersion) {
      dismissedUpdateVersionsRef.current.add(softwareUpdate.latestVersion);
    }
    setUpdatePromptVersion("");
  };
  const toggleDarkMode = () => updateAppPreferences({ theme: appPreferences.colorScheme === "dark" ? "护眼" : "夜间" });
  const navigatePage = (nextPage) => {
    if (nextPage !== "reader" || bridgeMode === "demo" || readerState.phase === "ready") {
      setPage(nextPage);
      return;
    }
    setImportState({ ...EMPTY_IMPORT_STATE, status: "ready", message: "请先从内容库选择一本真实内容。", tone: "info" });
    setPage("library");
  };
  const showUnavailable = (message) => setImportState({ ...EMPTY_IMPORT_STATE, status: "unavailable", message, tone: "info" });
  const desktopMode = bridgeMode === "native" || nativeTransportAvailable;
  const readerEnabled = bridgeMode === "demo" || capabilities.reader;
  const effectiveCapabilities = bridgeMode === "demo"
    ? { fileImport: true, pasteImport: true, webImport: true, audioImport: true }
    : capabilities;
  useEffect(() => {
    const onKeyDown = (event) => {
      const target = event.target;
      if (target instanceof HTMLElement && target.closest("input, textarea, select, [contenteditable=true]")) return;
      if (event.key === "F11" || (event.altKey && event.key === "Enter")) {
        event.preventDefault();
        windowControls.toggleFullscreen();
      } else if (event.ctrlKey && event.shiftKey && event.key.toLowerCase() === "f") {
        event.preventDefault();
        toggleFloatingReader();
      } else if (event.ctrlKey && event.key.toLowerCase() === "o") {
        event.preventDefault();
        selectFiles();
      } else if (event.ctrlKey && event.key.toLowerCase() === "p" && readerState.phase === "ready") {
        event.preventDefault();
        controlReaderPlayback(readerState.data.playback.status === "playing" ? "pause" : "play");
      } else if (event.ctrlKey && event.key.toLowerCase() === "s" && readerState.phase === "ready") {
        event.preventDefault();
        controlReaderPlayback("stop");
      } else if (!event.ctrlKey && !event.altKey && ["+", "="].includes(event.key) && readerState.phase === "ready") {
        event.preventDefault();
        updateReaderSettings({ fontSize: Math.min(48, readerState.data.settings.fontSize + 1) });
      } else if (!event.ctrlKey && !event.altKey && event.key === "-" && readerState.phase === "ready") {
        event.preventDefault();
        updateReaderSettings({ fontSize: Math.max(10, readerState.data.settings.fontSize - 1) });
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [readerState, windowControls, nativeFloatingState]);
  return (
    <div className={`prototype-stage ${desktopMode ? "desktop-host" : ""} ${floating && bridgeMode === "demo" ? "demo-floating-active" : ""} theme-${appPreferences.colorScheme}`} data-theme={appPreferences.theme} data-window-mode={windowState.isFullScreen ? "fullscreen" : windowState.isMaximized ? "maximized" : "normal"}>
      {desktopMode ? <WindowResizeHandles controls={windowControls} /> : null}
      <div className="mac-window">
        <WindowTitlebar controls={windowControls} desktopMode={desktopMode} windowState={windowState} />
        <div className="app-body">
          <Rail page={page} setPage={navigatePage} readerEnabled={readerEnabled} audioEnabled={bridgeMode === "demo" || capabilities.audioImport} darkMode={appPreferences.colorScheme === "dark"} onToggleDark={toggleDarkMode} onOpenSettings={() => setSettingsOpen(true)} />
          <main className="content-area">
            {page === "reader" && bridgeMode === "demo"
              ? <DemoReader setPage={setPage} fontSize={fontSize} setFontSize={setFontSize} playing={playing} setPlaying={setPlaying} floating={floating} setFloating={setFloating} networkNotice={networkNotice} />
              : page === "reader" && bridgeMode === "native"
                ? <NativeReader state={readerState} networkNotice={networkNotice} selectedStart={selectedReaderStart} onChooseStart={chooseReaderStart} onBack={() => setPage("library")} onNavigate={navigateReader} onGetWindow={getReaderWindow} onUpdatePosition={updateReaderPosition} onSearch={searchReader} onLoadBookmarks={loadReaderBookmarks} onAddBookmark={addReaderBookmark} onRemoveBookmark={removeReaderBookmark} onCommand={controlReaderPlayback} onSettings={updateReaderSettings} floatingAvailable={capabilities.floatingReader} floatingVisible={Boolean(nativeFloatingState?.visible)} onFloatingToggle={switchToFloatingReader} onOpenSettings={() => setSettingsOpen(true)} />
                : <Library books={books} error={bridgeError} loading={libraryLoading} openBook={openBook} removeBook={removeBook} openPaste={() => setPasteOpen(true)} selectFiles={selectFiles} showUnavailable={showUnavailable} capabilities={effectiveCapabilities} readerEnabled={readerEnabled} importState={importState} cancelImport={cancelImport} openAfterImportBookId={openAfterImportBookId} />}
          </main>
        </div>
      </div>
      {floating && bridgeMode === "demo" ? <DemoFloatingReader playing={playing} setPlaying={setPlaying} onClose={() => setFloating(false)} onReturnToMain={() => setFloating(false)} /> : null}
      {pasteOpen && <PasteModal onClose={() => setPasteOpen(false)} onImport={startPasteImport} demoMode={bridgeMode === "demo"} />}
      {importSelection && <ImportConfirmationModal selection={importSelection} onClose={() => { setImportSelection(null); setImportState({ ...EMPTY_IMPORT_STATE }); }} onStart={startFileImport} />}
      {settingsOpen && <SettingsModal preferences={appPreferences} speech={speechState} floatingSettings={nativeFloatingState?.settings || EMPTY_FLOATING_STATE.settings} version={appVersion} softwareUpdate={softwareUpdate} pending={settingsPending} onUpdateApp={updateAppPreferences} onUpdateSpeech={updateSpeechPreferences} onUpdateFloating={updateFloatingPreferences} onCheckUpdate={checkForUpdates} onDownloadUpdate={downloadUpdate} onSkipUpdate={skipUpdate} onInstallUpdate={installUpdate} onOpenUpdatePage={openUpdatePage} onClose={() => setSettingsOpen(false)} />}
      {updatePromptVersion && softwareUpdate.latestVersion === updatePromptVersion ? <UpdateAvailableModal update={softwareUpdate} onDownload={downloadUpdate} onSkip={skipUpdate} onOpenRelease={() => openUpdatePage("release")} onClose={dismissUpdatePrompt} /> : null}
    </div>
  );
}

export function App() {
  const surface = new URLSearchParams(window.location.search).get("surface");
  return surface === "floating" ? <FloatingApplication /> : <MainApplication />;
}
