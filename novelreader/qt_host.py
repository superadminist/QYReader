# -*- coding: utf-8 -*-
"""Frameless PySide6 host for the production React frontend."""

from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QEvent, QFile, QIODevice, QRect, QStandardPaths, QTimer, Qt, QUrl, QUrlQuery
from PySide6.QtGui import QAction, QCloseEvent, QColor, QDesktopServices, QGuiApplication, QIcon
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineScript,
    QWebEngineSettings,
    QWebEngineUrlRequestInfo,
    QWebEngineUrlRequestInterceptor,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMenu, QMessageBox, QSystemTrayIcon

from .book_loader import SUPPORTED_EXTS
from .library_service import LibraryQueryService
from .qt_corners import RoundedWebEngineView
from .playback_service import PlaybackService
from .qt_bridge import DesktopBridge
from .reader_service import ReaderService
from .tts_engine import SpeechController


def _qa_trace(message: str) -> None:
    if os.environ.get("DD_QA_TRACE"):
        print(f"[DD_QA_TRACE] {message}", flush=True)


class OfflineRequestInterceptor(QWebEngineUrlRequestInterceptor):
    """Prevent the packaged UI from depending on remote resources."""

    def interceptRequest(self, info: QWebEngineUrlRequestInfo) -> None:
        if info.requestUrl().scheme().lower() in {"http", "https", "ws", "wss"}:
            info.block(True)


def application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[1]


def frontend_index_path() -> Path:
    root = application_root()
    candidates = (
        root / "prototype" / "dist" / "client" / "index.html",
        root / "frontend" / "index.html",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


_GEOMETRY_PATTERN = re.compile(r"^(\d+)x(\d+)([+-]\d+)([+-]\d+)$")


def clamp_floating_geometry(value: str, work_areas: list[QRect]) -> QRect:
    """Normalize a saved geometry into one of the available screen work areas."""
    areas = [QRect(area) for area in work_areas if area.isValid()]
    if not areas:
        areas = [QRect(0, 0, 1280, 720)]
    primary = areas[0]
    match = _GEOMETRY_PATTERN.fullmatch(str(value or ""))
    if match:
        width, height, x, y = (int(part) for part in match.groups())
    else:
        width, height = 560, 300
        x = primary.right() - width - 31
        y = primary.bottom() - height - 31
    target = next(
        (area for area in areas if area.contains(x + width // 2, y + height // 2)),
        None,
    )
    if target is None:
        candidate = QRect(x, y, max(1, width), max(1, height))
        target = max(
            areas,
            key=lambda area: area.intersected(candidate).width()
            * area.intersected(candidate).height(),
        )
        if not target.intersects(candidate):
            target = primary
    width = min(max(360, width), target.width())
    height = min(max(220, height), target.height())
    x = min(max(x, target.left()), target.right() - width + 1)
    y = min(max(y, target.top()), target.bottom() - height + 1)
    return QRect(x, y, width, height)


def qt_geometry_string(rect: QRect) -> str:
    x = f"+{rect.x()}" if rect.x() >= 0 else str(rect.x())
    y = f"+{rect.y()}" if rect.y() >= 0 else str(rect.y())
    return f"{rect.width()}x{rect.height()}{x}{y}"


def floating_frontend_url() -> QUrl:
    url = QUrl.fromLocalFile(os.fspath(frontend_index_path()))
    query = QUrlQuery()
    query.addQueryItem("surface", "floating")
    url.setQuery(query)
    return url


def _inject_qwebchannel_script(page: QWebEnginePage) -> None:
    resource = QFile(":/qtwebchannel/qwebchannel.js")
    if not resource.open(QIODevice.OpenModeFlag.ReadOnly):
        return
    script = QWebEngineScript()
    script.setName("qwebchannel.js")
    script.setSourceCode(bytes(resource.readAll()).decode("utf-8"))
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    script.setRunsOnSubFrames(False)
    page.scripts().insert(script)


def _configure_main_web_view(view: QWebEngineView, page: QWebEnginePage) -> None:
    """Keep the page transparent for CSS and the native alpha corner guard."""
    view.setObjectName("mainWebView")
    page.setBackgroundColor(QColor(0, 0, 0, 0))
    view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    view.setStyleSheet("QWebEngineView#mainWebView { background: transparent; }")


def _configure_floating_web_view(view: QWebEngineView, page: QWebEnginePage) -> None:
    """Allow the floating surface to own its user-configurable opacity."""
    view.setObjectName("floatingWebView")
    page.setBackgroundColor(QColor(0, 0, 0, 0))
    view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    view.setStyleSheet("QWebEngineView#floatingWebView { background: transparent; }")


def _set_windows_corner_preference(window: QMainWindow, rounded: bool) -> bool:
    if sys.platform != "win32":
        return False
    try:
        preference = ctypes.c_int(2 if rounded else 1)
        result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(int(window.winId())),
            33,
            ctypes.byref(preference),
            ctypes.sizeof(preference),
        )
        return result == 0
    except (AttributeError, OSError, ValueError):
        return False


def _apply_window_corners(
    window: QMainWindow,
    radius: int,
    rounded: bool,
) -> None:
    # resizeEvent fires continuously while the user drags a window edge. On a
    # translucent WebEngine top-level window, repeatedly clearing the mask and
    # asking DWM to re-apply the same preference invalidates the compositor
    # surface and can make the entire window disappear for a frame. Corner mode
    # changes only when entering/leaving maximized or fullscreen state.
    corner_state = (bool(rounded), int(radius))
    if getattr(window, "_dd_corner_state", None) == corner_state:
        return
    window._dd_corner_state = corner_state
    # CSS and the native alpha guard clip at every size; never create a binary
    # native region that becomes stale halfway through a system resize.
    window.clearMask()
    _set_windows_corner_preference(window, rounded)


class _WindowRenderLifecycle:
    """Keep Chromium layout and the native resize loop on the same lifecycle."""

    def _init_render_lifecycle(self, surface: str) -> None:
        self._surface = surface
        self._system_interaction_active = False
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._sync_web_surface)

    def nativeEvent(self, event_type, message):
        if sys.platform == "win32" and hasattr(self, "_render_timer"):
            native_message = wintypes.MSG.from_address(int(message)).message
            if native_message == 0x0231:  # WM_ENTERSIZEMOVE
                self._set_system_interaction(True)
            elif native_message == 0x0232:  # WM_EXITSIZEMOVE
                self._set_system_interaction(False)
        return super().nativeEvent(event_type, message)

    def hideEvent(self, event) -> None:
        self._cancel_window_interaction()
        super().hideEvent(event)

    def _cancel_window_interaction(self) -> None:
        if getattr(self, "_system_interaction_active", False):
            self._set_system_interaction(False)
        for name in ("_geometry_timer", "_render_timer"):
            timer = getattr(self, name, None)
            if timer is not None:
                timer.stop()

    def _set_system_interaction(self, active: bool) -> None:
        if self._system_interaction_active == active:
            return
        self._system_interaction_active = active
        geometry_timer = getattr(self, "_geometry_timer", None)
        if geometry_timer is not None:
            geometry_timer.stop()
        signal = getattr(getattr(self, "bridge", None), "windowInteractionChanged", None)
        if signal is not None:
            signal.emit(self._surface, active)
        _qa_trace(f"window-interaction:{self._surface}:{active}")
        if not active:
            if geometry_timer is not None:
                geometry_timer.start()
            self._schedule_surface_sync()

    def _schedule_surface_sync(self) -> None:
        if hasattr(self, "_render_timer") and not self._system_interaction_active:
            self._render_timer.start(0)

    def _sync_web_surface(self) -> None:
        if not hasattr(self, "_view") or self._system_interaction_active:
            return
        layout = self.layout()
        if layout is not None:
            layout.activate()
        # Both hosts have only a central web view, without menus or status bars.
        # Correct stale backing-store dimensions after native state transitions.
        rect = self.contentsRect()
        if self._view.geometry() != rect:
            self._view.setGeometry(rect)
        # Paint only the web view. Invalidating the translucent parent too
        # clears its entire backing store before Chromium supplies the next
        # frame; that can expose the desktop during ordinary interaction.
        self._view.update()
        # Chromium sends resize once the real viewport has changed. A synthetic
        # resize here runs against the previous viewport and duplicates layout.
        if os.environ.get("DD_QA_TRACE"):
            _qa_trace(f"window-render:{self._surface}:client={rect}:view={self._view.geometry()}:state={self.windowState()}")
            self._page.runJavaScript(
                "JSON.stringify({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})",
                lambda viewport: _qa_trace(f"window-viewport:{self._surface}:{viewport}"),
            )


class FloatingReaderWindow(_WindowRenderLifecycle, QMainWindow):
    """Independent frameless React window sharing the main window's bridge."""

    def __init__(self, bridge: DesktopBridge, profile: QWebEngineProfile):
        super().__init__(None)
        self._init_render_lifecycle("floating")
        self.bridge = bridge
        self._profile = profile
        self._allow_close = False
        self._applying_geometry_clamp = False
        self._settings: dict = {}
        self.setWindowTitle("启远阅读 - 悬浮朗读")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(360, 220)

        self._view = RoundedWebEngineView(self, "floating")
        self._page = QWebEnginePage(profile, self._view)
        self._view.setPage(self._page)
        _configure_floating_web_view(self._view, self._page)
        self._page.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,
            True,
        )
        _inject_qwebchannel_script(self._page)
        self._channel = QWebChannel(self._page)
        self._channel.registerObject("ddBridge", bridge)
        self._page.setWebChannel(self._channel)
        self.setCentralWidget(self._view)

        self._view.setUrl(floating_frontend_url())

        self._geometry_timer = QTimer(self)
        self._geometry_timer.setSingleShot(True)
        self._geometry_timer.setInterval(180)
        self._geometry_timer.timeout.connect(self._persist_geometry)

    def show_with_settings(self, settings: dict) -> None:
        self._settings = dict(settings)
        rect = clamp_floating_geometry(
            settings.get("geometry", ""), self._available_work_areas()
        )
        self.setGeometry(rect)
        self.apply_settings(settings)
        self.bridge.floatingPointerChanged.emit(False)
        self.show()
        self._schedule_surface_sync()
        _apply_window_corners(self, 30, True)
        if settings.get("topmost", True):
            self.raise_()
        self._persist_geometry()

    def apply_settings(self, settings: dict) -> None:
        self._settings = dict(settings)
        was_visible = self.isVisible()
        topmost = bool(settings.get("topmost", True))
        if bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) == topmost:
            return
        self.setWindowFlag(
            Qt.WindowType.WindowStaysOnTopHint,
            topmost,
        )
        self._dd_corner_state = None  # Window flags may create a new HWND.
        if was_visible:
            self.show()
            QTimer.singleShot(0, lambda: _apply_window_corners(self, 30, True))
            self._schedule_surface_sync()

    def ensure_visible_after_main_minimize(self) -> None:
        if self.isVisible():
            self.show()
            if self._settings.get("topmost", True):
                self.raise_()

    def shutdown(self) -> None:
        self._cancel_window_interaction()
        if self.isVisible():
            self._persist_geometry()
        self._allow_close = True
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._cancel_window_interaction()
        if self._allow_close:
            event.accept()
            return
        self._geometry_timer.stop()
        self.bridge.floatingPointerChanged.emit(False)
        self._persist_geometry()
        self.hide()
        event.ignore()
        self.bridge.floatingWindowClosed()

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.bridge.floatingPointerChanged.emit(True)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.bridge.floatingPointerChanged.emit(False)

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        if (
            hasattr(self, "_geometry_timer")
            and not self._applying_geometry_clamp
            and not self._system_interaction_active
        ):
            self._geometry_timer.start()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not hasattr(self, "_render_timer"):
            return
        _apply_window_corners(self, 30, True)
        if (
            hasattr(self, "_geometry_timer")
            and not self._applying_geometry_clamp
            and not self._system_interaction_active
        ):
            self._geometry_timer.start()
        self._schedule_surface_sync()

    def _persist_geometry(self) -> None:
        if getattr(self, "_system_interaction_active", False):
            return
        rect = clamp_floating_geometry(
            qt_geometry_string(self.geometry()), self._available_work_areas()
        )
        if rect != self.geometry():
            self._applying_geometry_clamp = True
            try:
                self.setGeometry(rect)
            finally:
                self._applying_geometry_clamp = False
        self.bridge.floatingGeometryChanged(qt_geometry_string(rect))

    def _available_work_areas(self) -> list[QRect]:
        screen = self.screen()
        screens = screen.virtualSiblings() if screen is not None else QGuiApplication.screens()
        return [item.availableGeometry() for item in screens]


class DesktopWindow(_WindowRenderLifecycle, QMainWindow):
    def __init__(self, library: LibraryQueryService | None = None):
        super().__init__()
        self._init_render_lifecycle("main")
        _qa_trace("desktop-window:start")
        self.setWindowTitle("启远阅读")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        # Windows 10 does not honor DWMWA_WINDOW_CORNER_PREFERENCE.  Its
        # binary QRegion mask leaves stair-stepped black triangles around a
        # frameless window, so let the transparent WebEngine/CSS surface own
        # the single anti-aliased clip instead.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("QMainWindow { background: transparent; }")
        self.setMinimumSize(960, 620)
        self._corner_timer = QTimer(self)
        self._corner_timer.setSingleShot(True)
        self._corner_timer.setInterval(140)
        self._corner_timer.timeout.connect(self._sync_window_corners)
        self.resize(1280, 720)
        self._exit_requested = False
        self._tray: QSystemTrayIcon | None = None

        icon_path = application_root() / "assets" / "app.ico"
        if icon_path.is_file():
            self.setWindowIcon(QIcon(os.fspath(icon_path)))

        # Create the view first so its page is destroyed before the custom
        # profile owned by this window.
        self._view = RoundedWebEngineView(self, "main")
        _qa_trace("desktop-window:view-created")
        self._profile = QWebEngineProfile(self)
        self._fullscreen_restore_maximized = False
        self._interceptor = OfflineRequestInterceptor(self._profile)
        self._profile.setUrlRequestInterceptor(self._interceptor)

        self._page = QWebEnginePage(self._profile, self._view)
        _qa_trace("desktop-window:page-created")
        self._view.setPage(self._page)
        _configure_main_web_view(self._view, self._page)
        self._page.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,
            True,
        )

        self._inject_qwebchannel_script()
        library = library or LibraryQueryService()
        self._speech = SpeechController()
        _qa_trace("desktop-window:speech-created")
        self._playback = PlaybackService(self._speech)
        self._reader = ReaderService(library.path, deferred_progress=True)
        self.bridge = DesktopBridge(
            self,
            library,
            reader=self._reader,
            playback=self._playback,
            file_picker=self._select_import_files,
        )
        self._setup_system_tray()
        _qa_trace("desktop-window:bridge-created")
        self._floating_window: FloatingReaderWindow | None = None
        self._channel = QWebChannel(self._page)
        self._channel.registerObject("ddBridge", self.bridge)
        self._page.setWebChannel(self._channel)
        _qa_trace("desktop-window:channel-ready")

        self.setCentralWidget(self._view)
        self._load_error_shown = False
        self._view.loadFinished.connect(self._handle_load_finished)
        index_path = frontend_index_path()
        _qa_trace(f"desktop-window:load:{index_path}:{index_path.is_file()}")
        self._view.setUrl(QUrl.fromLocalFile(os.fspath(index_path)))

    def _handle_load_finished(self, succeeded: bool) -> None:
        _qa_trace(f"desktop-window:load-finished:{succeeded}:{self._view.url().toString()}")
        if succeeded or self._load_error_shown:
            return
        self._load_error_shown = True
        QMessageBox.critical(
            self,
            "启远阅读",
            "前端界面加载失败。请检查 prototype/dist/client 构建文件是否完整。",
        )

    def _inject_qwebchannel_script(self) -> None:
        _inject_qwebchannel_script(self._page)

    def centerOnPrimaryScreen(self) -> None:
        screen = self.screen()
        if screen is None:
            return
        available = screen.availableGeometry()
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    def _setup_system_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon = self.windowIcon()
        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip("启远阅读")
        menu = QMenu(self)
        self._tray_menu = menu
        self._tray_show_action = QAction("显示主界面", menu)
        self._tray_show_action.triggered.connect(self.restoreFromTray)
        self._tray_floating_action = QAction("显示悬浮朗读", menu)
        self._tray_floating_action.triggered.connect(self._toggle_floating_from_tray)
        self._tray_exit_action = QAction("退出", menu)
        self._tray_exit_action.triggered.connect(self.requestApplicationExit)
        menu.addAction(self._tray_show_action)
        menu.addAction(self._tray_floating_action)
        menu.addSeparator()
        menu.addAction(self._tray_exit_action)
        menu.aboutToShow.connect(self._refresh_tray_menu)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._handle_tray_activation)
        self._tray.show()

    def _refresh_tray_menu(self) -> None:
        if not hasattr(self, "_tray_floating_action"):
            return
        visible = bool(self._floating_window and self._floating_window.isVisible())
        self._tray_floating_action.setText("隐藏悬浮朗读" if visible else "显示悬浮朗读")
        identity = self._playback.session_identity()
        self._tray_floating_action.setEnabled(visible or bool(identity.get("sessionId")))

    def _handle_tray_activation(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.restoreFromTray()

    def _toggle_floating_from_tray(self) -> None:
        if self._floating_window is not None and self._floating_window.isVisible():
            self.closeFloatingReaderWindow()
            return
        self.bridge.showFloatingReader()

    def minimizeToTray(self) -> None:
        if self._tray is None or not self._tray.isVisible():
            self.showMinimized()
            return
        self.hide()

    def restoreFromTray(self) -> None:
        self.restoreNormalWindow()
        self.raise_()
        self.activateWindow()
        self._schedule_surface_sync()

    def restoreNormalWindow(self) -> None:
        self.showNormal()
        if sys.platform == "win32" and self.isMaximized():
            # Some translucent frameless Qt windows retain WS_MAXIMIZE after
            # QWidget.showNormal(). Restore the exact top-level HWND once;
            # Windows will use its saved normal placement and notify Qt.
            ctypes.windll.user32.ShowWindow(ctypes.c_void_p(int(self.winId())), 9)
            self.setWindowState(Qt.WindowState.WindowNoState)
            self.bridge.emitWindowState()
        self._schedule_surface_sync()

    def hideMainForFloating(self) -> None:
        self.hide()

    def requestApplicationExit(self) -> None:
        self._exit_requested = True
        self.close()

    def openExternalUrl(self, url: str) -> bool:
        return bool(QDesktopServices.openUrl(QUrl(url)))

    def launchUpdateInstaller(self, path: str) -> bool:
        installer = Path(path)
        if os.name != "nt" or not installer.is_file() or installer.suffix.lower() != ".exe":
            return False
        os.startfile(os.fspath(installer))
        QTimer.singleShot(500, self.requestApplicationExit)
        return True

    def _select_import_files(self) -> list[str]:
        patterns = " ".join(f"*{suffix}" for suffix in sorted(SUPPORTED_EXTS))
        try:
            saved_directory = self.bridge._app.import_directory()
        except Exception:
            saved_directory = ""
        directory = Path(saved_directory) if saved_directory else None
        if directory is None or not directory.is_dir():
            documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
            directory = Path(documents) if documents and Path(documents).is_dir() else Path.home()
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "选择要加入书架的小说（可多选）",
            os.fspath(directory),
            f"支持的小说格式 ({patterns});;所有文件 (*)",
        )
        if paths:
            try:
                self.bridge._app.record_import_directory(os.fspath(Path(paths[0]).parent))
            except Exception:
                # Preference persistence must not reject files already selected.
                _qa_trace("import-directory:save-failed")
        return paths

    def revealSourceFile(self, path: str) -> bool:
        source = Path(path).resolve()
        if not source.is_file():
            return False
        if sys.platform == "win32":
            try:
                subprocess.Popen(["explorer.exe", "/select,", os.fspath(source)])
                return True
            except OSError:
                return False
        return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(os.fspath(source.parent))))

    def showFloatingReaderWindow(self, settings: dict) -> None:
        if self._floating_window is None:
            self._floating_window = FloatingReaderWindow(self.bridge, self._profile)
        self._floating_window.show_with_settings(settings)

    def closeFloatingReaderWindow(self) -> None:
        if self._floating_window is not None and self._floating_window.isVisible():
            self._floating_window.close()

    def applyFloatingReaderSettings(self, settings: dict) -> None:
        if self._floating_window is not None:
            self._floating_window.apply_settings(settings)

    def floatingWindowHandle(self):
        if self._floating_window is None or not self._floating_window.isVisible():
            return None
        return self._floating_window.windowHandle()

    def toggleFullscreenWindow(self) -> None:
        if self.isFullScreen():
            if self._fullscreen_restore_maximized:
                self.showMaximized()
            else:
                self.restoreNormalWindow()
            return
        self._fullscreen_restore_maximized = self.isMaximized()
        self.showFullScreen()

    def shutdownFloatingReaderWindow(self) -> None:
        if self._floating_window is None:
            return
        window = self._floating_window
        self._floating_window = None
        window.shutdown()
        window.deleteLater()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._cancel_window_interaction()
        self._exit_requested = True
        if self._tray is not None:
            self._tray.hide()
            self._tray.deleteLater()
        if hasattr(self, "bridge"):
            self.bridge.shutdown()
        super().closeEvent(event)
        app = QApplication.instance()
        if app is not None:
            QTimer.singleShot(0, app.quit)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "bridge"):
            QTimer.singleShot(0, self._sync_window_corners)
            self._schedule_surface_sync()
            self.bridge.emitWindowState()
            if self.isMinimized() and self._floating_window is not None:
                self._floating_window.ensure_visible_after_main_minimize()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._schedule_surface_sync()
        if not hasattr(self, "_corner_timer"):
            return
        if self.isMaximized() or self.isFullScreen():
            self._corner_timer.stop()
            self._sync_window_corners()
            return
        self._corner_timer.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._sync_window_corners)
        self._schedule_surface_sync()

    def _sync_window_corners(self) -> None:
        rounded = not self.isMaximized() and not self.isFullScreen()
        _apply_window_corners(self, 22, rounded)
