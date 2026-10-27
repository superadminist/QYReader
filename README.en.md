# QYReader (启远阅读)

[简体中文](README.md) | [English](README.en.md)

<p align="center"><img src="assets/qyreader-icon.png" alt="QYReader icon" width="144"></p>

QYReader is a local novel and document reader for Windows. The 2.x desktop application uses **PySide6 / Qt WebEngine** to host a React interface, with QWebChannel connecting it to local Python services. Your library, text, reading progress, and settings are stored on your computer by default.

The app icon depicts open book pages leading toward morning light. Deep blue represents quiet reading, while warm gold suggests exploration. The repository includes the high-resolution PNG source and a Windows ICO with 16/32/48/64/128/256-pixel layers.

## UI design showcase

These macOS-inspired UI concepts put the software first, with neutral gray backgrounds, simple windows, and clear typography. They illustrate existing features and are not screenshots of the current release. QYReader remains a Windows application. The artwork uses Chinese interface text.

**Keep the words you love close.** Bring files, pasted text, and web articles into a local library, organize by content type and reading status, and pick up where you left off.

![QYReader library concept showing multi-format import, content filters, book covers, and reading progress](assets/screenshots/library-showcase.png)

**Read deeply. Listen freely.** Chapter navigation and comfortable typography support focused reading. Free Kokoro offline voices, current-sentence highlighting, and a compact four-color annotation toolbar connect reading, listening, and note-taking.

![QYReader reading concept showing chapter navigation, highlights and notes, current-sentence highlighting, and Kokoro offline playback](assets/screenshots/reader-showcase.png)

**Let the story stay with you.** An independent floating reader shows the surrounding sentences, supports always-on-top mode, adjustable background opacity, and playback controls, and shares reading progress with the main window.

![QYReader floating reader concept showing surrounding sentences, pinning, playback controls, whole-book progress, and background opacity](assets/screenshots/floating-reader-showcase.png)

**Just the words. Just the story.** In the text-only floating view, moving the pointer away hides the title bar and playback controls, leaving surrounding sentences visible and the current passage emphasized.

![QYReader text-only floating reader concept with hidden title bar and controls, subdued surrounding sentences, and bold current text](assets/screenshots/floating-reader-text-showcase.png)

## Current features

### v2.2.0 · 2026-10-22

- Free offline text-to-speech: download or manually import the official **Kokoro v1.0 INT8 / standard FP32** model packages in Settings. Both variants offer the same eight Chinese voices: 晓北, 晓妮, 晓晓, 晓伊, 云健, 云希, 云夏, and 云扬. Open Settings → Voices & Models (音色与模型) → Free Offline Voice Pack (免费离线音色包) → Model Version (模型版本). Stop playback before selecting and installing another variant. FP32 requires about 350 MB to download; INT8 requires about 132 MB. Switching preserves installed models and the selected voice. Generation speed depends on your computer. Edge and SAPI remain available through the shared `SpeechController` / `PlaybackService`. Slow generation displays a waiting state without automatically switching voices.
- Offline generation scheduling: the selected model warms up in the background. Current playback and voice previews take priority over prefetching, and cached audio is immediately available. Stopping, seeking, and switching models isolate stale tasks. Incremental cache accounting and Windows long-path support reduce queueing and repeated disk scans.
- Highlights and notes: select text to open a compact toolbar beside the selection, then click one of four color dots to highlight, choose Write Note (写笔记) for a lightweight editor, or choose Read from selection (朗读). The toolbar does not shift the text. Click an existing highlight to view its note, change its color, edit, or delete it. A successful save clears the blue text selection and shows feedback; pending saves prevent duplicate submissions. The bookmark panel retains navigation and Markdown / TXT export. Existing bookmarks are preserved. Positions use Unicode code points, so changing font size or line spacing does not change anchors.
- Sleep timers: the main playback bar and floating controls share 15 / 30 / 60-minute presets, a custom 1–720-minute timer, and Stop at Chapter End (读完本章). Pausing does not pause the countdown. Expiry stops playback while retaining the position; chapter timers stop before the next chapter speaks and cancel when you switch books or manually leave the target chapter.
- Offline chapters: open Prepare Offline Listening (准备离线听书) in the reader toolbar or Settings → Offline Listening (离线听书). Choose Edge or Kokoro, a voice and speed, and the current chapter, following chapters, custom chapter numbers, or the entire book. Pause, resume, verify, repair missing audio, cancel while keeping audio, or confirm cache cleanup. Playback and previews have priority over background preparation. Retained Kokoro chapters are excluded from temporary cache eviction until you clean them. Tasks require revalidation after restarting or changing content or models. SAPI remains available for live reading.
- Voice center: Settings → Voices & Models (音色与模型) groups Edge, Kokoro, and system voices, with name / engine / ID search, favorites, cancellable or replaceable previews, and reasons for unavailable voices. Previewing does not save the reading voice, change book progress, or count as listening time. Resume the original book manually afterward.
- Backup and restore: Settings → Backup & Restore (备份与恢复) estimates size before saving library metadata, available text and source copies, progress, notes, categories, tags, favorites, and statistics. Audio and models are optional. Restore verifies files and previews the destination, missing content, and replacement scope before confirmation. It replaces the full snapshot and retains a pre-restore backup, preserving book IDs and note anchors without changing original external files.
- Bulk library management: click Bulk Management (批量管理) in the library, select items or all filtered results, and set or clear categories, add or remove tags, or change reading status. The UI counts selected items outside the filter. Other tags are retained, and manually set reading status can explicitly return to automatic tracking.
- Reading statistics: the main and floating windows share local statistics, including today's time, total time, and a one-year heatmap. Reading counts while the text is visible in the foreground and there has been activity within five minutes. Listening counts actual playback, including background playback; generation, buffering, pauses, and voice previews do not count. Total time excludes overlap between reading and listening. Statistics start at zero when no historical data exists.
- Library organization: content types (novels / articles / reference material), one category per item, multiple tags, and unread / reading / finished filters. Read Later (待读) is a built-in tag. Actual use marks an item as reading, and 100% progress marks it as finished; you can also lock its status manually. Reimporting preserves progress, bookmarks, and unknown fields.

New interface elements follow the existing themes, controls, rounded corners, and typography. Source tests do not establish which features are present in an installed build; voice quality still requires listening in person.

- Content library: browse existing items, search, view recently read content, and automatically reopen the last item.
- Import: file selection, pasted text, and web links. Supported formats include TXT, MD/Markdown, DOC/DOCX, EPUB, MOBI, AZW3, PDF, HTML/HTM, and ZIP.
- Documents and web articles: Markdown import keeps the prose while removing formatting markers, images, link URLs, metadata, and code blocks. DOC supports unencrypted Word 97–2003 binary documents; DOCX extracts body and table text. HTTP/HTTPS article extraction saves a local copy for offline reading, text-to-speech, search, and progress tracking. It does not execute page scripts or use browser login sessions. For pages requiring login, CAPTCHAs, or dynamic loading, copy the article and use pasted-text import.
- Reader: chapter list, chunked text, chapter navigation, progress, full-text search, bookmarks, font size, line spacing, and blank-line modes. Click or select text to start reading aloud at any character position. The playback bar can smoothly scroll to the current sentence.
- Text-to-speech: local SAPI5 and Edge neural voices share a single `SpeechController`. Controls include play, pause, stop, previous/next sentence, speed, volume, and current-sentence highlighting. Edge failures fall back to SAPI5 with a persistent notice; after network recovery, playback returns to the selected voice at a sentence boundary. Local highlighting tracks actual SAPI stream numbers. Resuming rereads the current sentence, and late events from old streams cannot advance the next sentence prematurely.
- Independent floating reader: shows the previous, current, and next sentences and shares chapter, character offset, progress, and playback state with the main window. Switch between the main panel and floating reader. Supports native dragging/resizing, always-on-top, transparency, fonts, backgrounds, and restored window geometry.
- Desktop window: custom title bar, minimize, maximize, fullscreen, and 100%–200% DPI support. Windows defaults to Qt software compositing to reduce white flashes in transparent windows, without additionally disabling Chromium GPU at startup. Cover hover movement and shadow animations remain enabled. For driver troubleshooting, `QYREADER_RENDER_MODE=software` also disables Chromium GPU; `hardware` leaves the optional rendering path to Qt.
- Settings: day, eye-care, beige, and night themes, plus reopening the last item at startup.

The following entries are currently unavailable and do not create placeholder content:

- Podcast/audio import and speech transcription.
- Accounts, cloud sync, and an online bookstore.

Chapter preparation and cache management are available in the 2.x interface. Existing audio cache paths remain compatible. Old audio without content verification and tasks restored after restarting are marked for verification; check and repair them before playback with the same engine, voice, and speed.

## Recent updates

| Version | Main changes |
| --- | --- |
| [v2.2.0](release-notes/v2.2.0.md) | Adds sleep timers, Edge / Kokoro offline chapters, a voice center, backup and restore, and bulk library management, alongside the compact four-color annotation toolbar and shared playback state. |
| [v2.1.9](release-notes/v2.1.9.md) | Adds the optional Kokoro FP32 model for faster offline generation; improves warm-up, scheduling, and caching while preserving INT8, all eight voices, and existing data. |
| [v2.1.8](release-notes/v2.1.8.md) | Adds optional Kokoro offline voices, highlights and notes, reading statistics, categories, and tags using the existing interface style. |

Only the latest three versions appear here. See the [full changelog](CHANGELOG.md) or [GitHub Releases](https://github.com/superadminist/QYReader/releases) for older versions. Detailed release notes and the changelog are currently in Chinese. Each release must add `release-notes/vX.Y.Z.md` to provide readable GitHub Release notes.

## Architecture

```text
React interface (prototype/src)
        │  Single contract: prototype/src/bridge.d.ts (schemaVersion 2)
        ▼
QWebChannel / DesktopBridge (novelreader/qt_bridge.py)
        │
        ├─ Library, import, reading, and settings services
        ├─ PlaybackService ── single SpeechController
        └─ FloatingReaderService
                 │
Qt main window ──┴────── independent Qt floating window
```

The main and floating windows share the same Bridge, WebEngine profile, playback service, and TTS event consumer. The production entry point does not load Tkinter or create a hidden legacy UI instance.

## User data and privacy

Installed builds store data under the installation directory you choose in the installer:

- Library, settings, and reading progress: `<install directory>\data\library.json`
- Text cache: `<install directory>\data\cache\`
- Imported source backups: `<install directory>\data\cache\sources\`
- Audio cache: `<install directory>\data\tts_cache\`
- Optional offline models: `<install directory>\data\models\kokoro\v1.0\int8\` or the sibling `fp32\` directory. You can choose another disk directory; the path and model variant are saved in `kokoro-model.json`.
- Reading/listening statistics: `<install directory>\data\reading_stats.sqlite3`. SQLite transactions persist statistics; an unexpected exit does not add time spent offline.
- Edge connection diagnostics: `<install directory>\data\logs\edge-tts.log`. Logs rotate and do not contain book text, tokens, or full URLs.

On the first launch of an installed build, if `<install directory>\data` does not exist, the legacy `%APPDATA%\DDNovelReader` directory is copied to the new location without deleting the original. Source runs continue using that legacy directory for compatibility. Tests can use `DOUBAO_NOVEL_DATA` to select an isolated directory.

The application does not upload your library, book text, or reading progress. When you use Edge online voices for reading or preparing offline chapters, the relevant text is sent to that service as part of Edge TTS synthesis. Local SAPI5 does not require network access.

Kokoro accesses official GitHub downloads only when downloading the selected model. After installation, synthesis, previews, and playback use local files. The INT8 archive is 132,303,094 bytes with SHA256 `4c3052abaa60943a341f193888cf6abd68787dae6ab8ae5c925a706caa247e4e`; the FP32 archive is 349,906,910 bytes with SHA256 `c5f7e2d2caf082bc1d20fb70334a61d99d20b484500aad32e7cf84c128ea3298`. Extracted models occupy about 181.1 / 382.7 MiB. Models are separate from the main installer and do not need to be downloaded again after upgrading. Each variant has its own model and audio cache, with a default temporary cache limit of 500 MiB per variant. Retained offline chapters are excluded from this eviction limit until you clean them in Offline Listening; shared or currently used files remain protected. Manual imports must match the selected variant; failed validation leaves the source archive intact.

Before the new reader features first write data, the app saves `library.json.before-reader-features.bak`. Statistics are saved every five seconds and committed when playback phases change. An unexpected exit can lose the last few seconds. Existing progress is not converted into historical reading time.

Upgrading preserves the installation's `data` directory, and uninstalling keeps it by default. Settings updates preserve existing books and unknown fields. Back up `<install directory>\data` before upgrading. Do not commit real libraries, copyrighted sample books, or local caches to Git.

## Usage

1. Launch the app and import files or paste text in the content library.
2. Open an item and navigate using chapters, scrolling, or search.
3. Use the bottom playback bar to read aloud. `Ctrl+P` pauses/resumes, `Ctrl+S` stops, and `+`/`-` changes font size.
4. Open the independent floating reader using Floating Reader (悬浮朗读) or `Ctrl+Shift+F`. Closing it does not stop playback; it remains available when the main window is minimized.
5. Toggle fullscreen with `F11` or `Alt+Enter`.
6. If offline generation is slow, stop playback and open Settings → Voices & Models → Free Offline Voice Pack → Model Version. Select FP32 and download or import its approximately 350 MB package. You do not need to delete the existing INT8 model.
7. Select text and click a color dot on the nearby toolbar to highlight it, or choose Write Note (写笔记) to enter and save a note. Click an existing highlight to view, recolor, edit, or delete its note.
8. Choose Sleep Timer (睡眠定时) in the playback controls. Both windows show the same countdown; Stop at Chapter End prevents playback from continuing into the next chapter.
9. Choose Prepare Offline Listening in the reader toolbar or manage tasks in Settings → Offline Listening. Play prepared chapters with the same engine, voice, and speed.
10. Search, favorite, or preview voices in Settings → Voices & Models. Save or verify snapshots in Settings → Backup & Restore. Review the replacement scope before restoring; audio and models depend on what the selected backup contains.
11. Click Bulk Management in the library and check the selected count before changing categories, tags, or reading status.

## Development

### Requirements

- Windows 10/11.
- Python 3.10+.
- Node.js 20+ for frontend development, testing, and packaging only. Installed builds do not require Node.js.

### Install Python dependencies

```bat
install.bat
```

Equivalent manual commands:

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Build the frontend

The desktop host loads static build output and does not depend on a Vite development server. Before the first run, or after changing `prototype/src`, run:

```bat
npm.cmd --prefix prototype ci
npm.cmd --prefix prototype run build
```

The output entry point must exist at `prototype\dist\client\index.html`.

### Run the desktop app

```bat
run.bat
```

Or:

```bat
.venv\Scripts\python.exe -m novelreader.qt_main
```

`novelreader.main` remains a compatibility entry point that forwards to the same Qt application.

### Tests

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
npm.cmd --prefix prototype run test:bridge
npm.cmd --prefix prototype run test:sites
npm.cmd --prefix prototype run build
```

Long-text benchmark:

```bat
.venv\Scripts\python.exe tests\stage3_performance_qa.py
```

Benchmark Kokoro using synthetic text and an isolated model directory rather than a real library:

```bat
.venv\Scripts\python.exe tests\kokoro_performance_qa.py --model-dir "isolated-dir\models\kokoro\v1.0\int8" --output "outside-repo\kokoro-performance.json"
```

This script compares generation time, audio duration, real-time factor (RTF), and memory with 1/2/4 threads, and creates samples for all eight voices. It tests inference directly, excluding production model validation, queues, audio caching, and playback waits. An RTF above 1 means generation is slower than playback; additional prefetching cannot compensate indefinitely.

Cold-cache long-chapter validation uses the production `KokoroService`, the reader's sentence splitting, current-sentence priority, and three-sentence prefetching:

```bat
.venv\Scripts\python.exe tests\kokoro_continuity_qa.py --model-dir "isolated-dir\models\kokoro\v1.0\fp32" --output "isolated-qa-dir\cold-chapter.json" --threads 2 --simulate-playback --warm-run
```

By default, this generates 32 unique synthetic Chinese sentences. Each run creates separate data/cache directories next to the report and selects INT8 or FP32 from the model manifest. The model directory is read-only; the script does not use a real library or delete previous validation files. `--simulate-playback` waits silently for actual WAV durations while synthesis runs in the background, without opening the speakers. Reports include first-sentence waiting, model loading/validation, per-sentence waits, weighted RTF, buffered audio duration, actual generation ratio, and gaps above 300 ms. Passing the continuity threshold requires at least 20 sentences, at least 200 seconds of audio, no initial cache hits, and no gaps above 300 ms after playback starts. `--sentences 12` provides a shorter regression run but does not pass the long-chapter requirement.

Without `--simulate-playback`, the faster benchmark reports inference throughput and an optimistic virtual-consumption estimate, which cannot prove playback continuity. `--warm-run` separately reports playback of the same cached text and requires zero new synthesis calls. Assess cached playback, repeated loops, and cold chapters separately. Use a new output path for each run; detailed sentence records and WAV files remain in the report's `workspace` directory for inspection, including interrupted runs.

Avoid packaging or running other synthesis jobs during measurement. Silent simulation and playback-event checks do not establish successful MCI playback, speaker output, or perceived voice quality.

Desktop/DPI validation requires an available Windows graphical session and Node.js 20+:

```bat
.venv\Scripts\python.exe tests\stage4_desktop_qa.py --node "C:\path\to\node.exe" --screenshot-dir "C:\path\outside\repo\stage4-qa" --dpi 1,1.25,1.5,2
```

Keep QA screenshots outside the repository to avoid committing test libraries or temporary visual evidence.

## Packaging

Install Inno Setup 6, then run the script below. It checks Node.js and Inno Setup, rebuilds the offline frontend, installs the pinned PyInstaller version, and creates a fast-start build, a single-file compatibility build, and a Windows installer:

```bat
build.bat
```

For manual packaging, build the frontend, install packaging dependencies, and run:

```bat
.venv\Scripts\python.exe -m pip install -r build-requirements.txt
.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm "QYReader.spec"
```

The current version's installer path is `dist\installer\QYReader-Setup-2.2.0.exe`. The installer lets you choose the location and whether to create a desktop shortcut. It defaults to `Program Files\QYReader` and requests administrator privileges when launched. Before release, validate installation, first-launch data migration, upgrading, and data retention after uninstalling. Check WebEngine resources, importing/reading, exit cleanup, and the absence of Node, Vite development servers, or an external Python interpreter in the process tree. A successful build alone does not establish desktop validation.

Pushing to `main` triggers the GitHub Actions `Windows installer` workflow, which runs tests and packaging on a Windows runner. The installer and `SHA256SUMS.txt` are retained as build artifacts for 30 days. You can also trigger the workflow manually from GitHub Actions. Generated binaries are not committed to Git.

## Project structure

```text
QYReader/
├─ novelreader/
│  ├─ qt_main.py                 # Production Qt entry point
│  ├─ qt_host.py                 # Main/floating windows and offline WebEngine host
│  ├─ qt_bridge.py               # QWebChannel boundary and event dispatch
│  ├─ *_service.py               # Settings, library, import, reading, playback, floating services
│  ├─ book_loader.py             # Format parsers
│  ├─ storage.py                 # Existing local data/cache compatibility
│  └─ tts_engine.py              # SAPI5, Edge TTS, MCI, and SpeechController
├─ prototype/
│  ├─ src/                       # React interface and single Bridge contract
│  ├─ tests/                     # Bridge / Sites tests
│  └─ dist/client/               # Frontend build loaded by Qt
├─ tests/                        # Python, Qt, performance, and desktop validation
├─ installer/QYReader.iss        # Inno Setup installer definition
├─ requirements.txt
├─ run.bat
├─ build.bat
└─ QYReader.spec
```

## Environment limitations

- SAPI5 and speaker playback depend on the current Windows user's voice packages, COM session, and audio device. CI or a restricted desktop session cannot replace listening on a real machine.
- Edge TTS and offline fallback require separate online/offline validation.
- Dual-monitor validation requires a real second display; single-monitor geometry tests are insufficient.
- Strict verification that packaged builds need no installed Python should use a clean Windows environment without Python or Node.js.

## License

MIT License
