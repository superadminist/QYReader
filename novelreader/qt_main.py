# -*- coding: utf-8 -*-
"""Independent entry point for the phase-1 Qt desktop host."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    # Must precede QApplication and the first QWebEngine/QQuick surface.
    from .qt_rendering import configure_rendering
    configure_rendering()
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        from .paths import ensure_data_dir
        from .qt_host import DesktopWindow, frontend_index_path
    except ImportError as exc:
        print(
            "[错误] 缺少 PySide6/QtWebEngine，"
            f"请先安装 requirements.txt 中的依赖：{exc}",
            file=sys.stderr,
        )
        return 2

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("启远阅读")
    app.setOrganizationName("QYReader")

    try:
        data_root = ensure_data_dir()
    except OSError as exc:
        QMessageBox.critical(
            None,
            "启远阅读",
            "无法在安装目录创建或迁移 data 数据文件夹。\n"
            "请重新安装到当前用户拥有写入权限的路径。\n\n"
            f"{exc}",
        )
        return 4

    try:
        from .tts_engine import configure_edge_diagnostics
        configure_edge_diagnostics(data_root)
    except OSError:
        # Diagnostics must never prevent the reader from starting. Playback
        # events still carry the same sanitized failure details in memory.
        pass

    index_path = frontend_index_path()
    if not index_path.is_file():
        QMessageBox.critical(
            None,
            "启远阅读",
            "未找到前端构建文件。请先构建 prototype/dist/client/index.html。",
        )
        return 3

    window = DesktopWindow()
    window.centerOnPrimaryScreen()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
