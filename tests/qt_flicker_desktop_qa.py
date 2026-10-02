"""Capture native desktop frames while the production library animates.

Unlike CDP screenshots/rAF timing, these samples include Qt's widget compositor.
All library writes use a temporary fixture; existing reader processes are untouched.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--frames", type=int, default=360)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    from novelreader.qt_rendering import configure_rendering
    configure_rendering()
    from PySide6.QtCore import QEvent, QPoint, QPointF, QTimer, Qt
    from PySide6.QtGui import QImage, QMouseEvent, QPainter
    from PySide6.QtWidgets import QApplication
    from novelreader.qt_host import DesktopWindow
    from ui_repair_qa import fixtures

    with tempfile.TemporaryDirectory(prefix="qyreader-flicker-") as temporary:
        root = Path(temporary)
        (root / "data").mkdir()
        os.environ["DOUBAO_NOVEL_DATA"] = str(root / "data")
        fixtures(root / "data", root)
        app = QApplication([])
        window = DesktopWindow()
        window.resize(1280, 720)
        window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        window.setWindowFlag(Qt.WindowType.WindowTransparentForInput, True)
        window.show()
        window.centerOnPrimaryScreen()
        frames, probes, captures = [], [], []
        result = {"passed": False, "capture": "QScreen native desktop", "frames": frames,
                  "hoverSamples": [],
                  "environment": {k: os.environ.get(k) for k in
                                  ("QT_QUICK_BACKEND", "QSG_RHI_BACKEND", "QTWEBENGINE_CHROMIUM_FLAGS")}}
        timer = QTimer()
        started = 0

        def finish(error=None):
            timer.stop()
            if error:
                result["error"] = error
            else:
                # A missing content frame loses most of several independent
                # cover/title probes together; normal hover only moves 4 px.
                baseline = [max(f["ink"][i] for f in frames) for i in range(len(probes))]
                result["baselineInk"] = baseline
                available = all(value > 8 for value in baseline)
                bad = [i for i, frame in enumerate(frames)
                       if sum(ink < base * .35 for ink, base in zip(frame["ink"], baseline)) >= 3]
                result.update({"captureAvailable": available, "missingContentFrames": bad,
                               "passed": available and not bad, "frameCount": len(frames)})
                for i in bad[:12]:
                    captures[i].save(str(output / f"missing-{i:04d}.png"))
                contact = QImage(1280, 720, QImage.Format.Format_RGB32)
                contact.fill(Qt.GlobalColor.white)
                painter = QPainter(contact)
                indices = sorted(set(bad[:6] + [round(i * (len(captures)-1) / 11) for i in range(12)]))[:12]
                for slot, i in enumerate(indices):
                    painter.drawImage(slot % 4 * 320, slot // 4 * 240,
                                      captures[i].scaled(320, 220))
                    painter.drawText(slot % 4 * 320 + 5, slot // 4 * 240 + 236, str(i))
                painter.end()
                contact.save(str(output / "contact.png"))
                captures[-1].save(str(output / "last.png"))
            (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            window.requestApplicationExit()
            app.quit()

        def sample():
            try:
                index = len(frames)
                # Mouse events enter and leave every import/book card during
                # continuous native captures, not after the animation settles.
                if index % 15 == 0:
                    target = probes[(index // 15) % len(probes)]
                    point = QPoint(round(target["x"]), round(target["y"]))
                    target_widget = window._view.focusProxy() or window._view
                    local = target_widget.mapFrom(window._view, point)
                    event = QMouseEvent(QEvent.Type.MouseMove, QPointF(local),
                                        QPointF(target_widget.mapToGlobal(local)),
                                        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                                        Qt.KeyboardModifier.NoModifier)
                    QApplication.sendEvent(target_widget, event)
                    window._page.runJavaScript("document.querySelectorAll('.book-card:hover').length",
                                               lambda value: result["hoverSamples"].append(value))
                origin = window.mapToGlobal(QPoint(0, 0))
                image = window.screen().grabWindow(0, origin.x(), origin.y(),
                                                  window.width(), window.height()).toImage()
                if image.isNull():
                    finish("Native desktop capture unavailable")
                    return
                image = image.scaled(window.width(), window.height())
                inks = []
                for probe in probes:
                    # Count dark/textured pixels well inside content; movement
                    # and antialiasing cannot explain complete disappearance.
                    x, y = round(probe["x"]), round(probe["y"])
                    inks.append(sum(image.pixelColor(x + dx, y + dy).lightness() < 190
                                    for dx in range(-12, 13, 3) for dy in range(-12, 13, 3)))
                frames.append({"ms": round((time.monotonic()-started)*1000, 2), "ink": inks})
                captures.append(image.scaled(640, 360))
                if len(frames) >= args.frames:
                    finish()
            except Exception as exc:
                finish(str(exc))

        def ready(raw):
            nonlocal started
            try:
                probes.extend(json.loads(raw))
                if len(probes) < 4:
                    finish("Library fixture was not rendered")
                    return
                started = time.monotonic()
                timer.timeout.connect(sample)
                timer.start(16)
            except Exception as exc:
                finish(str(exc))

        def start():
            window._page.runJavaScript("JSON.stringify([...document.querySelectorAll('.cover-wrap')].slice(0,4).map(e=>{const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+45}}))", ready)

        window._view.loadFinished.connect(lambda ok: QTimer.singleShot(1800, start) if ok else finish("Page failed"))
        QTimer.singleShot(25000, lambda: finish("Timed out"))
        app.exec()
        print(json.dumps({k: v for k, v in result.items() if k != "frames"}))
        return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
