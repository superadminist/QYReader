"""Explicit GUI gate: native alpha guard must work without any CSS rounding."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from novelreader.qt_rendering import configure_rendering

configure_rendering()

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QMainWindow
from novelreader.qt_corners import RoundedWebEngineView


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    app = QApplication([])
    window = QMainWindow()
    window.setWindowFlags(Qt.WindowType.FramelessWindowHint)
    window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    view = RoundedWebEngineView(window, "main")
    view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    view.page().setBackgroundColor(QColor(0, 0, 0, 0))
    window.setCentralWidget(view)
    result = {"cssRounding": False, "checks": [], "passed": False}

    def exercise():
        try:
            for surface in ("main", "floating"):
                view._corner_clip._surface = surface
                for width, height in ((800, 600), (1001, 711), (640, 481), (901, 631)):
                    window.resize(width, height)
                    app.processEvents()
                    # No wait for Chromium's viewport reflow; Qt must clip now.
                    view._corner_clip.refresh()
                    image = view.grab().toImage()
                    points = ((0, 0), (image.width() - 1, 0),
                              (0, image.height() - 1), (image.width() - 1, image.height() - 1))
                    alpha = [image.pixelColor(x, y).alpha() for x, y in points]
                    center = image.pixelColor(image.width() // 2, image.height() // 2)
                    edge = round((34 if surface == "floating" else 24) * image.devicePixelRatio())
                    aa = sum(0 < image.pixelColor(x, y).alpha() < 255
                             for x in range(edge) for y in range(edge))
                    check = {"surface": surface, "logicalSize": [width, height],
                             "dpr": image.devicePixelRatio(), "corners": alpha,
                             "centerAlpha": center.alpha(), "antialiasedPixels": aa}
                    result["checks"].append(check)
                    assert alpha == [0] * 4 and center.alpha() == 255 and aa > 0, check
            view._corner_clip._surface = "main"
            window.showMaximized()
            app.processEvents()
            view._corner_clip.refresh()
            image = view.grab().toImage()
            alpha = image.pixelColor(0, 0).alpha()
            result["maximizedCornerAlpha"] = alpha
            assert alpha == 255, alpha
            result["passed"] = True
        except Exception as error:
            result["error"] = str(error)
        finally:
            Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
            window.close()
            app.quit()

    view.loadFinished.connect(lambda ok: QTimer.singleShot(350, exercise) if ok else app.exit(2))
    window.resize(800, 600)
    window.show()
    view.setHtml("<style>html,body{margin:0;width:100%;height:100%;background:#c86432}</style>Native alpha test")
    QTimer.singleShot(15000, lambda: app.exit(3))
    app.exec()
    print(json.dumps(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
