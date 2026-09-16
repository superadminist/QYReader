import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  BridgeProtocolError,
  SCHEMA_VERSION,
  connectBridge,
  createDemoInitialState,
  parseInitialState,
} from "../src/bridge.js";
import { floatingLyricTransition } from "../src/floatingLyrics.js";
import {
  floatingFontWheelChange,
  floatingPickerColor,
  floatingTextColorPatch,
  mergeFloatingState,
  settingsPatchIds,
} from "../src/floatingSettings.js";
import { windowControlPresentation } from "../src/windowControls.js";
import { shouldApplyAudioWindow, windowContainsSentence } from "../src/readerWindowSync.js";
import { readerPositionFromRange } from "../src/readerPosition.js";

test("reader text range resolves an exact Unicode character offset", () => {
  const block = {
    nodeType: 1,
    dataset: { startOffset: "20" },
    textContent: "甲😀乙丙",
    closest: () => block,
  };
  const textNode = { nodeType: 3, parentElement: block };
  const root = {
    contains: (node) => node === block,
    ownerDocument: {
      createRange: () => ({
        selectNodeContents() {},
        setEnd() {},
        toString: () => "甲😀",
      }),
    },
  };

  assert.deepEqual(readerPositionFromRange(root, {
    startContainer: textNode,
    startOffset: 3,
  }, 4), {
    kind: "position",
    chapterIndex: 4,
    charOffset: 22,
  });
});

test("reader text range rejects a selection outside the reading copy", () => {
  const outside = { nodeType: 1, closest: () => null };
  const root = { contains: () => false };
  assert.equal(readerPositionFromRange(root, {
    startContainer: outside,
    startOffset: 0,
  }, 0), null);
});

test("audio window ignores stale or wrong-chapter responses", () => {
  const first = { chapterIndex: 0, startOffset: 10 };
  const second = { chapterIndex: 0, startOffset: 200 };
  const firstWindow = { chapterIndex: 0, windowStartOffset: 0, windowEndOffset: 100 };
  const secondWindow = { chapterIndex: 0, windowStartOffset: 150, windowEndOffset: 250 };
  assert.ok(windowContainsSentence(firstWindow, first));
  assert.equal(windowContainsSentence(firstWindow, second), false);
  assert.equal(shouldApplyAudioWindow(1, 2, first, { sentence: second }, firstWindow), false);
  assert.equal(shouldApplyAudioWindow(2, 2, second, { sentence: second }, firstWindow), false);
  assert.equal(shouldApplyAudioWindow(2, 2, second, { sentence: second }, secondWindow), true);
});


function signal() {
  const callbacks = new Set();
  return {
    connect(callback) { callbacks.add(callback); },
    disconnect(callback) { callbacks.delete(callback); },
    emit(payload) { callbacks.forEach((callback) => callback(payload)); },
    get size() { return callbacks.size; },
  };
}

function readerFixture() {
  const position = { chapterIndex: 0, charOffset: 0, progressPercent: 0 };
  const playback = { status: "idle", position, sentence: null, requestedBackend: "sapi", activeBackend: null, fallbackActive: false };
  const window = { sessionId: "reader-session", bookId: "book-1", chapterIndex: 0, chapterTitle: "第一章", chapterCharCount: 4, anchorOffset: 0, windowStartOffset: 0, windowEndOffset: 4, hasBefore: false, hasAfter: false, blocks: [{ id: "0:0:4", startOffset: 0, endOffset: 4, text: "真实正文", startsParagraph: true, endsParagraph: true }] };
  const settings = { fontFamily: "微软雅黑", fontSize: 17, lineSpacing: 1.5, paragraphMode: 1, firstLineIndent: true, ttsRate: 200, ttsVoiceId: "voice-1", volume: 100, sentenceGapSeconds: 0.1 };
  return { sessionId: "reader-session", book: { id: "book-1", title: "真实书籍", author: "作者", format: "TXT", totalChars: 4, chapters: [{ index: 0, title: "第一章", charCount: 4 }] }, position, window, settings, playback, bookmarkCount: 0 };
}

function floatingFixture(overrides = {}) {
  const reader = readerFixture();
  return {
    visible: true,
    sessionId: reader.sessionId,
    bookId: reader.book.id,
    settings: { geometry: "", topmost: true, backgroundOpacity: 0.94, fontSize: 20, followReaderFont: true, background: "light", bilingual: false, textColor: "auto", hoverDisplayEnabled: true },
    playback: reader.playback,
    context: {
      chapterIndex: 0,
      chapterTitle: "第一章",
      previous: null,
      current: { chapterIndex: 0, startOffset: 0, endOffset: 2, text: "真实" },
      next: { chapterIndex: 0, startOffset: 2, endOffset: 4, text: "正文" },
    },
    ...overrides,
  };
}

function nativeEnvironment(response) {
  const calls = [];
  const ok = (data) => JSON.stringify({ schemaVersion: SCHEMA_VERSION, ok: true, data, error: null });
  const nativeBridge = {
    bridgeError: signal(),
    windowStateChanged: signal(),
    appPreferencesChanged: signal(),
    speechPreferencesChanged: signal(),
    softwareUpdateChanged: signal(),
    importProgress: signal(),
    importFinished: signal(),
    readerOpened: signal(),
    readerSearchFinished: signal(),
    readerPlaybackChanged: signal(),
    floatingReaderChanged: signal(),
    floatingPointerChanged: signal(),
    getInitialState(callback) { callback(JSON.stringify(response)); },
    selectImportFiles(callback) {
      calls.push(["selectImportFiles"]);
      callback(ok({
        cancelled: false,
        selectionId: "selection-1",
        total: 1,
        duplicateCount: 0,
        largeFileCount: 0,
        items: [{
          itemId: "item-1",
          name: "novel.txt",
          format: "TXT",
          sizeBytes: 12,
          supported: true,
          large: false,
          duplicate: { exists: false, bookId: "", title: "" },
        }],
      }));
    },
    startFileImport(input, callback) {
      calls.push(["startFileImport", input]);
      callback(ok({ jobId: "job-file", state: "queued" }));
    },
    startPasteImport(input, callback) {
      calls.push(["startPasteImport", input]);
      callback(ok({ jobId: "job-paste", state: "queued" }));
    },
    cancelImport(jobId, callback) {
      calls.push(["cancelImport", jobId]);
      callback(ok({ jobId, cancelRequested: true }));
    },
    openReaderBook(bookId, callback) { calls.push(["openReaderBook", bookId]); callback(ok({ requestId: "reader-request", bookId, state: "loading" })); },
    getReaderWindow(input, callback) { calls.push(["getReaderWindow", input]); callback(ok(readerFixture().window)); },
    navigateReader(input, callback) { calls.push(["navigateReader", input]); const fixture = readerFixture(); callback(ok({ position: fixture.position, window: fixture.window, playback: fixture.playback })); },
    updateReaderPosition(input, callback) { calls.push(["updateReaderPosition", input]); callback(ok({ updated: true, position: readerFixture().position })); },
    searchReader(input, callback) { calls.push(["searchReader", input]); callback(ok({ requestId: "search-request", state: "searching" })); },
    listReaderBookmarks(input, callback) { calls.push(["listReaderBookmarks", input]); callback(ok({ total: 0, nextCursor: "", items: [] })); },
    addReaderBookmark(input, callback) { calls.push(["addReaderBookmark", input]); callback(ok({ id: "bookmark-1", chapterIndex: 0, chapterTitle: "第一章", startOffset: 0, endOffset: 2, text: "真实", note: "重点", createdAt: 1 })); },
    removeReaderBookmark(input, callback) { calls.push(["removeReaderBookmark", input]); callback(ok({ bookmarkId: "bookmark-1", removed: true })); },
    controlReaderPlayback(input, callback) { calls.push(["controlReaderPlayback", input]); callback(ok({ commandId: "command-1", accepted: true })); },
    updateReaderSettings(input, callback) { calls.push(["updateReaderSettings", input]); callback(ok({ ...readerFixture().settings, ...JSON.parse(input).patch })); },
    getFloatingReaderState(callback) { calls.push(["getFloatingReaderState"]); callback(ok(floatingFixture())); },
    showFloatingReader(callback) { calls.push(["showFloatingReader"]); callback(ok(floatingFixture({ visible: true }))); },
    closeFloatingReader(callback) { calls.push(["closeFloatingReader"]); callback(ok({ closed: true })); },
    returnToMainWindow(callback) { calls.push(["returnToMainWindow"]); callback(ok({ closed: true })); },
    updateFloatingReaderSettings(input, callback) { calls.push(["updateFloatingReaderSettings", input]); const fixture = floatingFixture(); callback(ok({ ...fixture, settings: { ...fixture.settings, ...JSON.parse(input).patch } })); },
    updateAppPreferences(input, callback) { calls.push(["updateAppPreferences", input]); const patch = JSON.parse(input).patch; const preferences = { ...response.data.preferences, ...patch }; preferences.colorScheme = preferences.theme === "夜间" ? "dark" : "light"; callback(ok(preferences)); },
    updateSpeechPreferences(input, callback) { calls.push(["updateSpeechPreferences", input]); const patch = JSON.parse(input).patch; callback(ok({ ...response.data.speech, settings: { ...response.data.speech.settings, ...patch } })); },
    checkSoftwareUpdate(input, callback) { calls.push(["checkSoftwareUpdate", input]); callback(ok({ ...response.data.softwareUpdate, status: "checking", message: "正在检查更新…" })); },
    downloadSoftwareUpdate(input, callback) { calls.push(["downloadSoftwareUpdate", input]); callback(ok({ ...response.data.softwareUpdate, status: "downloading", latestVersion: "2.0.2", message: "正在下载…" })); },
    skipSoftwareUpdate(input, callback) { calls.push(["skipSoftwareUpdate", input]); callback(ok({ ...response.data.softwareUpdate, status: "skipped", latestVersion: "2.0.2", message: "已跳过。" })); },
    installSoftwareUpdate(callback) { calls.push(["installSoftwareUpdate"]); callback(ok({ ...response.data.softwareUpdate, status: "installing", latestVersion: "2.0.2", message: "正在安装。" })); },
    openSoftwareUpdatePage(target, callback) { calls.push(["openSoftwareUpdatePage", target]); callback(ok(response.data.softwareUpdate)); },
    startFloatingWindowMove() { calls.push(["startFloatingWindowMove"]); },
    startFloatingWindowResize(edge) { calls.push(["startFloatingWindowResize", edge]); },
    minimizeWindow() { calls.push(["minimizeWindow"]); },
    toggleMaximizeWindow() { calls.push(["toggleMaximizeWindow"]); },
    toggleFullscreen() { calls.push(["toggleFullscreen"]); },
    closeWindow() { calls.push(["closeWindow"]); },
    startWindowMove() { calls.push(["startWindowMove"]); },
    startWindowResize(edge) { calls.push(["startWindowResize", edge]); },
  };
  const browserWindow = {
    qt: { webChannelTransport: {} },
    QWebChannel: class {
      constructor(_transport, ready) { ready({ objects: { ddBridge: nativeBridge } }); }
    },
  };
  return { browserWindow, nativeBridge, calls };
}

test("browser preview uses the versioned demo provider", async () => {
  const connection = await connectBridge({ window: {}, document: null });
  assert.equal(connection.mode, "demo");
  assert.equal(connection.initialState.schemaVersion, SCHEMA_VERSION);
  assert.equal(connection.initialState.data.library.total, 4);
});

test("demo paste import stays isolated and emits the frozen event contract", async () => {
  const connection = await connectBridge({ window: {}, document: null });
  const finished = new Promise((resolve) => connection.onImportFinished(resolve));
  const start = await connection.imports.startPasteImport({ title: "浏览器演示导入", text: "真实提交内容" });
  const event = await finished;

  assert.equal(start.data.state, "queued");
  assert.equal(event.jobId, start.data.jobId);
  assert.equal(event.succeeded, 1);
  assert.ok(event.openAfterImportBookId.startsWith("demo-import-"));
  assert.equal(connection.initialState.data.library.books[0].title, "浏览器演示导入");
  assert.equal(connection.initialState.data.library.total, 5);
  connection.dispose();
});

test("native provider validates schema and delegates window controls", async () => {
  const response = createDemoInitialState();
  response.data.library = { books: [], total: 0 };
  const env = nativeEnvironment(response);

  const connection = await connectBridge({ window: env.browserWindow, document: null });
  connection.controls.minimizeWindow();
  connection.controls.toggleMaximizeWindow();
  connection.controls.toggleFullscreen();
  connection.controls.startWindowMove();
  connection.controls.startWindowResize("topLeft");
  connection.controls.closeWindow();

  assert.equal(connection.mode, "native");
  assert.deepEqual(env.calls, [
    ["minimizeWindow"],
    ["toggleMaximizeWindow"],
    ["toggleFullscreen"],
    ["startWindowMove"],
    ["startWindowResize", "topLeft"],
    ["closeWindow"],
  ]);
});

test("native application preferences preserve legacy themes and validate events", async () => {
  const env = nativeEnvironment(createDemoInitialState());
  const connection = await connectBridge({ window: env.browserWindow, document: null });
  const events = [];
  const errors = [];
  connection.onAppPreferencesChanged((preferences) => events.push(preferences));
  connection.onBridgeError((raw) => errors.push(JSON.parse(raw)));

  const updated = await connection.app.updatePreferences({ patch: { theme: "夜间", autoOpenLast: false, closeToTray: true, autoCheckUpdates: false } });
  assert.equal(updated.data.colorScheme, "dark");
  assert.deepEqual(env.calls, [["updateAppPreferences", JSON.stringify({ patch: { theme: "夜间", autoOpenLast: false, closeToTray: true, autoCheckUpdates: false } })]]);
  env.nativeBridge.appPreferencesChanged.emit(JSON.stringify(updated.data));
  env.nativeBridge.appPreferencesChanged.emit(JSON.stringify({ ...updated.data, colorScheme: "light" }));
  assert.equal(events.length, 1);
  assert.equal(errors.at(-1).code, "BRIDGE_INVALID_PAYLOAD");
  await assert.rejects(
    connection.app.updatePreferences({ patch: { theme: "蓝色" } }),
    (error) => error instanceof BridgeProtocolError && error.code === "BRIDGE_INVALID_ARGUMENT",
  );
  await assert.rejects(
    connection.app.updatePreferences({ patch: { closeToTray: "yes" } }),
    (error) => error instanceof BridgeProtocolError && error.code === "BRIDGE_INVALID_ARGUMENT",
  );
  connection.dispose();
  assert.equal(env.nativeBridge.appPreferencesChanged.size, 0);
});

test("native software updater validates commands and update events", async () => {
  const env = nativeEnvironment(createDemoInitialState());
  const connection = await connectBridge({ window: env.browserWindow, document: null });
  const events = [];
  const errors = [];
  connection.onSoftwareUpdateChanged((state) => events.push(state));
  connection.onBridgeError((raw) => errors.push(JSON.parse(raw)));

  await connection.updates.check({ manual: true });
  await connection.updates.download("2.0.2");
  await connection.updates.skip("2.0.2");
  await connection.updates.install();
  await connection.updates.openPage("project");
  assert.deepEqual(env.calls, [
    ["checkSoftwareUpdate", JSON.stringify({ manual: true })],
    ["downloadSoftwareUpdate", JSON.stringify({ version: "2.0.2" })],
    ["skipSoftwareUpdate", JSON.stringify({ version: "2.0.2" })],
    ["installSoftwareUpdate"],
    ["openSoftwareUpdatePage", "project"],
  ]);

  const available = { ...createDemoInitialState().data.softwareUpdate, status: "available", latestVersion: "2.0.2", message: "发现新版本。", canDownload: true };
  env.nativeBridge.softwareUpdateChanged.emit(JSON.stringify(available));
  env.nativeBridge.softwareUpdateChanged.emit(JSON.stringify({ ...available, progressPercent: 101 }));
  assert.equal(events.length, 1);
  assert.equal(events[0].latestVersion, "2.0.2");
  assert.equal(errors.at(-1).code, "BRIDGE_INVALID_PAYLOAD");
  await assert.rejects(
    connection.updates.check({ manual: "yes" }),
    (error) => error instanceof BridgeProtocolError && error.code === "BRIDGE_INVALID_ARGUMENT",
  );
  connection.dispose();
  assert.equal(env.nativeBridge.softwareUpdateChanged.size, 0);
});

test("native speech preferences keep the full voice catalog and validate events", async () => {
  const env = nativeEnvironment(createDemoInitialState());
  const connection = await connectBridge({ window: env.browserWindow, document: null });
  const events = [];
  connection.onSpeechPreferencesChanged((speech) => events.push(speech));

  const updated = await connection.speech.updatePreferences({ patch: { ttsVoiceId: "zh-CN-YunxiNeural", ttsRate: 260, sentenceGapSeconds: 0.25 } });
  assert.equal(updated.data.settings.ttsRate, 260);
  assert.ok(updated.data.voices.length >= 2);
  assert.deepEqual(env.calls, [["updateSpeechPreferences", JSON.stringify({ patch: { ttsVoiceId: "zh-CN-YunxiNeural", ttsRate: 260, sentenceGapSeconds: 0.25 } })]]);
  env.nativeBridge.speechPreferencesChanged.emit(JSON.stringify({ schemaVersion: SCHEMA_VERSION, state: updated.data }));
  assert.equal(events[0].settings.ttsVoiceId, "zh-CN-YunxiNeural");
  await assert.rejects(
    connection.speech.updatePreferences({ patch: { ttsRate: 401 } }),
    (error) => error instanceof BridgeProtocolError && error.code === "BRIDGE_INVALID_ARGUMENT",
  );
  connection.dispose();
  assert.equal(env.nativeBridge.speechPreferencesChanged.size, 0);
});

test("native import controls use the frozen slot names and serialize inputs", async () => {
  const env = nativeEnvironment(createDemoInitialState());
  const connection = await connectBridge({ window: env.browserWindow, document: null });

  const selection = await connection.imports.selectFiles();
  const fileStart = await connection.imports.startFileImport({
    selectionId: selection.data.selectionId,
    confirmLargeFiles: true,
    duplicateMode: "overwrite",
  });
  const pasteStart = await connection.imports.startPasteImport({ title: "标题", text: "正文" });
  const cancelled = await connection.imports.cancelImport(fileStart.data.jobId);

  assert.equal(selection.data.items[0].name, "novel.txt");
  assert.equal(pasteStart.data.jobId, "job-paste");
  assert.equal(cancelled.data.cancelRequested, true);
  assert.deepEqual(env.calls, [
    ["selectImportFiles"],
    ["startFileImport", JSON.stringify({ selectionId: "selection-1", confirmLargeFiles: true, duplicateMode: "overwrite" })],
    ["startPasteImport", JSON.stringify({ title: "标题", text: "正文" })],
    ["cancelImport", "job-file"],
  ]);
});

test("native reader controls use the frozen slots and serialize complex inputs", async () => {
  const env = nativeEnvironment(createDemoInitialState());
  const connection = await connectBridge({ window: env.browserWindow, document: null });
  const sessionId = "reader-session";

  await connection.reader.openBook("book-1");
  await connection.reader.getWindow({ sessionId, chapterIndex: 0, anchorOffset: 0 });
  await connection.reader.navigate({ sessionId, target: { kind: "percent", percent: 42 } });
  await connection.reader.updatePosition({ sessionId, chapterIndex: 0, charOffset: 2 });
  await connection.reader.search({ sessionId, query: "真实", cursor: "" });
  await connection.reader.listBookmarks({ sessionId, cursor: "" });
  await connection.reader.addBookmark({ sessionId, chapterIndex: 0, startOffset: 0, endOffset: 2, note: "重点" });
  await connection.reader.removeBookmark({ sessionId, bookmarkId: "bookmark-1" });
  await connection.reader.controlPlayback({ sessionId, command: "play" });
  await connection.reader.updateSettings({ sessionId, patch: { fontSize: 22, paragraphMode: 2 } });

  assert.deepEqual(env.calls, [
    ["openReaderBook", "book-1"],
    ["getReaderWindow", JSON.stringify({ sessionId, chapterIndex: 0, anchorOffset: 0 })],
    ["navigateReader", JSON.stringify({ sessionId, target: { kind: "percent", percent: 42 } })],
    ["updateReaderPosition", JSON.stringify({ sessionId, chapterIndex: 0, charOffset: 2 })],
    ["searchReader", JSON.stringify({ sessionId, query: "真实", cursor: "" })],
    ["listReaderBookmarks", JSON.stringify({ sessionId, cursor: "" })],
    ["addReaderBookmark", JSON.stringify({ sessionId, chapterIndex: 0, startOffset: 0, endOffset: 2, note: "重点" })],
    ["removeReaderBookmark", JSON.stringify({ sessionId, bookmarkId: "bookmark-1" })],
    ["controlReaderPlayback", JSON.stringify({ sessionId, command: "play" })],
    ["updateReaderSettings", JSON.stringify({ sessionId, patch: { fontSize: 22, paragraphMode: 2 } })],
  ]);
});

test("native floating controls use the frozen slots, validate settings and preserve the active session", async () => {
  const env = nativeEnvironment(createDemoInitialState());
  const connection = await connectBridge({ window: env.browserWindow, document: null });

  const state = await connection.floating.getState();
  await connection.floating.show();
  await connection.floating.updateSettings({ patch: { topmost: false, backgroundOpacity: 0.8, fontSize: 24, followReaderFont: false, background: "sepia", bilingual: true, textColor: "#123ABC", hoverDisplayEnabled: false } });
  connection.floating.startWindowMove();
  connection.floating.startWindowResize("bottomRight");
  const closed = await connection.floating.close();
  const returned = await connection.floating.returnToMain();

  assert.equal(state.data.sessionId, "reader-session");
  assert.equal(state.data.bookId, "book-1");
  assert.equal(closed.data.closed, true);
  assert.equal(returned.data.closed, true);
  assert.deepEqual(env.calls, [
    ["getFloatingReaderState"],
    ["showFloatingReader"],
    ["updateFloatingReaderSettings", JSON.stringify({ patch: { topmost: false, backgroundOpacity: 0.8, fontSize: 24, followReaderFont: false, background: "sepia", bilingual: true, textColor: "#123ABC", hoverDisplayEnabled: false } })],
    ["startFloatingWindowMove"],
    ["startFloatingWindowResize", "bottomRight"],
    ["closeFloatingReader"],
    ["returnToMainWindow"],
  ]);
  await assert.rejects(
    connection.floating.updateSettings({ patch: { backgroundOpacity: 2 } }),
    (error) => error instanceof BridgeProtocolError && error.code === "BRIDGE_INVALID_ARGUMENT",
  );
  await assert.rejects(
    connection.floating.updateSettings({ patch: { backgroundOpacity: -0.01 } }),
    (error) => error instanceof BridgeProtocolError && error.code === "BRIDGE_INVALID_ARGUMENT",
  );
  await assert.rejects(
    connection.floating.updateSettings({ patch: { fontSize: 41 } }),
    (error) => error instanceof BridgeProtocolError && error.code === "BRIDGE_INVALID_ARGUMENT",
  );
  await assert.rejects(
    connection.floating.updateSettings({ patch: { textColor: "red" } }),
    (error) => error instanceof BridgeProtocolError && error.code === "BRIDGE_INVALID_ARGUMENT",
  );
  assert.throws(
    () => connection.floating.startWindowResize("center"),
    (error) => error instanceof BridgeProtocolError && error.code === "BRIDGE_INVALID_ARGUMENT",
  );
});

test("floating state events are validated and disconnected on dispose", async () => {
  const env = nativeEnvironment(createDemoInitialState());
  const connection = await connectBridge({ window: env.browserWindow, document: null });
  const events = [];
  const pointerEvents = [];
  const errors = [];
  connection.onFloatingReaderChanged((event) => events.push(event));
  connection.onFloatingPointerChanged((inside) => pointerEvents.push(inside));
  connection.onBridgeError((raw) => errors.push(JSON.parse(raw)));

  env.nativeBridge.floatingReaderChanged.emit(JSON.stringify({ schemaVersion: SCHEMA_VERSION, state: floatingFixture() }));
  env.nativeBridge.floatingReaderChanged.emit(JSON.stringify({ schemaVersion: SCHEMA_VERSION, state: floatingFixture({ settings: { ...floatingFixture().settings, background: "neon" } }) }));
  env.nativeBridge.floatingPointerChanged.emit(true);
  env.nativeBridge.floatingPointerChanged.emit(false);

  assert.equal(events.length, 1);
  assert.deepEqual(pointerEvents, [true, false]);
  assert.equal(events[0].state.context.current.text, "真实");
  assert.equal(errors.at(-1).code, "BRIDGE_INVALID_PAYLOAD");
  connection.dispose();
  assert.equal(env.nativeBridge.floatingReaderChanged.size, 0);
  assert.equal(env.nativeBridge.floatingPointerChanged.size, 0);
});

test("native reader business errors preserve their backend code before success-data validation", async () => {
  const env = nativeEnvironment(createDemoInitialState());
  env.nativeBridge.openReaderBook = (_bookId, callback) => callback(JSON.stringify({
    schemaVersion: SCHEMA_VERSION,
    ok: false,
    data: { requestId: "", bookId: "missing", state: "loading" },
    error: { code: "BOOK_NOT_FOUND", message: "内容库中不存在该书籍。", retryable: false },
  }));
  const connection = await connectBridge({ window: env.browserWindow, document: null });
  await assert.rejects(
    connection.reader.openBook("missing"),
    (error) => error instanceof BridgeProtocolError && error.code === "BOOK_NOT_FOUND",
  );
});

test("native reader events are parsed, bounded and disposed", async () => {
  const env = nativeEnvironment(createDemoInitialState());
  const connection = await connectBridge({ window: env.browserWindow, document: null });
  const opened = [];
  const searches = [];
  const playback = [];
  const errors = [];
  connection.onReaderOpened((event) => opened.push(event));
  connection.onReaderSearchFinished((event) => searches.push(event));
  connection.onReaderPlaybackChanged((event) => playback.push(event));
  connection.onBridgeError((raw) => errors.push(JSON.parse(raw)));

  env.nativeBridge.readerOpened.emit(JSON.stringify({ schemaVersion: SCHEMA_VERSION, requestId: "reader-request", bookId: "book-1", ok: true, data: readerFixture(), error: null }));
  env.nativeBridge.readerSearchFinished.emit(JSON.stringify({ schemaVersion: SCHEMA_VERSION, requestId: "search-request", sessionId: "reader-session", ok: true, data: { query: "真实", total: 1, nextCursor: "", results: [{ id: "result-1", chapterIndex: 0, chapterTitle: "第一章", startOffset: 0, endOffset: 2, excerptStartOffset: 0, excerpt: "真实正文" }] }, error: null }));
  env.nativeBridge.readerPlaybackChanged.emit(JSON.stringify({ schemaVersion: SCHEMA_VERSION, sessionId: "reader-session", bookId: "book-1", sequence: 1, commandId: "command-1", reason: "sentenceStart", playback: { ...readerFixture().playback, status: "playing", activeBackend: "sapi", sentence: { chapterIndex: 0, startOffset: 0, endOffset: 2, text: "真实" } }, error: null }));
  env.nativeBridge.readerPlaybackChanged.emit(JSON.stringify({ schemaVersion: SCHEMA_VERSION, sessionId: "reader-session", bookId: "book-1", sequence: 2, commandId: "command-1", reason: "buffering", playback: { ...readerFixture().playback, status: "playing", activeBackend: "edge" }, error: null }));
  const oversized = readerFixture();
  oversized.window.blocks = Array.from({ length: 121 }, (_, index) => ({ id: `0:${index}:${index + 1}`, startOffset: index, endOffset: index + 1, text: "字", startsParagraph: true, endsParagraph: true }));
  env.nativeBridge.readerOpened.emit(JSON.stringify({ schemaVersion: SCHEMA_VERSION, requestId: "oversized", bookId: "book-1", ok: true, data: oversized, error: null }));

  assert.equal(opened.length, 1);
  assert.equal(searches[0].data.results[0].startOffset, 0);
  assert.equal(playback[0].playback.sentence.endOffset, 2);
  assert.equal(playback[1].reason, "buffering");
  assert.equal(errors.at(-1).code, "BRIDGE_INVALID_PAYLOAD");
  connection.dispose();
  assert.equal(env.nativeBridge.readerOpened.size, 0);
  assert.equal(env.nativeBridge.readerSearchFinished.size, 0);
  assert.equal(env.nativeBridge.readerPlaybackChanged.size, 0);
});

test("native import events are parsed and all subscriptions are disposed", async () => {
  const env = nativeEnvironment(createDemoInitialState());
  const connection = await connectBridge({ window: env.browserWindow, document: null });
  const progress = [];
  const finished = [];
  connection.onImportProgress((event) => progress.push(event));
  connection.onImportFinished((event) => finished.push(event));

  env.nativeBridge.importProgress.emit(JSON.stringify({
    schemaVersion: SCHEMA_VERSION,
    jobId: "job-1",
    phase: "item",
    completed: 1,
    total: 1,
    succeeded: 1,
    failed: 0,
    item: { index: 0, name: "novel.txt", status: "succeeded", bookId: "book-1" },
    error: null,
  }));
  env.nativeBridge.importFinished.emit(JSON.stringify({
    schemaVersion: SCHEMA_VERSION,
    jobId: "job-1",
    state: "completed",
    total: 1,
    processed: 1,
    succeeded: 1,
    failed: 0,
    lastImportedBookId: "book-1",
    openAfterImportBookId: "book-1",
    results: [{ name: "novel.txt", status: "succeeded", bookId: "book-1", error: null }],
  }));

  assert.equal(progress[0].item.bookId, "book-1");
  assert.equal(finished[0].openAfterImportBookId, "book-1");
  assert.equal(env.nativeBridge.importProgress.size, 1);
  assert.equal(env.nativeBridge.importFinished.size, 1);
  connection.dispose();
  assert.equal(env.nativeBridge.importProgress.size, 0);
  assert.equal(env.nativeBridge.importFinished.size, 0);
});

test("malformed import events surface a bridge error without reaching React", async () => {
  const env = nativeEnvironment(createDemoInitialState());
  const connection = await connectBridge({ window: env.browserWindow, document: null });
  const errors = [];
  const progress = [];
  connection.onBridgeError((payload) => errors.push(JSON.parse(payload)));
  connection.onImportProgress((event) => progress.push(event));

  env.nativeBridge.importProgress.emit('{"schemaVersion":1,"jobId":"broken"}');

  assert.equal(progress.length, 0);
  assert.equal(errors[0].code, "BRIDGE_INVALID_PAYLOAD");
  assert.equal(errors[0].message, "导入进度数据无效。");
});

test("native errors are observable and subscriptions are disposed", async () => {
  const env = nativeEnvironment(createDemoInitialState());
  const connection = await connectBridge({ window: env.browserWindow, document: null });
  const received = [];
  connection.onBridgeError((payload) => received.push(payload));
  env.nativeBridge.bridgeError.emit('{"message":"failed"}');
  assert.deepEqual(received, ['{"message":"failed"}']);
  assert.equal(env.nativeBridge.bridgeError.size, 1);
  connection.dispose();
  assert.equal(env.nativeBridge.bridgeError.size, 0);
});

test("schema mismatch and backend failure never fall back to demo data", async () => {
  assert.throws(
    () => parseInitialState({ ...createDemoInitialState(), schemaVersion: 3 }),
    (error) => error instanceof BridgeProtocolError && error.code === "SCHEMA_MISMATCH",
  );

  const failed = createDemoInitialState();
  failed.ok = false;
  failed.data.library = { books: [], total: 0 };
  failed.error = { code: "LIBRARY_INVALID", message: "书架损坏", retryable: false };
  const env = nativeEnvironment(failed);
  await assert.rejects(
    connectBridge({ window: env.browserWindow, document: null }),
    (error) => {
      assert.equal(error.code, "LIBRARY_INVALID");
      assert.equal(error.initialData.library.total, 0);
      assert.equal(error.connection.mode, "native");
      error.connection.controls.closeWindow();
      error.connection.controls.startWindowMove();
      assert.deepEqual(env.calls, [["closeWindow"], ["startWindowMove"]]);
      return true;
    },
  );
});

test("incomplete schema v1 data is rejected before React receives it", () => {
  const missingCapabilities = createDemoInitialState();
  delete missingCapabilities.data.capabilities;
  assert.throws(
    () => parseInitialState(missingCapabilities),
    (error) => error.code === "BRIDGE_INVALID_PAYLOAD",
  );

  const invalidBook = createDemoInitialState();
  invalidBook.data.library.books[0].title = null;
  assert.throws(
    () => parseInitialState(invalidBook),
    (error) => error.code === "BRIDGE_INVALID_PAYLOAD",
  );
});

test("floating lyric transitions follow sentence identity in both directions", () => {
  const context = (chapterIndex, startOffset) => ({
    previous: null,
    current: { chapterIndex, startOffset, endOffset: startOffset + 4, text: `${chapterIndex}:${startOffset}` },
    next: null,
  });
  const first = context(0, 0);
  const second = context(0, 4);
  const previousChapter = context(0, 99);
  const nextChapter = context(1, 0);

  assert.deepEqual(floatingLyricTransition(first, first), {
    changed: false,
    direction: "forward",
    previousIdentity: "0:0",
    nextIdentity: "0:0",
  });
  assert.equal(floatingLyricTransition(first, second).direction, "forward");
  assert.equal(floatingLyricTransition(second, first).direction, "backward");
  assert.equal(floatingLyricTransition(previousChapter, nextChapter).direction, "forward");
  assert.equal(floatingLyricTransition(nextChapter, previousChapter).direction, "backward");
});

test("rapid floating lyric updates always retain the newest sentence", () => {
  const contexts = [0, 4, 8, 12].map((startOffset) => ({
    previous: null,
    current: { chapterIndex: 0, startOffset, endOffset: startOffset + 4, text: String(startOffset) },
    next: null,
  }));
  let rendered = contexts[0];
  for (const next of contexts.slice(1)) {
    const transition = floatingLyricTransition(rendered, next);
    assert.equal(transition.changed, true);
    assert.equal(transition.direction, "forward");
    rendered = next;
  }
  assert.equal(rendered.current.startOffset, 12);
});

test("floating font wheel exits reader-follow mode on the first event", () => {
  assert.deepEqual(floatingFontWheelChange(22, true, -120), {
    fontSize: 23,
    immediate: true,
    patch: { followReaderFont: false, fontSize: 23 },
  });
  assert.deepEqual(floatingFontWheelChange(40, true, -120), {
    fontSize: 40,
    immediate: true,
    patch: { followReaderFont: false, fontSize: 40 },
  });
  assert.equal(floatingFontWheelChange(40, false, -120), null);
});

test("floating custom color applies optimistically and auto color stays explicit", () => {
  const state = floatingFixture();
  assert.equal(floatingPickerColor({ background: "dark", textColor: "auto" }), "#F0F2F6");
  assert.deepEqual(floatingTextColorPatch("#12abef"), { textColor: "#12ABEF" });
  assert.equal(mergeFloatingState(state, { textColor: "#12ABEF" }).settings.textColor, "#12ABEF");
});

test("settings pending identities are isolated per field", () => {
  assert.deepEqual(settingsPatchIds("floating", { followReaderFont: true, fontSize: 24 }), [
    "floating.followReaderFont",
    "floating.fontSize",
  ]);
  assert.notEqual("floating.followReaderFont", "floating.textColor");
});

test("floating body keeps scrolling capability while hiding Chromium scrollbars", async () => {
  const css = await readFile(new URL("../src/styles.css", import.meta.url), "utf8");
  assert.match(css, /\.native-floating-surface \.floating-content \{[^}]*overflow: auto;[^}]*scrollbar-width: none;/s);
  assert.match(css, /\.native-floating-surface \.floating-content::\-webkit\-scrollbar \{[^}]*display: none;/s);
  assert.match(css, /\.mac-window \{[^}]*background: #f7f9fc;/s);
  assert.match(css, /\.mac-titlebar \{[^}]*background: #f4f7fb;/s);
});

test("settings modal avoids the Qt WebEngine full-window backdrop filter flicker path", async () => {
  const [css, app] = await Promise.all([
    readFile(new URL("../src/styles.css", import.meta.url), "utf8"),
    readFile(new URL("../src/App.jsx", import.meta.url), "utf8"),
  ]);
  const modalBackdrop = css.match(/\.modal-backdrop \{([^}]*)\}/)?.[1] || "";
  const settingsModal = css.match(/\.settings-modal \{([^}]*)\}/)?.[1] || "";
  const settingsScroll = css.match(/\.settings-scroll \{([^}]*)\}/)?.[1] || "";
  assert.doesNotMatch(modalBackdrop, /backdrop-filter/);
  assert.match(settingsModal, /border-radius: 24px/);
  assert.match(settingsModal, /overflow: hidden/);
  assert.match(settingsScroll, /overflow-y: auto/);
  assert.match(app, /\["general", "常规"\]/);
  assert.match(app, /\["reading", "朗读与悬浮"\]/);
  assert.match(app, /\["updates", "更新与关于"\]/);
  assert.match(app, /preferences\.closeToTray/);
  assert.match(app, /点击关闭按钮时最小化到系统托盘/);
  assert.match(app, /preferences\.autoCheckUpdates/);
  assert.match(app, /启动时自动检查正式版更新/);
  assert.match(app, /SHA256/);
  assert.match(app, /function UpdateAvailableModal/);
  assert.match(app, /本次更新内容/);
});

test("software update state carries bounded user-readable release notes", () => {
  const state = createDemoInitialState().data.softwareUpdate;
  assert.equal(typeof state.releaseNotes, "string");
  assert.equal(typeof state.publishedAt, "string");
});

test("native window surfaces let the transparent CSS clip paint the main corners", async () => {
  const css = await readFile(new URL("../src/styles.css", import.meta.url), "utf8");
  assert.match(css, /--main-window-radius: 22px;/);
  assert.match(css, /--floating-window-radius: 30px;/);
  assert.match(css, /\.desktop-host \.mac-window \{[^}]*width: 100vw;[^}]*height: 100vh;[^}]*margin: 0;[^}]*border-radius: var\(--main-window-radius\);/s);
  assert.match(css, /\.desktop-host\[data-window-mode="maximized"\] \.mac-window,[\s\S]*border-radius: 0;/);
  assert.match(css, /\.floating-surface-stage \{[^}]*padding: 2px;/s);
  assert.match(css, /\.native-floating-surface \{[^}]*border-radius: var\(--floating-window-radius\);/s);
});

test("floating reader keeps chrome tied to pointer while the switch only controls idle context", async () => {
  const css = await readFile(new URL("../src/styles.css", import.meta.url), "utf8");
  const app = await readFile(new URL("../src/App.jsx", import.meta.url), "utf8");
  const host = await readFile(new URL("../../novelreader/qt_host.py", import.meta.url), "utf8");
  assert.match(css, /--floating-header-row: 0px;/);
  assert.match(css, /--floating-footer-row: 0px;/);
  assert.match(css, /\.native-floating-surface\[data-interaction-visible="true"\] \{[\s\S]*--floating-header-row: 48px;[\s\S]*--floating-footer-row: 58px;/);
  assert.match(css, /\.native-floating-surface \.floating-dragbar,[\s\S]*visibility: hidden;[\s\S]*pointer-events: none;/);
  assert.match(css, /\.native-floating-surface\[data-pointer-inside="true"\] \.floating-sentence\.previous,[\s\S]*\.native-floating-surface\[data-pointer-inside="true"\] \.floating-sentence\.next,/);
  assert.match(css, /@media \(hover: none\)[\s\S]*--floating-header-row: 48px;[\s\S]*--floating-footer-row: 58px;/);
  assert.match(css, /\.native-floating-surface\[data-hover-display-enabled="false"\] \.floating-sentence\.previous,[\s\S]*\.floating-sentence\.next \{ display: none; \}/);
  assert.match(app, /const \[pointerInside, setPointerInside\] = useState\(false\);/);
  assert.match(app, /connection\.onFloatingPointerChanged\(\(inside\) =>/);
  assert.match(app, /const interactionVisible = pointerInside;/);
  assert.doesNotMatch(app, /const interactionVisible = !hoverDisplayEnabled/);
  assert.match(app, /root\.dataset\.contextMode = "all";\s*if \(hoverDisplayEnabled && !pointerInside\)/);
  assert.match(app, /data-pointer-inside=\{pointerInside \? "true" : "false"\}/);
  assert.match(app, /data-hover-display-enabled=\{hoverDisplayEnabled \? "true" : "false"\}/);
  assert.match(app, /鼠标移开时显示上一段和下一段/);
  assert.doesNotMatch(css, /\.native-floating-surface:hover/);
  assert.match(host, /def enterEvent\(self, event\)[\s\S]*floatingPointerChanged\.emit\(True\)/);
  assert.match(host, /def leaveEvent\(self, event\)[\s\S]*floatingPointerChanged\.emit\(False\)/);
});

test("Windows titlebar derives the maximize and restore presentation from native state", () => {
  assert.deepEqual(windowControlPresentation({ isMaximized: false, isFullScreen: false }), {
    isMaximized: false,
    maximizeLabel: "最大化窗口",
    maximizeIcon: "maximize",
  });
  assert.deepEqual(windowControlPresentation({ isMaximized: true, isFullScreen: false }), {
    isMaximized: true,
    maximizeLabel: "还原窗口",
    maximizeIcon: "restore",
  });
});

test("main titlebar uses right-side Windows controls and no traffic lights", async () => {
  const [source, css] = await Promise.all([
    readFile(new URL("../src/App.jsx", import.meta.url), "utf8"),
    readFile(new URL("../src/styles.css", import.meta.url), "utf8"),
  ]);
  assert.doesNotMatch(source, /traffic-lights|className="traffic/);
  assert.match(source, /className="window-controls"/);
  assert.match(source, /aria-label=\{windowPresentation\.maximizeLabel\}/);
  assert.match(source, /data-no-window-drag/);
  assert.match(css, /\.titlebar-actions \{[^}]*right: 150px;/s);
  assert.match(css, /\.window-controls \{[^}]*right: 0;/s);
  assert.match(css, /\.window-control\.close:hover \{[^}]*background: #c42b1c;/s);
});

test("network trouble uses one subtle animated status shared by main and floating readers", async () => {
  const [source, css] = await Promise.all([
    readFile(new URL("../src/App.jsx", import.meta.url), "utf8"),
    readFile(new URL("../src/styles.css", import.meta.url), "utf8"),
  ]);
  assert.match(source, /function NetworkStatusHint/);
  assert.match(source, /event\.reason === "buffering"/);
  assert.match(source, /event\.error\?\.code === "EDGE_OFFLINE_FALLBACK"/);
  assert.match(source, /event\.reason === "recovered"/);
  assert.match(source, /网络异常，正在使用系统语音；恢复后会自动切回所选音色/);
  assert.doesNotMatch(source, /setTimeout\(\(\) => setNotice\(null\), 6000\)/);
  assert.match(source, /playback\.fallbackActive \? NETWORK_FALLBACK_NOTICE/);
  assert.match(source, /<NativePlayer[\s\S]*networkNotice=\{networkNotice\}/);
  assert.match(source, /<NativeFloatingReader[\s\S]*networkNotice=\{networkNotice\}/);
  assert.match(css, /@keyframes network-status-ripple/);
  assert.match(css, /\.network-status-copy \{[^}]*text-overflow: ellipsis;/s);
  assert.match(css, /\.network-status-hint \{[^}]*max-width: 100%;[^}]*overflow: hidden;/s);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)[\s\S]*network-status-icon/);
});

test("active reader scrolls cannot passively move the shared playback sentence", async () => {
  const source = await readFile(new URL("../src/App.jsx", import.meta.url), "utf8");
  assert.match(source, /const handleScroll = \(event\) => \{[\s\S]*if \(playback\.status !== "idle"\) return;/);
  assert.match(source, /\[playback\?\.status\]/);
  assert.match(source, /behavior: requested \? "smooth" : "auto"/);
  assert.match(source, /mark\.top >= viewport\.top \+ 16 && mark\.bottom <= viewport\.bottom - 16/);
  assert.doesNotMatch(source, /\[sentence\?\.chapterIndex, sentence\?\.startOffset, playback\?\.status, windowData\]/);
});

test("return-to-current-reader-text is a scroll-only playback-bar action", async () => {
  const source = await readFile(new URL("../src/App.jsx", import.meta.url), "utf8");
  const handler = source.match(/const locateCurrentSentence = \(\) => \{[\s\S]*?\n  \};\n  const handleScroll/);
  assert.ok(handler);
  assert.match(handler[0], /target\.scrollIntoView\(\{ block: "center", behavior: "smooth" \}\)/);
  assert.match(handler[0], /onGetWindow\(current\.chapterIndex, current\.startOffset\)/);
  assert.doesNotMatch(handler[0], /onNavigate\(|onUpdatePosition\(|onCommand\(/);
  assert.match(source, /label="定位当前朗读" disabled=\{!playback\.sentence\}/);
});

test("floating footer replaces bilingual control with a native bottom-right resize grip", async () => {
  const [source, css] = await Promise.all([
    readFile(new URL("../src/App.jsx", import.meta.url), "utf8"),
    readFile(new URL("../src/styles.css", import.meta.url), "utf8"),
  ]);
  assert.doesNotMatch(source, />中 \/ EN</);
  assert.match(source, /className="floating-resize-control"[\s\S]*onResize\("bottomRight"\)/);
  assert.match(source, /aria-label="拖动调整悬浮窗大小"/);
  assert.match(css, /grid-template-columns: 126px minmax\(96px, 108px\) 36px;/);
  assert.match(css, /\.floating-resize-control:hover/);
  assert.match(css, /cursor: nwse-resize;/);
});
