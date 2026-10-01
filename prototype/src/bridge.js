export const SCHEMA_VERSION = 2;

const DEMO_BOOKS = [
  { id: "demo-1", title: "高效能人士的七个习惯", author: "", format: "EPUB", progressPercent: 36, chapterIndex: 2, chapterCount: 12, currentChapterTitle: "第 3 章 · 要事第一", lastReadAt: null, totalChars: 0, coverUrl: "covers/library-indigo.jpg" },
  { id: "demo-2", title: "创意是一种习惯", author: "", format: "EPUB", progressPercent: 68, chapterIndex: 7, chapterCount: 10, currentChapterTitle: "第 8 章 · 保持好奇", lastReadAt: null, totalChars: 0, coverUrl: "covers/library-sage.jpg" },
  { id: "demo-3", title: "财富自由之路", author: "", format: "EPUB", progressPercent: 52, chapterIndex: 5, chapterCount: 9, currentChapterTitle: "第 6 章 · 运气的成分", lastReadAt: null, totalChars: 0, coverUrl: "covers/library-amber.jpg" },
  { id: "demo-4", title: "星火", author: "", format: "EPUB", progressPercent: 12, chapterIndex: 0, chapterCount: 8, currentChapterTitle: "序章 · 启程", lastReadAt: null, totalChars: 0, coverUrl: "covers/library-night.jpg" },
];

const DEMO_READER_TEXT = "每年300万美元在大多数人眼里是一笔大钱，但是在另一些人眼里却不值一提。\n财富并不只是一串数字，它更像一种选择权：你能决定把时间留给谁，也能决定拒绝什么。\n创造财富的法则，往往只是代表了财富创造的方式。";

function demoReaderSettings() {
  return { fontFamily: "Songti SC", fontSize: 21, lineSpacing: 2, paragraphMode: 1, firstLineIndent: false, ttsRate: 200, ttsVoiceId: "demo", volume: 100, sentenceGapSeconds: 0.1 };
}

function demoPlayback(position = { chapterIndex: 0, charOffset: 0, progressPercent: 0 }, status = "idle") {
  return { status, position, sentence: null, requestedBackend: "sapi", activeBackend: status === "idle" ? null : "sapi", fallbackActive: false };
}

function demoFloatingState(visible = false, playback = demoPlayback()) {
  return {
    visible,
    sessionId: "demo-reader-session",
    bookId: "demo-3",
    settings: { geometry: "", topmost: true, backgroundOpacity: 0.94, fontSize: 20, followReaderFont: true, background: "light", bilingual: false, textColor: "auto", hoverDisplayEnabled: true },
    playback,
    context: {
      chapterIndex: 0,
      chapterTitle: "第六章　运气的成分",
      previous: { chapterIndex: 0, startOffset: 0, endOffset: 25, text: "创造财富的法则，往往只是代表了财富创造的方式。" },
      current: { chapterIndex: 0, startOffset: 26, endOffset: 65, text: "每年300万美元在大多数人眼里是一笔大钱，但是在另一些人眼里却不值一提。" },
      next: { chapterIndex: 0, startOffset: 66, endOffset: 76, text: "300万美元算什么？" },
    },
  };
}

function demoReaderWindow(sessionId, bookId, anchorOffset = 0) {
  let offset = 0;
  const blocks = DEMO_READER_TEXT.split("\n").map((text, index) => {
    const block = { id: `0:${offset}:${offset + text.length}`, startOffset: offset, endOffset: offset + text.length, text, startsParagraph: true, endsParagraph: true };
    offset += text.length + (index < 2 ? 1 : 0);
    return block;
  });
  return { sessionId, bookId, chapterIndex: 0, chapterTitle: "第六章　运气的成分", chapterCharCount: DEMO_READER_TEXT.length, anchorOffset, windowStartOffset: 0, windowEndOffset: DEMO_READER_TEXT.length, hasBefore: false, hasAfter: false, blocks };
}

const EMPTY_DATA = {
  app: { version: "2.1.1" },
  library: { books: [], total: 0, sortMode: "recent" },
  preferences: { theme: "护眼", colorScheme: "light", autoOpenLast: true, closeToTray: false, autoCheckUpdates: true, startupBookId: "" },
  window: { isMaximized: false, isFullScreen: false },
  speech: {
    settings: { ttsRate: 200, ttsVoiceId: "", sentenceGapSeconds: 0.1 },
    voices: [
      { id: "", label: "系统默认音色", backend: "sapi", requiresNetwork: false },
      { id: "zh-CN-XiaoxiaoNeural", label: "晓晓·女声·温柔", backend: "edge", requiresNetwork: true },
    ],
    loadingLocalVoices: false,
    localVoiceError: "",
  },
  softwareUpdate: {
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
  },
  capabilities: {
    fileImport: false,
    pasteImport: false,
    webImport: false,
    audioImport: false,
    reader: false,
    tts: false,
    floatingReader: false,
  },
};

const CAPABILITY_KEYS = Object.keys(EMPTY_DATA.capabilities);
const BOOK_FIELDS = {
  id: "string",
  title: "string",
  author: "string",
  format: "string",
  progressPercent: "number",
  chapterIndex: "number",
  chapterCount: "number",
  currentChapterTitle: "string",
  totalChars: "number",
  coverUrl: "string",
};

const DUPLICATE_MODES = new Set(["cancel", "overwrite", "reparse"]);
const PLAYBACK_STATUSES = new Set(["idle", "playing", "paused", "finished", "error"]);
const PLAYBACK_COMMANDS = new Set(["play", "pause", "stop", "previousSentence", "nextSentence"]);
const PLAYBACK_REASONS = new Set(["state", "sentenceStart", "sentenceDone", "buffering", "finished", "fallback", "recovered", "error"]);
const FLOATING_BACKGROUNDS = new Set(["light", "sepia", "dark"]);
const APP_THEMES = new Set(["白天", "护眼", "夜间", "米黄"]);
const SOFTWARE_UPDATE_STATUSES = new Set(["idle", "checking", "upToDate", "available", "skipped", "downloading", "ready", "installing", "error"]);
const WINDOW_RESIZE_EDGES = new Set(["top", "right", "bottom", "left", "topRight", "bottomRight", "bottomLeft", "topLeft"]);
const FLOATING_SETTING_FIELDS = {
  topmost: "boolean",
  backgroundOpacity: "number",
  fontSize: "number",
  followReaderFont: "boolean",
  background: "string",
  bilingual: "boolean",
  textColor: "string",
  hoverDisplayEnabled: "boolean",
};
const READER_SETTING_FIELDS = {
  fontFamily: "string",
  fontSize: "number",
  lineSpacing: "number",
  paragraphMode: "number",
  firstLineIndent: "boolean",
  ttsRate: "number",
  ttsVoiceId: "string",
  volume: "number",
  sentenceGapSeconds: "number",
};

function validBridgeError(error) {
  return error === null || Boolean(
    error
    && typeof error.code === "string"
    && typeof error.message === "string"
    && typeof error.retryable === "boolean",
  );
}

function validBook(book) {
  return Boolean(
    book
    && Object.entries(BOOK_FIELDS).every(([field, type]) => typeof book[field] === type)
    && (book.lastReadAt === null || typeof book.lastReadAt === "number")
    && (book.canRevealSource === undefined || typeof book.canRevealSource === "boolean"),
  );
}

function validAppPreferences(preferences) {
  return Boolean(
    preferences
    && APP_THEMES.has(preferences.theme)
    && ["light", "dark"].includes(preferences.colorScheme)
    && (preferences.colorScheme === "dark") === (preferences.theme === "夜间")
    && typeof preferences.autoOpenLast === "boolean"
    && typeof preferences.closeToTray === "boolean"
    && typeof preferences.autoCheckUpdates === "boolean"
    && typeof preferences.startupBookId === "string",
  );
}

function validSoftwareUpdateState(state) {
  return Boolean(
    state
    && SOFTWARE_UPDATE_STATUSES.has(state.status)
    && typeof state.currentVersion === "string"
    && typeof state.latestVersion === "string"
    && typeof state.lastCheckedAt === "string"
    && typeof state.message === "string"
    && typeof state.releaseUrl === "string"
    && typeof state.publishedAt === "string"
    && typeof state.releaseNotes === "string"
    && state.releaseNotes.length <= 12_000
    && nonNegativeNumber(state.progressPercent)
    && state.progressPercent <= 100
    && nonNegativeNumber(state.downloadedBytes)
    && nonNegativeNumber(state.totalBytes)
    && typeof state.canDownload === "boolean"
    && typeof state.canInstall === "boolean",
  );
}

function validSpeechState(state) {
  return Boolean(
    state
    && state.settings
    && typeof state.settings.ttsVoiceId === "string"
    && Number.isInteger(state.settings.ttsRate)
    && state.settings.ttsRate >= 80 && state.settings.ttsRate <= 400
    && nonNegativeNumber(state.settings.sentenceGapSeconds)
    && state.settings.sentenceGapSeconds <= 1
    && Array.isArray(state.voices)
    && state.voices.every((voice) => (
      voice
      && typeof voice.id === "string"
      && typeof voice.label === "string"
      && ["sapi", "edge"].includes(voice.backend)
      && typeof voice.requiresNetwork === "boolean"
    ))
    && typeof state.loadingLocalVoices === "boolean"
    && typeof state.localVoiceError === "string",
  );
}

function validWindowStateEvent(event) {
  return Boolean(
    event
    && event.schemaVersion === SCHEMA_VERSION
    && typeof event.isMaximized === "boolean"
    && typeof event.isFullScreen === "boolean",
  );
}

function parseJsonPayload(raw, invalidMessage) {
  try {
    return typeof raw === "string" ? JSON.parse(raw) : raw;
  } catch {
    throw new BridgeProtocolError(invalidMessage, "BRIDGE_INVALID_JSON");
  }
}

function parseBridgeResponse(raw, validateData) {
  const payload = parseJsonPayload(raw, "桌面通信返回了无法解析的数据。");
  if (!payload || payload.schemaVersion !== SCHEMA_VERSION) {
    throw new BridgeProtocolError("桌面程序与界面版本不兼容，请更新后重试。", "SCHEMA_MISMATCH");
  }
  if (typeof payload.ok !== "boolean" || !validBridgeError(payload.error)) {
    throw new BridgeProtocolError("桌面通信返回的数据结构不完整。", "BRIDGE_INVALID_PAYLOAD");
  }
  if (!payload.ok) {
    if (!payload.error) {
      throw new BridgeProtocolError("桌面通信返回的数据结构不完整。", "BRIDGE_INVALID_PAYLOAD");
    }
    throw new BridgeProtocolError(
      payload.error?.message || "桌面操作失败。",
      payload.error?.code || "BRIDGE_REQUEST_FAILED",
    );
  }
  if (payload.error !== null || !validateData(payload.data)) {
    throw new BridgeProtocolError("桌面通信返回的数据结构不完整。", "BRIDGE_INVALID_PAYLOAD");
  }
  return payload;
}

const NOOP_CONTROLS = Object.freeze({
  minimizeWindow() {},
  toggleMaximizeWindow() {},
  toggleFullscreen() {},
  closeWindow() {},
  startWindowMove() {},
  startWindowResize() {},
});

export class BridgeProtocolError extends Error {
  constructor(message, code = "BRIDGE_PROTOCOL_ERROR", initialData = EMPTY_DATA) {
    super(message);
    this.name = "BridgeProtocolError";
    this.code = code;
    this.initialData = initialData;
  }
}

export function createDemoInitialState() {
  return {
    schemaVersion: SCHEMA_VERSION,
    ok: true,
    data: {
      ...EMPTY_DATA,
      library: { books: DEMO_BOOKS.map((book) => ({ ...book, canRevealSource: false })), total: DEMO_BOOKS.length, sortMode: "recent" },
    },
    error: null,
  };
}

export function parseInitialState(raw) {
  const payload = parseJsonPayload(raw, "桌面通信返回了无法解析的数据。");

  if (!payload || payload.schemaVersion !== SCHEMA_VERSION) {
    throw new BridgeProtocolError("桌面程序与界面版本不兼容，请更新后重试。", "SCHEMA_MISMATCH");
  }
  const books = payload?.data?.library?.books;
  const capabilities = payload?.data?.capabilities;
  const validBooks = Array.isArray(books) && books.every(validBook);
  const validCapabilities = capabilities
    && CAPABILITY_KEYS.every((key) => typeof capabilities[key] === "boolean");
  if (
    typeof payload.ok !== "boolean"
    || !validBridgeError(payload.error)
    || !validBooks
    || typeof payload.data?.app?.version !== "string"
    || !validAppPreferences(payload.data?.preferences)
    || typeof payload.data.library.total !== "number"
    || (payload.data.library.sortMode !== undefined && !["recent", "manual"].includes(payload.data.library.sortMode))
    || typeof payload.data?.window?.isMaximized !== "boolean"
    || typeof payload.data?.window?.isFullScreen !== "boolean"
    || !validSpeechState(payload.data?.speech)
    || !validSoftwareUpdateState(payload.data?.softwareUpdate)
    || !validCapabilities
  ) {
    throw new BridgeProtocolError("桌面通信返回的数据结构不完整。", "BRIDGE_INVALID_PAYLOAD");
  }
  if (!payload.ok) {
    throw new BridgeProtocolError(
      payload.error?.message || "桌面程序暂时无法读取内容库。",
      payload.error?.code || "BRIDGE_REQUEST_FAILED",
      payload.data,
    );
  }
  return payload;
}

function nonNegativeNumber(value) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function nonNegativeInteger(value) {
  return nonNegativeNumber(value) && Number.isInteger(value);
}

function validImportSelection(data) {
  return Boolean(
    data
    && typeof data.cancelled === "boolean"
    && typeof data.selectionId === "string"
    && nonNegativeNumber(data.total)
    && nonNegativeNumber(data.duplicateCount)
    && nonNegativeNumber(data.largeFileCount)
    && Array.isArray(data.items)
    && data.items.length === data.total
    && data.items.every((item) => (
      item
      && typeof item.itemId === "string"
      && typeof item.name === "string"
      && typeof item.format === "string"
      && nonNegativeNumber(item.sizeBytes)
      && typeof item.supported === "boolean"
      && typeof item.large === "boolean"
      && item.duplicate
      && typeof item.duplicate.exists === "boolean"
      && typeof item.duplicate.bookId === "string"
      && typeof item.duplicate.title === "string"
    )),
  );
}

function validImportStart(data) {
  return Boolean(data && typeof data.jobId === "string" && data.jobId && data.state === "queued");
}

function validImportCancel(data) {
  return Boolean(data && typeof data.jobId === "string" && typeof data.cancelRequested === "boolean");
}

function validImportProgress(event) {
  return Boolean(
    event
    && event.schemaVersion === SCHEMA_VERSION
    && typeof event.jobId === "string"
    && event.phase === "item"
    && nonNegativeNumber(event.completed)
    && nonNegativeNumber(event.total)
    && nonNegativeNumber(event.succeeded)
    && nonNegativeNumber(event.failed)
    && event.item
    && nonNegativeNumber(event.item.index)
    && typeof event.item.name === "string"
    && ["running", "succeeded", "failed"].includes(event.item.status)
    && typeof event.item.bookId === "string"
    && validBridgeError(event.error),
  );
}

function validImportFinished(event) {
  return Boolean(
    event
    && event.schemaVersion === SCHEMA_VERSION
    && typeof event.jobId === "string"
    && ["completed", "cancelled"].includes(event.state)
    && nonNegativeNumber(event.total)
    && nonNegativeNumber(event.processed)
    && nonNegativeNumber(event.succeeded)
    && nonNegativeNumber(event.failed)
    && typeof event.lastImportedBookId === "string"
    && typeof event.openAfterImportBookId === "string"
    && Array.isArray(event.results)
    && event.results.every((item) => (
      item
      && typeof item.name === "string"
      && ["succeeded", "failed"].includes(item.status)
      && typeof item.bookId === "string"
      && validBridgeError(item.error)
    )),
  );
}

function validReaderPosition(position) {
  return Boolean(
    position
    && nonNegativeInteger(position.chapterIndex)
    && nonNegativeInteger(position.charOffset)
    && nonNegativeNumber(position.progressPercent)
    && position.progressPercent <= 100,
  );
}

function validReaderWindow(data) {
  const blocksValid = Array.isArray(data?.blocks)
    && data.blocks.length <= 120
    && data.blocks.every((block, index) => (
      block
      && typeof block.id === "string" && block.id
      && nonNegativeInteger(block.startOffset)
      && nonNegativeInteger(block.endOffset)
      && block.startOffset <= block.endOffset
      && block.startOffset >= data.windowStartOffset
      && block.endOffset <= data.windowEndOffset
      && (index === 0 || data.blocks[index - 1].endOffset <= block.startOffset)
      && typeof block.text === "string"
      && typeof block.startsParagraph === "boolean"
      && typeof block.endsParagraph === "boolean"
    ));
  return Boolean(
    data
    && typeof data.sessionId === "string" && data.sessionId
    && typeof data.bookId === "string" && data.bookId
    && nonNegativeInteger(data.chapterIndex)
    && typeof data.chapterTitle === "string"
    && nonNegativeInteger(data.chapterCharCount)
    && nonNegativeInteger(data.anchorOffset)
    && nonNegativeInteger(data.windowStartOffset)
    && nonNegativeInteger(data.windowEndOffset)
    && data.windowStartOffset <= data.windowEndOffset
    && data.windowEndOffset <= data.chapterCharCount
    && data.anchorOffset <= data.chapterCharCount
    && typeof data.hasBefore === "boolean"
    && typeof data.hasAfter === "boolean"
    && blocksValid,
  );
}

function validReaderSettings(settings) {
  return Boolean(
    settings
    && Object.entries(READER_SETTING_FIELDS).every(([field, type]) => typeof settings[field] === type)
    && [1, 2, 3].includes(settings.paragraphMode),
  );
}

function validReaderSentence(sentence) {
  return sentence === null || Boolean(
    sentence
    && nonNegativeInteger(sentence.chapterIndex)
    && nonNegativeInteger(sentence.startOffset)
    && nonNegativeInteger(sentence.endOffset)
    && sentence.startOffset <= sentence.endOffset
    && typeof sentence.text === "string",
  );
}

function validReaderPlayback(playback) {
  return Boolean(
    playback
    && PLAYBACK_STATUSES.has(playback.status)
    && validReaderPosition(playback.position)
    && validReaderSentence(playback.sentence)
    && ["sapi", "edge"].includes(playback.requestedBackend)
    && (playback.activeBackend === null || ["sapi", "edge"].includes(playback.activeBackend))
    && typeof playback.fallbackActive === "boolean",
  );
}

function validFloatingSettings(settings) {
  return Boolean(
    settings
    && typeof settings.geometry === "string"
    && typeof settings.topmost === "boolean"
    && nonNegativeNumber(settings.backgroundOpacity) && settings.backgroundOpacity <= 1
    && nonNegativeNumber(settings.fontSize) && settings.fontSize >= 14 && settings.fontSize <= 40
    && typeof settings.followReaderFont === "boolean"
    && FLOATING_BACKGROUNDS.has(settings.background)
    && typeof settings.bilingual === "boolean"
    && typeof settings.hoverDisplayEnabled === "boolean"
    && (settings.textColor === "auto" || /^#[0-9A-Fa-f]{6}$/.test(settings.textColor)),
  );
}

function validSpeechChangedEvent(event) {
  return Boolean(event && event.schemaVersion === SCHEMA_VERSION && validSpeechState(event.state));
}

function validFloatingState(data) {
  return Boolean(
    data
    && typeof data.visible === "boolean"
    && typeof data.sessionId === "string"
    && typeof data.bookId === "string"
    && validFloatingSettings(data.settings)
    && validReaderPlayback(data.playback)
    && data.context
    && nonNegativeInteger(data.context.chapterIndex)
    && typeof data.context.chapterTitle === "string"
    && validReaderSentence(data.context.previous)
    && validReaderSentence(data.context.current)
    && validReaderSentence(data.context.next),
  );
}

function validFloatingChangedEvent(event) {
  return Boolean(event && event.schemaVersion === SCHEMA_VERSION && validFloatingState(event.state));
}

function validFloatingClose(data) {
  return Boolean(data && typeof data.closed === "boolean");
}

function validReaderOpenData(data) {
  return Boolean(
    data
    && typeof data.sessionId === "string" && data.sessionId
    && data.book
    && typeof data.book.id === "string" && data.book.id
    && typeof data.book.title === "string"
    && typeof data.book.author === "string"
    && typeof data.book.format === "string"
    && nonNegativeInteger(data.book.totalChars)
    && Array.isArray(data.book.chapters)
    && data.book.chapters.every((chapter) => (
      chapter
      && nonNegativeInteger(chapter.index)
      && typeof chapter.title === "string"
      && nonNegativeInteger(chapter.charCount)
    ))
    && validReaderPosition(data.position)
    && validReaderWindow(data.window)
    && data.window.sessionId === data.sessionId
    && data.window.bookId === data.book.id
    && validReaderSettings(data.settings)
    && validReaderPlayback(data.playback)
    && nonNegativeNumber(data.bookmarkCount),
  );
}

function validReaderOpenStart(data) {
  return Boolean(data && typeof data.requestId === "string" && data.requestId && typeof data.bookId === "string" && data.bookId && data.state === "loading");
}

function validReaderOpenedEvent(event) {
  return Boolean(
    event
    && event.schemaVersion === SCHEMA_VERSION
    && typeof event.requestId === "string" && event.requestId
    && typeof event.bookId === "string" && event.bookId
    && typeof event.ok === "boolean"
    && validBridgeError(event.error)
    && (event.ok ? validReaderOpenData(event.data) && event.error === null : event.data === null && event.error !== null),
  );
}

function validReaderNavigate(data) {
  return Boolean(data && validReaderPosition(data.position) && validReaderWindow(data.window) && validReaderPlayback(data.playback));
}

function validReaderPositionUpdate(data) {
  return Boolean(data && typeof data.updated === "boolean" && validReaderPosition(data.position));
}

function validReaderSearchResult(item) {
  return Boolean(
    item
    && typeof item.id === "string" && item.id
    && nonNegativeInteger(item.chapterIndex)
    && typeof item.chapterTitle === "string"
    && nonNegativeInteger(item.startOffset)
    && nonNegativeInteger(item.endOffset)
    && item.startOffset <= item.endOffset
    && nonNegativeInteger(item.excerptStartOffset)
    && typeof item.excerpt === "string",
  );
}

function validReaderSearchPage(data) {
  return Boolean(data && typeof data.query === "string" && nonNegativeInteger(data.total) && typeof data.nextCursor === "string" && Array.isArray(data.results) && data.results.length <= data.total && data.results.every(validReaderSearchResult));
}

function validReaderSearchStart(data) {
  return Boolean(data && typeof data.requestId === "string" && data.requestId && data.state === "searching");
}

function validReaderSearchFinished(event) {
  return Boolean(
    event
    && event.schemaVersion === SCHEMA_VERSION
    && typeof event.requestId === "string" && event.requestId
    && typeof event.sessionId === "string" && event.sessionId
    && typeof event.ok === "boolean"
    && validBridgeError(event.error)
    && (event.ok ? validReaderSearchPage(event.data) && event.error === null : event.data === null && event.error !== null),
  );
}

function validReaderBookmark(item) {
  return Boolean(
    item
    && typeof item.id === "string" && item.id
    && nonNegativeInteger(item.chapterIndex)
    && typeof item.chapterTitle === "string"
    && nonNegativeInteger(item.startOffset)
    && nonNegativeInteger(item.endOffset)
    && item.startOffset <= item.endOffset
    && typeof item.text === "string"
    && typeof item.note === "string"
    && nonNegativeNumber(item.createdAt),
  );
}

function validReaderBookmarkPage(data) {
  return Boolean(data && nonNegativeInteger(data.total) && typeof data.nextCursor === "string" && Array.isArray(data.items) && data.items.length <= data.total && data.items.every(validReaderBookmark));
}

function validReaderBookmarkRemove(data) {
  return Boolean(data && typeof data.bookmarkId === "string" && typeof data.removed === "boolean");
}

function validLibraryRemove(data) {
  return Boolean(data && typeof data.bookId === "string" && data.bookId && data.removed === true);
}

function validLibraryState(data) {
  return Boolean(data && Array.isArray(data.books) && data.books.every(validBook)
    && nonNegativeInteger(data.total) && data.total === data.books.length
    && ["recent", "manual"].includes(data.sortMode));
}

function validSourceReveal(data) {
  return Boolean(data && typeof data.bookId === "string" && data.bookId && data.opened === true);
}

function validReaderPlaybackCommand(data) {
  return Boolean(data && typeof data.commandId === "string" && data.commandId && typeof data.accepted === "boolean");
}

function validReaderPlaybackEvent(event) {
  return Boolean(
    event
    && event.schemaVersion === SCHEMA_VERSION
    && typeof event.sessionId === "string" && event.sessionId
    && typeof event.bookId === "string" && event.bookId
    && nonNegativeNumber(event.sequence)
    && typeof event.commandId === "string"
    && PLAYBACK_REASONS.has(event.reason)
    && validReaderPlayback(event.playback)
    && validBridgeError(event.error),
  );
}

function parseImportEvent(raw, validate, message) {
  const event = parseJsonPayload(raw, message);
  if (!validate(event)) {
    throw new BridgeProtocolError(message, "BRIDGE_INVALID_PAYLOAD");
  }
  return event;
}

function loadQWebChannel(browserWindow, browserDocument) {
  if (typeof browserWindow.QWebChannel === "function") return Promise.resolve();
  if (!browserDocument) {
    return Promise.reject(new BridgeProtocolError("无法加载桌面通信组件。", "QWEBCHANNEL_UNAVAILABLE"));
  }

  const existing = browserDocument.querySelector('script[data-dd-qwebchannel="true"]');
  if (existing) {
    return new Promise((resolve, reject) => {
      existing.addEventListener("load", resolve, { once: true });
      existing.addEventListener("error", () => reject(new BridgeProtocolError("桌面通信组件加载失败。", "QWEBCHANNEL_LOAD_FAILED")), { once: true });
    });
  }

  return new Promise((resolve, reject) => {
    const script = browserDocument.createElement("script");
    script.src = "qrc:///qtwebchannel/qwebchannel.js";
    script.dataset.ddQwebchannel = "true";
    script.addEventListener("load", resolve, { once: true });
    script.addEventListener("error", () => reject(new BridgeProtocolError("桌面通信组件加载失败。", "QWEBCHANNEL_LOAD_FAILED")), { once: true });
    browserDocument.head.appendChild(script);
  });
}

function createNativeChannel(browserWindow) {
  return new Promise((resolve, reject) => {
    try {
      new browserWindow.QWebChannel(browserWindow.qt.webChannelTransport, (channel) => resolve(channel));
    } catch {
      reject(new BridgeProtocolError("无法连接桌面程序。", "QWEBCHANNEL_CONNECT_FAILED"));
    }
  });
}

function invokeWithResult(nativeBridge, method, args = []) {
  return new Promise((resolve, reject) => {
    if (typeof nativeBridge?.[method] !== "function") {
      reject(new BridgeProtocolError("桌面通信接口不完整。", "BRIDGE_METHOD_MISSING"));
      return;
    }
    try {
      nativeBridge[method](...args, (result) => resolve(result));
    } catch {
      reject(new BridgeProtocolError("桌面通信调用失败。", "BRIDGE_CALL_FAILED"));
    }
  });
}

function nativeImports(nativeBridge) {
  return {
    async selectFiles() {
      return parseBridgeResponse(
        await invokeWithResult(nativeBridge, "selectImportFiles"),
        validImportSelection,
      );
    },
    async startFileImport(input) {
      if (
        !input
        || typeof input.selectionId !== "string"
        || typeof input.confirmLargeFiles !== "boolean"
        || !DUPLICATE_MODES.has(input.duplicateMode)
      ) {
        throw new BridgeProtocolError("文件导入参数无效。", "BRIDGE_INVALID_ARGUMENT");
      }
      return parseBridgeResponse(
        await invokeWithResult(nativeBridge, "startFileImport", [JSON.stringify(input)]),
        validImportStart,
      );
    },
    async startPasteImport(input) {
      if (!input || typeof input.title !== "string" || typeof input.text !== "string") {
        throw new BridgeProtocolError("粘贴文本参数无效。", "BRIDGE_INVALID_ARGUMENT");
      }
      return parseBridgeResponse(
        await invokeWithResult(nativeBridge, "startPasteImport", [JSON.stringify(input)]),
        validImportStart,
      );
    },
    async cancelImport(jobId) {
      if (typeof jobId !== "string" || !jobId) {
        throw new BridgeProtocolError("导入任务编号无效。", "BRIDGE_INVALID_ARGUMENT");
      }
      return parseBridgeResponse(
        await invokeWithResult(nativeBridge, "cancelImport", [jobId]),
        validImportCancel,
      );
    },
  };
}

function validSessionInput(input) {
  return Boolean(input && typeof input.sessionId === "string" && input.sessionId);
}

function invokeReader(nativeBridge, method, input, validateData) {
  return invokeWithResult(nativeBridge, method, [JSON.stringify(input)])
    .then((raw) => parseBridgeResponse(raw, validateData));
}

function nativeReader(nativeBridge) {
  return {
    async openBook(bookId) {
      if (typeof bookId !== "string" || !bookId) throw new BridgeProtocolError("书籍编号无效。", "BRIDGE_INVALID_ARGUMENT");
      return parseBridgeResponse(await invokeWithResult(nativeBridge, "openReaderBook", [bookId]), validReaderOpenStart);
    },
    async getWindow(input) {
      if (!validSessionInput(input) || !nonNegativeNumber(input.chapterIndex) || !nonNegativeNumber(input.anchorOffset)) throw new BridgeProtocolError("正文窗口参数无效。", "BRIDGE_INVALID_ARGUMENT");
      return invokeReader(nativeBridge, "getReaderWindow", input, validReaderWindow);
    },
    async navigate(input) {
      const target = input?.target;
      const validTarget = target?.kind === "position"
        ? nonNegativeNumber(target.chapterIndex) && nonNegativeNumber(target.charOffset)
        : target?.kind === "percent" && nonNegativeNumber(target.percent) && target.percent <= 100;
      if (!validSessionInput(input) || !validTarget) throw new BridgeProtocolError("阅读跳转参数无效。", "BRIDGE_INVALID_ARGUMENT");
      return invokeReader(nativeBridge, "navigateReader", input, validReaderNavigate);
    },
    async updatePosition(input) {
      if (!validSessionInput(input) || !nonNegativeNumber(input.chapterIndex) || !nonNegativeNumber(input.charOffset)) throw new BridgeProtocolError("阅读进度参数无效。", "BRIDGE_INVALID_ARGUMENT");
      return invokeReader(nativeBridge, "updateReaderPosition", input, validReaderPositionUpdate);
    },
    async search(input) {
      if (!validSessionInput(input) || typeof input.query !== "string" || typeof input.cursor !== "string") throw new BridgeProtocolError("书内搜索参数无效。", "BRIDGE_INVALID_ARGUMENT");
      return invokeReader(nativeBridge, "searchReader", input, validReaderSearchStart);
    },
    async listBookmarks(input) {
      if (!validSessionInput(input) || typeof input.cursor !== "string") throw new BridgeProtocolError("书签查询参数无效。", "BRIDGE_INVALID_ARGUMENT");
      return invokeReader(nativeBridge, "listReaderBookmarks", input, validReaderBookmarkPage);
    },
    async addBookmark(input) {
      if (!validSessionInput(input) || !nonNegativeNumber(input.chapterIndex) || !nonNegativeNumber(input.startOffset) || !nonNegativeNumber(input.endOffset) || input.startOffset > input.endOffset || typeof input.note !== "string") throw new BridgeProtocolError("书签参数无效。", "BRIDGE_INVALID_ARGUMENT");
      return invokeReader(nativeBridge, "addReaderBookmark", input, validReaderBookmark);
    },
    async removeBookmark(input) {
      if (!validSessionInput(input) || typeof input.bookmarkId !== "string" || !input.bookmarkId) throw new BridgeProtocolError("书签删除参数无效。", "BRIDGE_INVALID_ARGUMENT");
      return invokeReader(nativeBridge, "removeReaderBookmark", input, validReaderBookmarkRemove);
    },
    async controlPlayback(input) {
      if (!validSessionInput(input) || !PLAYBACK_COMMANDS.has(input.command)) throw new BridgeProtocolError("播放控制参数无效。", "BRIDGE_INVALID_ARGUMENT");
      return invokeReader(nativeBridge, "controlReaderPlayback", input, validReaderPlaybackCommand);
    },
    async updateSettings(input) {
      const patch = input?.patch;
      const validPatch = patch && Object.entries(patch).every(([field, value]) => READER_SETTING_FIELDS[field] === typeof value);
      if (!validSessionInput(input) || !validPatch || ("paragraphMode" in patch && ![1, 2, 3].includes(patch.paragraphMode))) throw new BridgeProtocolError("阅读设置参数无效。", "BRIDGE_INVALID_ARGUMENT");
      return invokeReader(nativeBridge, "updateReaderSettings", input, validReaderSettings);
    },
  };
}

function nativeFloating(nativeBridge) {
  return {
    async getState() {
      return parseBridgeResponse(await invokeWithResult(nativeBridge, "getFloatingReaderState"), validFloatingState);
    },
    async show() {
      return parseBridgeResponse(await invokeWithResult(nativeBridge, "showFloatingReader"), validFloatingState);
    },
    async close() {
      return parseBridgeResponse(await invokeWithResult(nativeBridge, "closeFloatingReader"), validFloatingClose);
    },
    async returnToMain() {
      return parseBridgeResponse(await invokeWithResult(nativeBridge, "returnToMainWindow"), validFloatingClose);
    },
    async updateSettings(input) {
      const patch = input?.patch;
      const validPatch = patch
        && !Array.isArray(patch)
        && Object.entries(patch).every(([field, value]) => (
          FLOATING_SETTING_FIELDS[field] === typeof value
          && (field !== "backgroundOpacity" || nonNegativeNumber(value) && value <= 1)
          && (field !== "fontSize" || nonNegativeNumber(value) && value >= 14 && value <= 40)
          && (field !== "background" || FLOATING_BACKGROUNDS.has(value))
          && (field !== "textColor" || value === "auto" || /^#[0-9A-Fa-f]{6}$/.test(value))
        ));
      if (!validPatch) throw new BridgeProtocolError("悬浮朗读设置参数无效。", "BRIDGE_INVALID_ARGUMENT");
      return parseBridgeResponse(
        await invokeWithResult(nativeBridge, "updateFloatingReaderSettings", [JSON.stringify(input)]),
        validFloatingState,
      );
    },
    startWindowMove() {
      if (typeof nativeBridge?.startFloatingWindowMove !== "function") throw new BridgeProtocolError("桌面通信接口不完整。", "BRIDGE_METHOD_MISSING");
      nativeBridge.startFloatingWindowMove();
    },
    startWindowResize(edge) {
      if (!WINDOW_RESIZE_EDGES.has(edge)) throw new BridgeProtocolError("悬浮窗缩放方向无效。", "BRIDGE_INVALID_ARGUMENT");
      if (typeof nativeBridge?.startFloatingWindowResize !== "function") throw new BridgeProtocolError("桌面通信接口不完整。", "BRIDGE_METHOD_MISSING");
      nativeBridge.startFloatingWindowResize(edge);
    },
  };
}

function nativeControls(nativeBridge) {
  return {
    minimizeWindow: () => nativeBridge.minimizeWindow(),
    toggleMaximizeWindow: () => nativeBridge.toggleMaximizeWindow(),
    toggleFullscreen: () => nativeBridge.toggleFullscreen(),
    closeWindow: () => nativeBridge.closeWindow(),
    startWindowMove: () => nativeBridge.startWindowMove(),
    startWindowResize: (edge) => nativeBridge.startWindowResize(edge),
  };
}

function nativeLibrary(nativeBridge) {
  return {
    async getState() {
      return parseBridgeResponse(await invokeWithResult(nativeBridge, "getLibraryState"), validLibraryState);
    },
    async setSortMode(mode) {
      if (!["recent", "manual"].includes(mode)) throw new BridgeProtocolError("排序方式无效。", "BRIDGE_INVALID_ARGUMENT");
      return parseBridgeResponse(await invokeWithResult(nativeBridge, "setLibrarySortMode", [mode]), validLibraryState);
    },
    async moveBook(input) {
      if (!input || typeof input.bookId !== "string" || !input.bookId || (input.beforeBookId !== null && (typeof input.beforeBookId !== "string" || !input.beforeBookId))) throw new BridgeProtocolError("排序请求无效。", "BRIDGE_INVALID_ARGUMENT");
      return parseBridgeResponse(await invokeWithResult(nativeBridge, "moveLibraryBook", [JSON.stringify(input)]), validLibraryState);
    },
    async revealSource(bookId) {
      if (typeof bookId !== "string" || !bookId) throw new BridgeProtocolError("书籍编号无效。", "BRIDGE_INVALID_ARGUMENT");
      return parseBridgeResponse(await invokeWithResult(nativeBridge, "revealLibrarySource", [bookId]), validSourceReveal);
    },
    async removeBook(bookId) {
      if (typeof bookId !== "string" || !bookId) throw new BridgeProtocolError("书籍编号无效。", "BRIDGE_INVALID_ARGUMENT");
      return parseBridgeResponse(await invokeWithResult(nativeBridge, "removeLibraryBook", [bookId]), validLibraryRemove);
    },
  };
}

function nativeSpeech(nativeBridge) {
  return {
    async updatePreferences(input) {
      const patch = input?.patch;
      const validPatch = patch
        && !Array.isArray(patch)
        && Object.keys(patch).length > 0
        && Object.entries(patch).every(([field, value]) => (
          (field === "ttsVoiceId" && typeof value === "string")
          || (field === "ttsRate" && Number.isInteger(value) && value >= 80 && value <= 400)
          || (field === "sentenceGapSeconds" && nonNegativeNumber(value) && value <= 1)
        ));
      if (!validPatch) throw new BridgeProtocolError("朗读设置参数无效。", "BRIDGE_INVALID_ARGUMENT");
      return parseBridgeResponse(
        await invokeWithResult(nativeBridge, "updateSpeechPreferences", [JSON.stringify(input)]),
        validSpeechState,
      );
    },
  };
}

function nativeSoftwareUpdates(nativeBridge) {
  return {
    async check(input = { manual: true }) {
      if (!input || typeof input.manual !== "boolean") throw new BridgeProtocolError("检查更新参数无效。", "BRIDGE_INVALID_ARGUMENT");
      return parseBridgeResponse(
        await invokeWithResult(nativeBridge, "checkSoftwareUpdate", [JSON.stringify(input)]),
        validSoftwareUpdateState,
      );
    },
    async download(version) {
      if (typeof version !== "string" || !version) throw new BridgeProtocolError("更新版本号无效。", "BRIDGE_INVALID_ARGUMENT");
      return parseBridgeResponse(
        await invokeWithResult(nativeBridge, "downloadSoftwareUpdate", [JSON.stringify({ version })]),
        validSoftwareUpdateState,
      );
    },
    async skip(version) {
      if (typeof version !== "string" || !version) throw new BridgeProtocolError("更新版本号无效。", "BRIDGE_INVALID_ARGUMENT");
      return parseBridgeResponse(
        await invokeWithResult(nativeBridge, "skipSoftwareUpdate", [JSON.stringify({ version })]),
        validSoftwareUpdateState,
      );
    },
    async install() {
      return parseBridgeResponse(
        await invokeWithResult(nativeBridge, "installSoftwareUpdate"),
        validSoftwareUpdateState,
      );
    },
    async openPage(target) {
      if (!["project", "release"].includes(target)) throw new BridgeProtocolError("更新页面参数无效。", "BRIDGE_INVALID_ARGUMENT");
      return parseBridgeResponse(
        await invokeWithResult(nativeBridge, "openSoftwareUpdatePage", [target]),
        validSoftwareUpdateState,
      );
    },
  };
}

function nativeApp(nativeBridge) {
  return {
    async updatePreferences(input) {
      const patch = input?.patch;
      const validPatch = patch
        && !Array.isArray(patch)
        && Object.keys(patch).length > 0
        && Object.entries(patch).every(([field, value]) => (
          (field === "theme" && APP_THEMES.has(value))
          || (field === "autoOpenLast" && typeof value === "boolean")
          || (field === "closeToTray" && typeof value === "boolean")
          || (field === "autoCheckUpdates" && typeof value === "boolean")
        ));
      if (!validPatch) throw new BridgeProtocolError("应用设置参数无效。", "BRIDGE_INVALID_ARGUMENT");
      return parseBridgeResponse(
        await invokeWithResult(nativeBridge, "updateAppPreferences", [JSON.stringify(input)]),
        validAppPreferences,
      );
    },
  };
}

function createNativeConnection(nativeBridge, initialState) {
  const subscriptions = [];
  const bridgeErrorCallbacks = new Set();
  const reportProtocolError = (error) => {
    const payload = JSON.stringify({
      schemaVersion: SCHEMA_VERSION,
      code: error.code || "BRIDGE_PROTOCOL_ERROR",
      message: error.message || "桌面通信事件无效。",
      retryable: false,
    });
    bridgeErrorCallbacks.forEach((callback) => callback(payload));
  };
  return {
    mode: "native",
    initialState,
    controls: nativeControls(nativeBridge),
    app: nativeApp(nativeBridge),
    updates: nativeSoftwareUpdates(nativeBridge),
    speech: nativeSpeech(nativeBridge),
    imports: nativeImports(nativeBridge),
    library: nativeLibrary(nativeBridge),
    reader: nativeReader(nativeBridge),
    floating: nativeFloating(nativeBridge),
    onBridgeError(callback) {
      bridgeErrorCallbacks.add(callback);
      signalSubscription(nativeBridge.bridgeError, callback, subscriptions);
      subscriptions.push(() => bridgeErrorCallbacks.delete(callback));
    },
    onWindowStateChanged(callback) {
      signalSubscription(nativeBridge.windowStateChanged, (raw) => {
        try {
          const event = parseJsonPayload(raw, "窗口状态事件无效。");
          if (!validWindowStateEvent(event)) throw new BridgeProtocolError("窗口状态事件无效。", "BRIDGE_INVALID_PAYLOAD");
          callback({ isMaximized: event.isMaximized, isFullScreen: event.isFullScreen });
        } catch (error) {
          reportProtocolError(error);
        }
      }, subscriptions);
    },
    onWindowInteractionChanged(callback) {
      return signalSubscription(nativeBridge.windowInteractionChanged, (surface, active) => {
        if (["main", "floating"].includes(surface) && typeof active === "boolean") callback({ surface, active });
        else reportProtocolError(new BridgeProtocolError("窗口交互状态无效。", "BRIDGE_INVALID_PAYLOAD"));
      }, subscriptions);
    },
    onAppPreferencesChanged(callback) {
      signalSubscription(nativeBridge.appPreferencesChanged, (raw) => {
        try {
          callback(parseImportEvent(raw, validAppPreferences, "应用设置事件无效。"));
        } catch (error) {
          reportProtocolError(error);
        }
      }, subscriptions);
    },
    onSpeechPreferencesChanged(callback) {
      signalSubscription(nativeBridge.speechPreferencesChanged, (raw) => {
        try {
          const event = parseJsonPayload(raw, "朗读设置事件无效。");
          if (!validSpeechChangedEvent(event)) throw new BridgeProtocolError("朗读设置事件无效。", "BRIDGE_INVALID_PAYLOAD");
          callback(event.state);
        } catch (error) {
          reportProtocolError(error);
        }
      }, subscriptions);
    },
    onSoftwareUpdateChanged(callback) {
      signalSubscription(nativeBridge.softwareUpdateChanged, (raw) => {
        try {
          callback(parseImportEvent(raw, validSoftwareUpdateState, "软件更新状态事件无效。"));
        } catch (error) {
          reportProtocolError(error);
        }
      }, subscriptions);
    },
    onImportProgress(callback) {
      signalSubscription(nativeBridge.importProgress, (raw) => {
        try {
          callback(parseImportEvent(raw, validImportProgress, "导入进度数据无效。"));
        } catch (error) {
          reportProtocolError(error);
        }
      }, subscriptions);
    },
    onImportFinished(callback) {
      signalSubscription(nativeBridge.importFinished, (raw) => {
        try {
          callback(parseImportEvent(raw, validImportFinished, "导入结果数据无效。"));
        } catch (error) {
          reportProtocolError(error);
        }
      }, subscriptions);
    },
    onReaderOpened(callback) {
      signalSubscription(nativeBridge.readerOpened, (raw) => {
        try {
          callback(parseImportEvent(raw, validReaderOpenedEvent, "阅读器打开事件无效。"));
        } catch (error) {
          reportProtocolError(error);
        }
      }, subscriptions);
    },
    onReaderSearchFinished(callback) {
      signalSubscription(nativeBridge.readerSearchFinished, (raw) => {
        try {
          callback(parseImportEvent(raw, validReaderSearchFinished, "书内搜索事件无效。"));
        } catch (error) {
          reportProtocolError(error);
        }
      }, subscriptions);
    },
    onReaderPlaybackChanged(callback) {
      signalSubscription(nativeBridge.readerPlaybackChanged, (raw) => {
        try {
          callback(parseImportEvent(raw, validReaderPlaybackEvent, "播放状态事件无效。"));
        } catch (error) {
          reportProtocolError(error);
        }
      }, subscriptions);
    },
    onFloatingReaderChanged(callback) {
      signalSubscription(nativeBridge.floatingReaderChanged, (raw) => {
        try {
          callback(parseImportEvent(raw, validFloatingChangedEvent, "悬浮朗读状态事件无效。"));
        } catch (error) {
          reportProtocolError(error);
        }
      }, subscriptions);
    },
    onFloatingPointerChanged(callback) {
      signalSubscription(nativeBridge.floatingPointerChanged, (inside) => {
        if (typeof inside === "boolean") callback(inside);
        else reportProtocolError(new BridgeProtocolError("悬浮窗鼠标状态事件无效。", "BRIDGE_INVALID_PAYLOAD"));
      }, subscriptions);
    },
    dispose() {
      subscriptions.splice(0).forEach((disconnect) => disconnect());
    },
  };
}

function signalSubscription(signal, callback, subscriptions) {
  if (!signal || typeof signal.connect !== "function") return () => {};
  signal.connect(callback);
  let connected = true;
  const unsubscribe = () => {
    if (connected && typeof signal.disconnect === "function") signal.disconnect(callback);
    connected = false;
  };
  subscriptions.push(unsubscribe);
  return unsubscribe;
}

function createDemoConnection() {
  const initialState = createDemoInitialState();
  const progressCallbacks = new Set();
  const finishedCallbacks = new Set();
  const readerOpenedCallbacks = new Set();
  const readerSearchCallbacks = new Set();
  const readerPlaybackCallbacks = new Set();
  const floatingChangedCallbacks = new Set();
  const appPreferencesCallbacks = new Set();
  const speechPreferencesCallbacks = new Set();
  const softwareUpdateCallbacks = new Set();
  const jobs = new Map();
  let jobSequence = 0;
  let readerSequence = 0;
  let demoSessionId = "";
  let demoBookId = "";
  let demoPosition = { chapterIndex: 0, charOffset: 0, progressPercent: 0 };
  let demoPlaybackState = demoPlayback(demoPosition);
  let demoFloating = demoFloatingState();
  let demoSpeech = { ...initialState.data.speech, settings: { ...initialState.data.speech.settings } };
  let demoSoftwareUpdate = { ...initialState.data.softwareUpdate };
  let demoManualOrder = initialState.data.library.books.map((book) => book.id);
  const demoRecentOrder = [...demoManualOrder];
  const demoLibraryState = () => {
    const library = initialState.data.library;
    const books = [...library.books];
    if (library.sortMode === "manual") books.sort((a, b) => demoManualOrder.indexOf(a.id) - demoManualOrder.indexOf(b.id));
    else books.sort((a, b) => (b.lastReadAt || 0) - (a.lastReadAt || 0) || demoRecentOrder.indexOf(a.id) - demoRecentOrder.indexOf(b.id));
    library.books = books;
    return { books, total: books.length, sortMode: library.sortMode };
  };

  const emit = (callbacks, payload) => callbacks.forEach((callback) => callback(payload));
  const response = (data) => ({ schemaVersion: SCHEMA_VERSION, ok: true, data, error: null });
  const addDemoBook = (name, format, title = "") => {
    const id = `demo-import-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const cleanTitle = title.trim() || name.replace(/\.[^.]+$/, "") || "粘贴文本";
    const book = {
      id,
      title: cleanTitle,
      author: "",
      format: format.toUpperCase(),
      progressPercent: 0,
      chapterIndex: 0,
      chapterCount: 1,
      currentChapterTitle: "尚未开始阅读",
      lastReadAt: Date.now() / 1000,
      totalChars: 0,
      coverUrl: `covers/library-${["indigo", "sage", "amber", "night"][initialState.data.library.books.length % 4]}.jpg`,
      canRevealSource: false,
    };
    demoManualOrder.push(id);
    demoRecentOrder.unshift(id);
    initialState.data.library.books = [book, ...initialState.data.library.books];
    initialState.data.library.total = initialState.data.library.books.length;
    demoLibraryState();
    return book;
  };
  const startJob = (items) => {
    const jobId = `demo-job-${++jobSequence}`;
    const job = { cancelled: false, timer: null };
    jobs.set(jobId, job);
    let completed = 0;
    let succeeded = 0;
    let failed = 0;
    const results = [];

    const finish = (state = "completed") => {
      const successful = results.filter((item) => item.status === "succeeded");
      const lastImportedBookId = successful.at(-1)?.bookId || "";
      emit(finishedCallbacks, {
        schemaVersion: SCHEMA_VERSION,
        jobId,
        state,
        total: items.length,
        processed: completed,
        succeeded,
        failed,
        lastImportedBookId,
        openAfterImportBookId: lastImportedBookId,
        results,
      });
      jobs.delete(jobId);
    };

    const processNext = () => {
      if (job.cancelled) {
        finish("cancelled");
        return;
      }
      const item = items[completed];
      if (!item) {
        finish();
        return;
      }
      let result;
      if (item.error) {
        failed += 1;
        result = { name: item.name, status: "failed", bookId: "", error: item.error };
      } else {
        const book = addDemoBook(item.name, item.format, item.title);
        succeeded += 1;
        result = { name: item.name, status: "succeeded", bookId: book.id, error: null };
      }
      completed += 1;
      results.push(result);
      emit(progressCallbacks, {
        schemaVersion: SCHEMA_VERSION,
        jobId,
        phase: "item",
        completed,
        total: items.length,
        succeeded,
        failed,
        item: {
          index: completed - 1,
          name: item.name,
          status: result.status,
          bookId: result.bookId,
        },
        error: result.error,
      });
      job.timer = setTimeout(processNext, 120);
    };

    job.timer = setTimeout(processNext, 80);
    return response({ jobId, state: "queued" });
  };

  return {
    mode: "demo",
    initialState,
    controls: NOOP_CONTROLS,
    app: {
      async updatePreferences(input) {
        const next = { ...initialState.data.preferences, ...input.patch };
        next.colorScheme = next.theme === "夜间" ? "dark" : "light";
        initialState.data.preferences = next;
        emit(appPreferencesCallbacks, next);
        return response(next);
      },
    },
    updates: {
      async check() {
        demoSoftwareUpdate = {
          ...demoSoftwareUpdate,
          status: "upToDate",
          latestVersion: demoSoftwareUpdate.currentVersion,
          lastCheckedAt: new Date().toISOString(),
          message: `当前已是最新版 v${demoSoftwareUpdate.currentVersion}。`,
          progressPercent: 0,
          downloadedBytes: 0,
          totalBytes: 0,
          canDownload: false,
          canInstall: false,
        };
        initialState.data.softwareUpdate = demoSoftwareUpdate;
        emit(softwareUpdateCallbacks, demoSoftwareUpdate);
        return response(demoSoftwareUpdate);
      },
      async download() { return response(demoSoftwareUpdate); },
      async skip() { return response(demoSoftwareUpdate); },
      async install() { return response(demoSoftwareUpdate); },
      async openPage() { return response(demoSoftwareUpdate); },
    },
    speech: {
      async updatePreferences(input) {
        demoSpeech = { ...demoSpeech, settings: { ...demoSpeech.settings, ...input.patch } };
        initialState.data.speech = demoSpeech;
        emit(speechPreferencesCallbacks, demoSpeech);
        return response(demoSpeech);
      },
    },
    imports: {
      async selectFiles() {
        const items = [
          { itemId: "demo-new", name: "演示新书.txt", format: "TXT", sizeBytes: 2048, supported: true, large: false, duplicate: { exists: false, bookId: "", title: "" } },
          { itemId: "demo-duplicate", name: "财富自由之路.epub", format: "EPUB", sizeBytes: 4096, supported: true, large: false, duplicate: { exists: true, bookId: "demo-3", title: "财富自由之路" } },
          { itemId: "demo-large", name: "长篇演示.txt", format: "TXT", sizeBytes: 30 * 1024 * 1024, supported: true, large: true, duplicate: { exists: false, bookId: "", title: "" } },
        ];
        return response({ cancelled: false, selectionId: "demo-selection", total: items.length, duplicateCount: 1, largeFileCount: 1, items });
      },
      async startFileImport(input) {
        if (!input?.confirmLargeFiles) {
          throw new BridgeProtocolError("请先确认导入大文件。", "LARGE_FILE_CONFIRMATION_REQUIRED");
        }
        const duplicateError = input.duplicateMode === "cancel"
          ? { code: "DUPLICATE_SKIPPED", message: "已跳过书架中的重复内容。", retryable: false }
          : null;
        return startJob([
          { name: "演示新书.txt", format: "TXT" },
          { name: "财富自由之路.epub", format: "EPUB", error: duplicateError },
          { name: "长篇演示.txt", format: "TXT" },
        ]);
      },
      async startPasteImport(input) {
        const text = input?.text?.trim();
        if (!text) {
          throw new BridgeProtocolError("正文不能为空，请粘贴要朗读的内容。", "PASTE_TEXT_EMPTY");
        }
        const title = input.title?.trim() || text.split(/\r?\n/).find((line) => line.trim())?.trim().slice(0, 40) || "粘贴文本";
        return startJob([{ name: `${title}.txt`, format: "TXT", title }]);
      },
      async cancelImport(jobId) {
        const job = jobs.get(jobId);
        if (job) job.cancelled = true;
        return response({ jobId, cancelRequested: Boolean(job) });
      },
    },
    library: {
      async getState() { return response(demoLibraryState()); },
      async setSortMode(mode) {
        if (!["recent", "manual"].includes(mode)) throw new BridgeProtocolError("排序方式无效。", "BRIDGE_INVALID_ARGUMENT");
        initialState.data.library.sortMode = mode;
        return response(demoLibraryState());
      },
      async moveBook(input) {
        if (initialState.data.library.sortMode !== "manual") throw new BridgeProtocolError("请先切换到自定义排序。", "SORT_MODE_REQUIRED");
        if (!input || !demoManualOrder.includes(input.bookId) || (input.beforeBookId !== null && !demoManualOrder.includes(input.beforeBookId))) throw new BridgeProtocolError("排序内容不存在。", "BOOK_NOT_FOUND");
        if (input.bookId !== input.beforeBookId) {
          demoManualOrder = demoManualOrder.filter((id) => id !== input.bookId);
          demoManualOrder.splice(input.beforeBookId === null ? demoManualOrder.length : demoManualOrder.indexOf(input.beforeBookId), 0, input.bookId);
        }
        return response(demoLibraryState());
      },
      async revealSource() { throw new BridgeProtocolError("浏览器演示内容没有本地源文件。", "SOURCE_UNAVAILABLE"); },
      async removeBook(bookId) {
        demoManualOrder = demoManualOrder.filter((id) => id !== bookId);
        const index = initialState.data.library.books.findIndex((book) => book.id === bookId);
        if (index < 0) throw new BridgeProtocolError("这项内容已不在内容库中。", "BOOK_NOT_FOUND");
        initialState.data.library.books.splice(index, 1);
        initialState.data.library.total = initialState.data.library.books.length;
        return response({ bookId, removed: true });
      },
    },
    reader: {
      async openBook(bookId) {
        const requestId = `demo-reader-request-${++readerSequence}`;
        demoSessionId = `demo-reader-session-${readerSequence}`;
        demoBookId = bookId;
        demoPosition = { chapterIndex: 0, charOffset: 0, progressPercent: 0 };
        demoPlaybackState = demoPlayback(demoPosition);
        demoFloating = { ...demoFloating, sessionId: demoSessionId, bookId, playback: demoPlaybackState };
        setTimeout(() => emit(readerOpenedCallbacks, {
          schemaVersion: SCHEMA_VERSION,
          requestId,
          bookId,
          ok: true,
          data: {
            sessionId: demoSessionId,
            book: { id: bookId, title: DEMO_BOOKS.find((book) => book.id === bookId)?.title || "演示内容", author: "", format: "EPUB", totalChars: DEMO_READER_TEXT.length, chapters: [{ index: 0, title: "第六章　运气的成分", charCount: DEMO_READER_TEXT.length }] },
            position: demoPosition,
            window: demoReaderWindow(demoSessionId, bookId),
            settings: demoReaderSettings(),
            playback: demoPlaybackState,
            bookmarkCount: 0,
          },
          error: null,
        }), 0);
        return response({ requestId, bookId, state: "loading" });
      },
      async getWindow(input) { return response(demoReaderWindow(input.sessionId, demoBookId, input.anchorOffset)); },
      async navigate(input) {
        const target = input.target.kind === "percent"
          ? { chapterIndex: 0, charOffset: Math.round(DEMO_READER_TEXT.length * input.target.percent / 100), progressPercent: input.target.percent }
          : { chapterIndex: input.target.chapterIndex, charOffset: input.target.charOffset, progressPercent: Math.round(input.target.charOffset / Math.max(1, DEMO_READER_TEXT.length) * 1000) / 10 };
        demoPosition = target;
        demoPlaybackState = { ...demoPlaybackState, position: target };
        return response({ position: target, window: demoReaderWindow(input.sessionId, demoBookId, target.charOffset), playback: demoPlaybackState });
      },
      async updatePosition(input) {
        demoPosition = { chapterIndex: input.chapterIndex, charOffset: input.charOffset, progressPercent: Math.round(input.charOffset / Math.max(1, DEMO_READER_TEXT.length) * 1000) / 10 };
        demoPlaybackState = { ...demoPlaybackState, position: demoPosition };
        return response({ updated: true, position: demoPosition });
      },
      async search(input) {
        const requestId = `demo-search-${++readerSequence}`;
        setTimeout(() => {
          const index = DEMO_READER_TEXT.indexOf(input.query);
          emit(readerSearchCallbacks, { schemaVersion: SCHEMA_VERSION, requestId, sessionId: input.sessionId, ok: true, data: { query: input.query, total: index >= 0 ? 1 : 0, nextCursor: "", results: index >= 0 ? [{ id: `demo-result-${index}`, chapterIndex: 0, chapterTitle: "第六章　运气的成分", startOffset: index, endOffset: index + input.query.length, excerptStartOffset: Math.max(0, index - 12), excerpt: DEMO_READER_TEXT.slice(Math.max(0, index - 12), index + input.query.length + 18) }] : [] }, error: null });
        }, 0);
        return response({ requestId, state: "searching" });
      },
      async listBookmarks() { return response({ total: 0, nextCursor: "", items: [] }); },
      async addBookmark(input) { return response({ id: `demo-bookmark-${Date.now()}`, chapterIndex: input.chapterIndex, chapterTitle: "第六章　运气的成分", startOffset: input.startOffset, endOffset: input.endOffset, text: DEMO_READER_TEXT.slice(input.startOffset, input.endOffset), note: input.note, createdAt: Date.now() / 1000 }); },
      async removeBookmark(input) { return response({ bookmarkId: input.bookmarkId, removed: true }); },
      async controlPlayback(input) {
        const status = input.command === "pause" ? "paused" : input.command === "stop" ? "idle" : "playing";
        const commandId = `demo-command-${++readerSequence}`;
        demoPlaybackState = demoPlayback(demoPosition, status);
        setTimeout(() => emit(readerPlaybackCallbacks, { schemaVersion: SCHEMA_VERSION, sessionId: input.sessionId, bookId: demoBookId, sequence: readerSequence, commandId, reason: "state", playback: demoPlaybackState, error: null }), 0);
        demoFloating = { ...demoFloating, sessionId: input.sessionId, bookId: demoBookId, playback: demoPlaybackState };
        setTimeout(() => emit(floatingChangedCallbacks, { schemaVersion: SCHEMA_VERSION, state: demoFloating }), 0);
        return response({ commandId, accepted: true });
      },
      async updateSettings(input) { return response({ ...demoReaderSettings(), ...input.patch }); },
    },
    floating: {
      async getState() { return response(demoFloating); },
      async show() {
        demoFloating = { ...demoFloating, visible: true };
        emit(floatingChangedCallbacks, { schemaVersion: SCHEMA_VERSION, state: demoFloating });
        return response(demoFloating);
      },
      async close() {
        demoFloating = { ...demoFloating, visible: false };
        emit(floatingChangedCallbacks, { schemaVersion: SCHEMA_VERSION, state: demoFloating });
        return response({ closed: true });
      },
      async returnToMain() {
        demoFloating = { ...demoFloating, visible: false };
        emit(floatingChangedCallbacks, { schemaVersion: SCHEMA_VERSION, state: demoFloating });
        return response({ closed: true });
      },
      async updateSettings(input) {
        demoFloating = { ...demoFloating, settings: { ...demoFloating.settings, ...input.patch } };
        emit(floatingChangedCallbacks, { schemaVersion: SCHEMA_VERSION, state: demoFloating });
        return response(demoFloating);
      },
      startWindowMove() {},
      startWindowResize() {},
    },
    onBridgeError() {},
    onWindowStateChanged() {},
    onWindowInteractionChanged() { return () => {}; },
    onAppPreferencesChanged(callback) { appPreferencesCallbacks.add(callback); },
    onSpeechPreferencesChanged(callback) { speechPreferencesCallbacks.add(callback); },
    onSoftwareUpdateChanged(callback) { softwareUpdateCallbacks.add(callback); },
    onImportProgress(callback) { progressCallbacks.add(callback); },
    onImportFinished(callback) { finishedCallbacks.add(callback); },
    onReaderOpened(callback) { readerOpenedCallbacks.add(callback); },
    onReaderSearchFinished(callback) { readerSearchCallbacks.add(callback); },
    onReaderPlaybackChanged(callback) { readerPlaybackCallbacks.add(callback); },
    onFloatingReaderChanged(callback) { floatingChangedCallbacks.add(callback); },
    onFloatingPointerChanged() {},
    dispose() {
      jobs.forEach((job) => clearTimeout(job.timer));
      jobs.clear();
      progressCallbacks.clear();
      finishedCallbacks.clear();
      readerOpenedCallbacks.clear();
      readerSearchCallbacks.clear();
      readerPlaybackCallbacks.clear();
      floatingChangedCallbacks.clear();
      appPreferencesCallbacks.clear();
      speechPreferencesCallbacks.clear();
      softwareUpdateCallbacks.clear();
    },
  };
}

export async function connectBridge(environment = {}) {
  const browserWindow = environment.window ?? (typeof window === "undefined" ? undefined : window);
  const browserDocument = environment.document ?? (typeof document === "undefined" ? undefined : document);

  if (!browserWindow?.qt?.webChannelTransport) {
    return createDemoConnection();
  }

  await loadQWebChannel(browserWindow, browserDocument);
  const channel = await createNativeChannel(browserWindow);
  const nativeBridge = channel.objects?.ddBridge;
  if (!nativeBridge) {
    throw new BridgeProtocolError("桌面通信对象不存在。", "BRIDGE_OBJECT_MISSING");
  }

  try {
    const initialState = parseInitialState(await invokeWithResult(nativeBridge, "getInitialState"));
    return createNativeConnection(nativeBridge, initialState);
  } catch (error) {
    if (error instanceof BridgeProtocolError) {
      error.connection = createNativeConnection(nativeBridge, {
        schemaVersion: SCHEMA_VERSION,
        ok: false,
        data: error.initialData,
        error: { code: error.code, message: error.message, retryable: false },
      });
    }
    throw error;
  }
}
