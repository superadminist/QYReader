# Prototype Instructions

Run the local server yourself and open the preview in the browser available to this environment. Do not give the user server-start instructions when you can run it.

Before making substantial visual changes, use the Product Design plugin's `get-context` skill when the visual source is unclear or no longer matches the current goal. When the user gives durable prototype-specific design feedback, preferences, or decisions, record them in `AGENTS.md`.

When implementing from a selected generated mock, treat that image as the source of truth for layout, component anatomy, density, spacing, color, typography, visible content, and hierarchy.

Build app UI in `src/`. Keep `.openai/hosting.json`, `worker/index.js`, `scripts/prepare-sites-build.mjs`, and `tests/sites-worker.test.mjs` intact so the same local prototype can be handed to Sites. Before a Sites handoff, run `npm run build` and `npm run test:sites`; the build must leave `dist/client/index.html`, `dist/server/index.js`, and `dist/.openai/hosting.json`.

## Confirmed design direction

- Content-library import cards are ordered left to right: 导入文件, 粘贴文本, 网页链接, 播客 / 音频.
- The React UI in this directory is the production Qt WebEngine frontend as well as the browser prototype; contract changes must update both Qt and demo transports and rebuild `dist/client`.
- Match the supplied `key-ui` screenshots as a macOS-style desktop reading experience.
- Content-library cards use an app-styled Chinese context menu for management actions; never expose WebEngine's generic browser menu on a book card. Label removal by its exact effect and confirm it before changing the library.
- Each reading theme applies to the whole main interface: title bar, rail, directory, toolbar, reading canvas, player, library and dialogs share one neutral surface family and one accent palette. Keep only a subtle lighter reading-paper layer; do not mix blue-white chrome with green or beige reading areas.
- The user rejected the all-green eye-protection interface. Day and eye-protection modes keep a neutral gray-white chassis and the original blue-purple brand buttons/selection accents; eye protection uses a softer neutral reading background, without recoloring the whole window or controls green.
- Avoid redundant full-window clip-path and CSS backdrop-filter composition on the translucent desktop host. Preserve the 22px/30px antialiased border-radius with overflow clipping and the floating two-pixel inset.
- Include the content library, reading view, chapter directory, import-text dialog, playback bar, and bilingual floating reader.
- The floating reader must be movable and freely resizable from its lower-right corner.
- Use an explicit visible lower-right resize handle with pointer-drag behavior; do not rely only on the browser's subtle native resize affordance.
- Treat the floating reader as the primary product surface: preserve the current sentence first, progressively hide the previous and then next sentence when space is constrained, and never overlay the title, error, or controls on text.
- The floating reader uses direct body-area mouse-wheel font sizing (14–40 px), background-only opacity (0–100%), and an independently configurable readable text color.
- The main window minimizes to the system tray; the floating window remains independent and must not add a second taskbar button.
- Keep all built-in Edge neural voices and append every locally enumerated Windows SAPI voice in the settings center.
- Drive floating-reader lyrics from the shared audio-start event: keep the current sentence visually centered and use a short vertical slide/fade when the sentence changes; sentence completion alone must not advance the visible lyric.
- Switching from the main reader into floating mode hides the main window; the floating header's return-to-main icon closes floating mode and restores the main window without interrupting speech. Repeated Play/Pause clicks on either surface must not advance lyrics ahead of confirmed audio start/resume.
- The main playback bar exposes a one-click return-to-current-sentence action. It smoothly centers the shared audio-start sentence after manual scrolling, loads its text window first when necessary, and never navigates or changes playback position by itself.
- Warm the one existing speech controller for the bound reader position; preloading must never create a second playback controller or a second playback state.
- On Windows, let Qt select hardware acceleration for the transparent Qt/WebEngine surface; retain `QYREADER_RENDER_MODE=software` as an explicit driver-compatibility override. Keep the 22px CSS border-radius/overflow clipping and a native-size antialiased alpha corner guard so live resize does not depend on Chromium's delayed viewport. Never apply a binary native window region that creates jagged corner pixels. Keep maximized/fullscreen edges square, and verify native resize/restore and playback in the real desktop host after changing this composition path. Never apply a native region to the floating window.
- Main-window normal state remains visibly rounded, while maximized and fullscreen states remain square and flush with the screen edge.
- Give the floating surface a fuller 30px anti-aliased radius with a two-pixel transparent inset so boundary pixels are not clipped; its configurable background opacity must remain independent from text and controls.
- Keep the floating reader content-only while the pointer is away: fully collapse the top title strip and bottom controls so they consume no space, then restore them on hover or keyboard focus. Pointer-less/touch environments keep the controls visible.
- Keep the floating footer compact: do not show the bilingual toggle, keep the background-opacity slider near 108px at the normal desktop size, and use the former right-side control area for a subtle hover/focus bottom-right resize grip backed by native system resize.
- Show Edge network trouble as a small animated Wi-Fi status instead of a large error panel: place it beside the chapter/status copy in the main player and in a dedicated lower-right status row above the floating controls so it never overlays reading text.
- In the normal 448x295 floating size, pointer-away state shows previous, current, and next sentences together; pointer-hover state shows the title and playback controls and may reduce the lyric to the current sentence to protect it from overlap.
- Make that pointer-driven display mode a persisted setting that defaults on. When it is off, keep the title, current sentence, and playback controls visible. Native Qt enter/leave events are authoritative so WebEngine cannot leave the hover state stuck after the pointer exits.
- Floating settings save independently per field. The color picker is always usable and selecting a color immediately enters custom mode; auto color remains explicit. The first body-wheel font change immediately disables and persists reader-font following, and Chromium scrollbars stay hidden without removing programmatic overflow.
- Use Windows-style minimize, maximize/restore, and close controls on the far right of the main 54px title bar; keep search and avatar immediately to their left and the app title visually centered. Minimize goes to the tray, maximize state changes the icon to restore, and blank-title-bar drag/double-click remains available. The persisted settings switch decides whether the close button exits or minimizes to tray; the tray menu's Exit action always exits.
- Keep modal overlays on Qt WebEngine's stable composition path: use a translucent solid scrim rather than a full-window `backdrop-filter`, which can disappear for single frames while the reader repaints.
- Keep software updates inside the settings center: automatically check the latest stable GitHub Release when enabled, allow manual checks and version skipping, download only the exact versioned Windows installer plus `SHA256SUMS.txt`, verify SHA256 before enabling installation, and never install silently without a user action.
- Edge continuation must keep the selected neural voice while audio is still being prepared: start ordered multi-sentence lookahead alongside the current-sentence prime, never duplicate an in-flight synthesis request, and never switch to SAPI merely because a healthy prefetch is pending. If Edge synthesis actually fails, a session may fall back once but must not flap between Edge and SAPI afterward.
- Keep Edge playback current-sentence-first: cap lookahead at 3 sentences, serialize network synthesis with foreground playback priority and failure backoff, retry one transient failure with the same voice and rate, and reuse a small bounded set of recent successful sentence audio.
