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
  contentType?: "" | "novel" | "article" | "reference";
  categoryId?: string;
  tagIds?: string[];
  readingStatus?: "unread" | "reading" | "read";
  statusMode?: "auto" | "manual";
}

export interface LibraryState {
  books: BookSummary[];
  total: number;
  sortMode: "recent" | "manual";
  categories?: ShelfTerm[];
  tags?: ShelfTerm[];
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
  backend: "sapi" | "edge" | "kokoro";
  requiresNetwork: boolean;
  available?: boolean;
  speakerId?: number;
  modelId?: string;
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

export interface SleepTimerState { mode: "off" | "minutes" | "chapter"; remainingMs: number; bookId: string; chapterIndex: number | null; endReason: string; version: number; }

export interface ReaderPlaybackSnapshot {
  sleepTimer?: SleepTimerState;
  preview?: { status: "idle" | "playing" | "completed" | "cancelled" | "error"; voiceId: string; error: BridgeError | null };
  status: PlaybackStatus;
  position: ReaderPosition;
  sentence: ReaderSentence | null;
  requestedBackend: "sapi" | "edge" | "kokoro";
  requestedVoiceId?: string;
  activeBackend: "sapi" | "edge" | "kokoro" | null;
  fallbackActive: boolean;
  purpose?: "book" | "preview";
  phase?: "speaking" | "buffering" | PlaybackStatus;
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
  kind?: "bookmark" | "annotation";
  color?: "yellow" | "green" | "blue" | "pink";
  updatedAt?: number;
  locationValid?: boolean;
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
    | "sleepStopped"
    | "buffering"
    | "finished"
    | "fallback"
    | "recovered"
    | "error";
  playback: ReaderPlaybackSnapshot;
  error: BridgeError | null;
  audioTransition?: { active: boolean; at: number };
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
  progressSeekEnabled: boolean;
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
    kind?: "bookmark" | "annotation";
    color?: "yellow" | "green" | "blue" | "pink";
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
      "topmost" | "backgroundOpacity" | "fontSize" | "followReaderFont" | "background" | "bilingual" | "textColor" | "hoverDisplayEnabled" | "progressSeekEnabled"
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
  features: { invoke<T extends ReaderFeatureRequest>(input: T): Promise<BridgeResponse<ReaderFeatureResult<T>>> };
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
  onFeaturesChanged(callback: (event: { schemaVersion: 2; kind: string; data: Record<string, unknown> }) => void): () => void;
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

export interface ShelfTerm { id: string; name: string; builtin?: boolean }
export interface ModelState {
  modelId: "kokoro-v1.0-int8" | "kokoro-v1.0-fp32";
  variant: "int8" | "fp32";
  status: "missing" | "downloading" | "verifying" | "extracting" | "loading" | "ready" | "error" | "cancelled";
  jobId: string; downloadedBytes: number; totalBytes: number; progressPercent: number;
  installedBytes: number; directory: string; message: string; error: BridgeError | null;
  playback?: ReaderPlaybackSnapshot;
}
export interface TimeSummary { readingMs: number; listeningMs: number; overlapMs: number; totalMs: number }
export interface StatisticsState { today: TimeSummary; total: TimeSummary; days: (TimeSummary & { date: string })[] }
export interface OfflineCacheJob { jobId: string; bookId: string; bookTitle?: string; chapterIndices: number[]; backend: "edge" | "kokoro"; voiceId: string; rate: number; modelId: string; modelSha256: string; state: "queued" | "preparing" | "running" | "paused" | "cancelled" | "completed" | "error"; done: number; total: number; bytes: number; verified: boolean; fingerprint: string; chapters: {index: number; done: number; total: number}[]; error: BridgeError | null; message: string; }
export interface OfflineCacheState { jobs: OfflineCacheJob[]; cacheRoot: string; }
export interface BackupMissing { bookId: string; kind: string; message: string; }
export interface BackupInventory { bookCount: number; noteCount: number; estimatedBytes: number; fileCount: number; missing: BackupMissing[]; targetRoot: string; includeAudio: boolean; includeModels: boolean; }
export interface BackupPreview { previewId: string; bookCount: number; noteCount: number; bytes: number; statisticsRange: (string | null)[]; missing: BackupMissing[]; targetRoot: string; replaceNames: string[]; rollbackEstimatedBytes?: number; }
export interface BackupJob { jobId: string; kind: "inventory" | "create" | "inspect" | "restore"; status: "running" | "completed" | "cancelled" | "error"; error: BridgeError | null; result: BackupInventory | BackupPreview | { path: string; complete: boolean; restored?: boolean; rollbackDirectory?: string; rollbackArchive?: string } | null; }
export interface VoiceCenterState { voices: (SpeechVoiceOption & { available: boolean; unavailableReason: string; statusLabel: string })[]; favorites: string[]; playback: ReaderPlaybackSnapshot; }
export type ReaderFeatureResult<T extends ReaderFeatureRequest> =
  T["action"] extends "modelState" | "modelVariant" | "modelDownload" | "modelRetry" | "modelCancel" | "modelImport" | "modelDirectory" ? ModelState :
  T["action"] extends "statistics" ? StatisticsState :
  T["action"] extends "organizationState" | "organizationUpdate" ? { categories: ShelfTerm[]; tags: ShelfTerm[] } :
  T["action"] extends "updateNote" ? ReaderBookmark :
  T["action"] extends "exportNotes" ? { saved: boolean; cancelled: boolean } :
  T["action"] extends "sleepTimer" | "sleepTimerState" ? SleepTimerState :
  T["action"] extends "cacheState" ? OfflineCacheState :
  T["action"] extends "cacheCreate" | "cacheControl" ? OfflineCacheJob :
  T["action"] extends "backupInventory" | "backupCreate" | "backupInspect" | "backupRestore" | "backupJob" | "backupCancel" ? BackupJob | { cancelled: true } :
  T["action"] extends "voiceCenter" | "voiceFavorite" ? VoiceCenterState :
  T["action"] extends "previewVoice" ? ReaderPlaybackCommandData : { accepted: boolean };
export type ReaderFeatureRequest =
  | { action: "modelState" | "modelDownload" | "modelRetry" | "modelCancel" | "modelImport" | "modelDirectory" | "organizationState" | "statistics" }
  | { action: "modelVariant"; variant: "int8" | "fp32" }
  | { action: "sleepTimer"; mode: "off" | "minutes" | "chapter"; minutes?: number }
  | { action: "sleepTimerState" }
  | { action: "cacheState" }
  | { action: "cacheCreate"; bookId: string; chapterIndices: number[]; backend: "edge" | "kokoro"; voiceId: string; rate: number }
  | { action: "cacheControl"; jobId: string; command: "pause" | "resume" | "cancel" | "verify" | "repair" | "clean"; confirmed?: boolean }
  | { action: "backupInventory" | "backupCreate" | "backupInspect"; includeAudio?: boolean; includeModels?: boolean }
  | { action: "backupRestore"; previewId: string }
  | { action: "backupJob" | "backupCancel"; jobId: string }
  | { action: "voiceCenter" | "cancelPreview" }
  | { action: "voiceFavorite"; voiceId: string; favorite: boolean }
  | { action: "previewVoice"; voiceId: string }
  | { action: "updateNote"; sessionId: string; bookmarkId: string; patch: { note?: string; color?: string } }
  | { action: "exportNotes"; sessionId: string; format: "md" | "txt" }
  | { action: "activity"; surface: "main" | "floating"; sessionId: string; visible: boolean; inputSequence: number }
  | { action: "organizationUpdate"; request: { action: "book" | "batch" | "create" | "rename" | "delete"; bookIds?: string[]; bookId?: string; patch?: Partial<Pick<BookSummary, "contentType" | "categoryId" | "tagIds" | "readingStatus" | "statusMode">> & { addTagIds?: string[]; removeTagIds?: string[] }; kind?: "categories" | "tags"; id?: string; name?: string } };

export class BridgeProtocolError extends Error {
  code: string;
  initialData: InitialStateData;
  connection?: BridgeConnection;
  constructor(message: string, code?: string, initialData?: InitialStateData);
}

export function createDemoInitialState(): InitialStateResponse;
export function parseInitialState(raw: string | InitialStateResponse): InitialStateResponse;
export function connectBridge(environment?: { window?: Window; document?: Document }): Promise<BridgeConnection>;
