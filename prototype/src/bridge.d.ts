export const SCHEMA_VERSION: 2;

export interface BridgeError {
  code: string;
  message: string;
  retryable: boolean;
  details?: Record<string, unknown>;
}

export interface BridgeResponse<T> {
  schemaVersion: 2;
  ok: boolean;
  data: T;
  error: BridgeError | null;
}

export interface BookSummary {
  id: string;
  title: string;
  author: string;
  format: string;
  progressPercent: number;
  chapterIndex: number;
  chapterCount: number;
  currentChapterTitle: string;
  lastReadAt: number | null;
  totalChars: number;
  coverUrl: string;
  canRevealSource: boolean;
}

export interface LibraryState {
  books: BookSummary[];
  total: number;
  sortMode: "recent" | "manual";
}

export type AppTheme = "白天" | "护眼" | "夜间" | "米黄";

export interface AppPreferences {
  theme: AppTheme;
  colorScheme: "light" | "dark";
  autoOpenLast: boolean;
  closeToTray: boolean;
  autoCheckUpdates: boolean;
  startupBookId: string;
}

export type SoftwareUpdateStatus =
  | "idle"
  | "checking"
  | "upToDate"
  | "available"
  | "skipped"
  | "downloading"
  | "ready"
  | "installing"
  | "error";

export interface SoftwareUpdateState {
  status: SoftwareUpdateStatus;
  currentVersion: string;
  latestVersion: string;
  lastCheckedAt: string;
  message: string;
  releaseUrl: string;
  publishedAt: string;
  releaseNotes: string;
  progressPercent: number;
  downloadedBytes: number;
  totalBytes: number;
  canDownload: boolean;
  canInstall: boolean;
}

export interface SpeechVoiceOption {
  id: string;
  label: string;
  backend: "sapi" | "edge";
  requiresNetwork: boolean;
}

export interface SpeechPreferences {
  ttsVoiceId: string;
  ttsRate: number;
  sentenceGapSeconds: number;
}

export interface SpeechState {
  settings: SpeechPreferences;
  voices: SpeechVoiceOption[];
  loadingLocalVoices: boolean;
  localVoiceError: string;
}

export interface InitialStateData {
  app: { version: string };
  library: LibraryState;
  preferences: AppPreferences;
  window: { isMaximized: boolean; isFullScreen: boolean };
  speech: SpeechState;
  softwareUpdate: SoftwareUpdateState;
  capabilities: {
    fileImport: boolean;
    pasteImport: boolean;
    webImport: boolean;
    audioImport: boolean;
    reader: boolean;
    tts: boolean;
    floatingReader: boolean;
  };
}

export interface InitialStateResponse {
  schemaVersion: 2;
  ok: boolean;
  data: InitialStateData;
  error: BridgeError | null;
}

export type DuplicateMode = "cancel" | "overwrite" | "reparse";

export interface ImportSelectionItem {
  itemId: string;
  name: string;
  format: string;
  sizeBytes: number;
  supported: boolean;
  large: boolean;
  duplicate: {
    exists: boolean;
    bookId: string;
    title: string;
  };
}

export interface ImportSelectionData {
  cancelled: boolean;
  selectionId: string;
  total: number;
  duplicateCount: number;
  largeFileCount: number;
  items: ImportSelectionItem[];
}

export interface ImportStartData {
  jobId: string;
  state: "queued";
}

export interface ImportCancelData {
  jobId: string;
  cancelRequested: boolean;
}

export interface ImportProgressEvent {
  schemaVersion: 2;
  jobId: string;
  phase: "item";
  completed: number;
  total: number;
  succeeded: number;
  failed: number;
  item: {
    index: number;
    name: string;
    status: "running" | "succeeded" | "failed";
    bookId: string;
  };
  error: BridgeError | null;
}

export interface ImportResultItem {
  name: string;
  status: "succeeded" | "failed";
  bookId: string;
  error: BridgeError | null;
}

export interface ImportFinishedEvent {
  schemaVersion: 2;
  jobId: string;
  state: "completed" | "cancelled";
  total: number;
  processed: number;
  succeeded: number;
  failed: number;
  lastImportedBookId: string;
  openAfterImportBookId: string;
  results: ImportResultItem[];
}

export interface ImportControls {
  selectFiles(): Promise<BridgeResponse<ImportSelectionData>>;
  startFileImport(input: {
    selectionId: string;
    confirmLargeFiles: boolean;
    duplicateMode: DuplicateMode;
  }): Promise<BridgeResponse<ImportStartData>>;
  startPasteImport(input: {
    title: string;
    text: string;
  }): Promise<BridgeResponse<ImportStartData>>;
  cancelImport(jobId: string): Promise<BridgeResponse<ImportCancelData>>;
  startWebImport(input: { url: string }): Promise<BridgeResponse<ImportStartData>>;
}

export interface ReaderPosition {
  chapterIndex: number;
  charOffset: number;
  progressPercent: number;
}

export interface ReaderChapterSummary {
  index: number;
  title: string;
  charCount: number;
}

export interface ReaderTextBlock {
  id: string;
  startOffset: number;
  endOffset: number;
  text: string;
  startsParagraph: boolean;
  endsParagraph: boolean;
}

export interface ReaderContentWindow {
  sessionId: string;
  bookId: string;
  chapterIndex: number;
  chapterTitle: string;
  chapterCharCount: number;
  anchorOffset: number;
  windowStartOffset: number;
  windowEndOffset: number;
  hasBefore: boolean;
  hasAfter: boolean;
  blocks: ReaderTextBlock[];
}

export interface ReaderSentence {
  chapterIndex: number;
  startOffset: number;
  endOffset: number;
  text: string;
}

export type PlaybackStatus = "idle" | "playing" | "paused" | "finished" | "error";

export interface ReaderPlaybackSnapshot {
  status: PlaybackStatus;
  position: ReaderPosition;
  sentence: ReaderSentence | null;
  requestedBackend: "sapi" | "edge";
  activeBackend: "sapi" | "edge" | null;
  fallbackActive: boolean;
}

export interface ReaderSettings {
  fontFamily: string;
  fontSize: number;
  lineSpacing: number;
  paragraphMode: 1 | 2 | 3;
  firstLineIndent: boolean;
  ttsRate: number;
  ttsVoiceId: string;
  volume: number;
  sentenceGapSeconds: number;
}

export interface ReaderOpenData {
  sessionId: string;
  book: {
    id: string;
    title: string;
    author: string;
    format: string;
    totalChars: number;
    chapters: ReaderChapterSummary[];
  };
  position: ReaderPosition;
  window: ReaderContentWindow;
  settings: ReaderSettings;
  playback: ReaderPlaybackSnapshot;
  bookmarkCount: number;
}

export interface ReaderOpenStartData {
  requestId: string;
  bookId: string;
  state: "loading";
}

export interface ReaderOpenedEvent {
  schemaVersion: 2;
  requestId: string;
  bookId: string;
  ok: boolean;
  data: ReaderOpenData | null;
  error: BridgeError | null;
}

export type ReaderNavigationTarget =
  | { kind: "position"; chapterIndex: number; charOffset: number }
  | { kind: "percent"; percent: number };

export interface ReaderNavigateData {
  position: ReaderPosition;
  window: ReaderContentWindow;
  playback: ReaderPlaybackSnapshot;
}

export interface ReaderPositionUpdateData {
  updated: boolean;
  position: ReaderPosition;
}

export interface ReaderSearchResult {
  id: string;
  chapterIndex: number;
  chapterTitle: string;
  startOffset: number;
  endOffset: number;
  excerptStartOffset: number;
  excerpt: string;
}

export interface ReaderSearchPage {
  query: string;
  total: number;
  nextCursor: string;
  results: ReaderSearchResult[];
}

export interface ReaderSearchStartData {
  requestId: string;
  state: "searching";
}

export interface ReaderSearchFinishedEvent {
  schemaVersion: 2;
  requestId: string;
  sessionId: string;
  ok: boolean;
  data: ReaderSearchPage | null;
  error: BridgeError | null;
}

export interface ReaderBookmark {
  id: string;
  chapterIndex: number;
  chapterTitle: string;
  startOffset: number;
  endOffset: number;
  text: string;
  note: string;
  createdAt: number;
}

export interface ReaderBookmarkPage {
  total: number;
  nextCursor: string;
  items: ReaderBookmark[];
}

export type ReaderPlaybackCommand =
  | "play"
  | "pause"
  | "stop"
  | "previousSentence"
  | "nextSentence";

export interface ReaderPlaybackCommandData {
  commandId: string;
  accepted: boolean;
}

export interface ReaderPlaybackEvent {
  schemaVersion: 2;
  sessionId: string;
  bookId: string;
  sequence: number;
  commandId: string;
  reason:
    | "state"
    | "sentenceStart"
    | "sentenceDone"
    | "buffering"
    | "finished"
    | "fallback"
    | "error";
  playback: ReaderPlaybackSnapshot;
  error: BridgeError | null;
}

export type FloatingReaderBackground = "light" | "sepia" | "dark";

export interface FloatingReaderSettings {
  geometry: string;
  topmost: boolean;
  backgroundOpacity: number;
  fontSize: number;
  followReaderFont: boolean;
  background: FloatingReaderBackground;
  bilingual: boolean;
  textColor: "auto" | `#${string}`;
  hoverDisplayEnabled: boolean;
}

export interface FloatingReaderContext {
  chapterIndex: number;
  chapterTitle: string;
  previous: ReaderSentence | null;
  current: ReaderSentence | null;
  next: ReaderSentence | null;
}

export interface FloatingReaderState {
  sessionId: string;
  bookId: string;
  visible: boolean;
  settings: FloatingReaderSettings;
  playback: ReaderPlaybackSnapshot;
  context: FloatingReaderContext;
}

export interface FloatingReaderChangedEvent {
  schemaVersion: 2;
  state: FloatingReaderState;
}

export interface ReaderControls {
  openBook(bookId: string): Promise<BridgeResponse<ReaderOpenStartData>>;
  getWindow(input: {
    sessionId: string;
    chapterIndex: number;
    anchorOffset: number;
  }): Promise<BridgeResponse<ReaderContentWindow>>;
  navigate(input: {
    sessionId: string;
    target: ReaderNavigationTarget;
  }): Promise<BridgeResponse<ReaderNavigateData>>;
  updatePosition(input: {
    sessionId: string;
    chapterIndex: number;
    charOffset: number;
  }): Promise<BridgeResponse<ReaderPositionUpdateData>>;
  search(input: {
    sessionId: string;
    query: string;
    cursor: string;
  }): Promise<BridgeResponse<ReaderSearchStartData>>;
  listBookmarks(input: {
    sessionId: string;
    cursor: string;
  }): Promise<BridgeResponse<ReaderBookmarkPage>>;
  addBookmark(input: {
    sessionId: string;
    chapterIndex: number;
    startOffset: number;
    endOffset: number;
    note: string;
  }): Promise<BridgeResponse<ReaderBookmark>>;
  removeBookmark(input: {
    sessionId: string;
    bookmarkId: string;
  }): Promise<BridgeResponse<{ bookmarkId: string; removed: boolean }>>;
  controlPlayback(input: {
    sessionId: string;
    command: ReaderPlaybackCommand;
  }): Promise<BridgeResponse<ReaderPlaybackCommandData>>;
  updateSettings(input: {
    sessionId: string;
    patch: Partial<ReaderSettings>;
  }): Promise<BridgeResponse<ReaderSettings>>;
}

export interface LibraryControls {
  getState(): Promise<BridgeResponse<LibraryState>>;
  setSortMode(mode: "recent" | "manual"): Promise<BridgeResponse<LibraryState>>;
  moveBook(input: { bookId: string; beforeBookId: string | null }): Promise<BridgeResponse<LibraryState>>;
  revealSource(bookId: string): Promise<BridgeResponse<{ bookId: string; opened: boolean }>>;
  removeBook(bookId: string): Promise<BridgeResponse<{ bookId: string; removed: boolean }>>;
}

export interface FloatingReaderControls {
  getState(): Promise<BridgeResponse<FloatingReaderState>>;
  show(): Promise<BridgeResponse<FloatingReaderState>>;
  close(): Promise<BridgeResponse<{ closed: boolean }>>;
  returnToMain(): Promise<BridgeResponse<{ closed: boolean }>>;
  updateSettings(input: {
    patch: Partial<Pick<
      FloatingReaderSettings,
      "topmost" | "backgroundOpacity" | "fontSize" | "followReaderFont" | "background" | "bilingual" | "textColor" | "hoverDisplayEnabled"
    >>;
  }): Promise<BridgeResponse<FloatingReaderState>>;
  startWindowMove(): void;
  startWindowResize(edge: "top" | "right" | "bottom" | "left" | "topRight" | "bottomRight" | "bottomLeft" | "topLeft"): void;
}

export interface AppControls {
  updatePreferences(input: {
    patch: Partial<Pick<AppPreferences, "theme" | "autoOpenLast" | "closeToTray" | "autoCheckUpdates">>;
  }): Promise<BridgeResponse<AppPreferences>>;
}

export interface SoftwareUpdateControls {
  check(input?: { manual: boolean }): Promise<BridgeResponse<SoftwareUpdateState>>;
  download(version: string): Promise<BridgeResponse<SoftwareUpdateState>>;
  skip(version: string): Promise<BridgeResponse<SoftwareUpdateState>>;
  install(): Promise<BridgeResponse<SoftwareUpdateState>>;
  openPage(target: "project" | "release"): Promise<BridgeResponse<SoftwareUpdateState>>;
}

export interface SpeechControls {
  updatePreferences(input: {
    patch: Partial<SpeechPreferences>;
  }): Promise<BridgeResponse<SpeechState>>;
}

export interface WindowControls {
  minimizeWindow(): void;
  toggleMaximizeWindow(): void;
  toggleFullscreen(): void;
  closeWindow(): void;
  startWindowMove(): void;
  startWindowResize(edge: "top" | "right" | "bottom" | "left" | "topRight" | "bottomRight" | "bottomLeft" | "topLeft"): void;
}

export interface BridgeConnection {
  mode: "demo" | "native";
  initialState: InitialStateResponse;
  controls: WindowControls;
  app: AppControls;
  updates: SoftwareUpdateControls;
  speech: SpeechControls;
  imports: ImportControls;
  library: LibraryControls;
  reader: ReaderControls;
  floating: FloatingReaderControls;
  onBridgeError(callback: (payload: string) => void): void;
  onWindowStateChanged(callback: (state: { isMaximized: boolean; isFullScreen: boolean }) => void): void;
  onWindowInteractionChanged(callback: (state: { surface: "main" | "floating"; active: boolean }) => void): () => void;
  onAppPreferencesChanged(callback: (preferences: AppPreferences) => void): void;
  onSpeechPreferencesChanged(callback: (speech: SpeechState) => void): void;
  onSoftwareUpdateChanged(callback: (state: SoftwareUpdateState) => void): void;
  onImportProgress(callback: (event: ImportProgressEvent) => void): void;
  onImportFinished(callback: (event: ImportFinishedEvent) => void): void;
  onReaderOpened(callback: (event: ReaderOpenedEvent) => void): void;
  onReaderSearchFinished(callback: (event: ReaderSearchFinishedEvent) => void): void;
  onReaderPlaybackChanged(callback: (event: ReaderPlaybackEvent) => void): void;
  onFloatingReaderChanged(callback: (event: FloatingReaderChangedEvent) => void): void;
  onFloatingPointerChanged(callback: (inside: boolean) => void): void;
  dispose(): void;
}

export class BridgeProtocolError extends Error {
  code: string;
  initialData: InitialStateData;
  connection?: BridgeConnection;
  constructor(message: string, code?: string, initialData?: InitialStateData);
}

export function createDemoInitialState(): InitialStateResponse;
export function parseInitialState(raw: string | InitialStateResponse): InitialStateResponse;
export function connectBridge(environment?: { window?: Window; document?: Document }): Promise<BridgeConnection>;
