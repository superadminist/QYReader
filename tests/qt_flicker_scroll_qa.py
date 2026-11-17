"""Detect whole-window white flash while the library scrolls on the hardware path.

Differs from qt_flicker_desktop_qa.py in two ways:
1. The trigger is continuous library scrolling (scrollTop churn via runJavaScript),
   not hover enter/leave. The user reported the flash appears during scrolling.
2. Detection counts ink (dark pixels) across the WHOLE window, not four probe
   points. A whole-window white flash drops total ink toward zero for one or more
   frames, which four probes may miss when the blank region misses the probes.

Capture is still native QScreen.grabWindow so the Qt widget compositor is included;
CDP-only screenshots never show a backing-store handoff gap.
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
    parser.add_argument("--frames", type=int, default=720)
    parser.add_argument("--scroll-step", type=int, default=90,
                        help="scrollTop delta injected per scroll tick")
    parser.add_argument("--ink-threshold", type=float, default=0.18,
                        help="fraction of baseline whole-window ink below which a frame counts as flash")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)

    from novelreader.qt_rendering import configure_rendering
    configured = configure_rendering()
    from PySide6.QtCore import QPoint, QTimer, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication
    from novelreader.qt_host import DesktopWindow
    from ui_repair_qa import fixtures

    with tempfile.TemporaryDirectory(prefix="qyreader-flicker-scroll-") as temporary:
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

        frames = []          # list of {ms, ink, scrollTop}
        captures = []        # downscaled QImage per frame (for flash evidence)
        scroll_tick = 0
        timer = QTimer()
        started = 0
        result = {"passed": False, "capture": "QScreen native desktop",
                  "configured": configured, "frames": args.frames,
                  "environment": {k: os.environ.get(k) for k in
                                  ("QT_QUICK_BACKEND", "QSG_RHI_BACKEND", "QTWEBENGINE_CHROMIUM_FLAGS")}}

        def whole_ink(image: QImage) -> int:
            # Count dark/textured pixels across the entire window, sampled on a
            # stride to keep each frame cheap. A white flash collapses this count.
            stride = 12
            count = 0
            for y in range(0, image.height(), stride):
                for x in range(0, image.width(), stride):
                    if image.pixelColor(x, y).lightness() < 190:
                        count += 1
            return count

        def finish(error=None):
            timer.stop()
            if error:
                result["error"] = error
            else:
                inks = [f["ink"] for f in frames]
                baseline = max(inks) if inks else 0
                result["baselineInk"] = baseline
                flash = [i for i, f in enumerate(frames)
                         if f["ink"] < baseline * args.ink_threshold]
                # A single isolated frame is a plausible drop; consecutive frames
                # (>=2) that both collapse is a real content loss the eye can see.
                runs = []
                run = [flash[0]] if flash else []
                for i in flash[1:]:
                    if i == run[-1] + 1:
                        run.append(i)
                    else:
                        if len(run) >= 1:
                            runs.append(run)
                        run = [i]
                if run:
                    runs.append(run)
                result.update({"captureAvailable": baseline > 500,
                               "flashFrames": flash,
                               "flashRuns": [{"start": r[0], "end": r[-1], "count": len(r),
                                              "minInk": min(frames[i]["ink"] for i in r)}
                                             for r in runs],
                               "frameCount": len(frames)})
                result["passed"] = bool(baseline > 500 and not runs)
                for i in flash[:12]:
                    captures[i].save(str(output / f"flash-{i:04d}.png"))
                if captures:
                    captures[-1].save(str(output / "last.png"))
            (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            window.requestApplicationExit()
            app.quit()

        def sample():
            nonlocal scroll_tick
            try:
                index = len(frames)
                # Scroll the library continuously: bounce the scrollTop up and down
                # so the compositor re-rasterizes new card tiles every tick.
                if index % 4 == 0:
                    scroll_tick += 1
                    direction = 1 if (scroll_tick // 10) % 2 == 0 else -1
                    window._page.runJavaScript(
                        "(()=>{const el=document.querySelector('.library-page');"
                        "if(!el)return 0;el.scrollTop=Math.min(Math.max(el.scrollTop+"
                        f"{direction * args.scroll_step},0),el.scrollHeight-el.clientHeight);"
                        "return el.scrollTop;})()")
                origin = window.mapToGlobal(QPoint(0, 0))
                image = window.screen().grabWindow(0, origin.x(), origin.y(),
                                                  window.width(), window.height()).toImage()
                if image.isNull():
                    finish("Native desktop capture unavailable")
                    return
                image = image.scaled(window.width(), window.height())
                ink = whole_ink(image)
                frames.append({"ms": round((time.monotonic() - started) * 1000, 2),
                               "ink": ink, "scrollTick": scroll_tick})
                captures.append(image.scaled(640, 360))
                if len(frames) >= args.frames:
                    finish()
            except Exception as exc:
                finish(str(exc))

        def start():
            nonlocal started
            started = time.monotonic()
            timer.timeout.connect(sample)
            timer.start(16)

        window._view.loadFinished.connect(lambda ok: QTimer.singleShot(1800, start) if ok else finish("Page failed"))
        QTimer.singleShot(90000, lambda: finish("Timed out"))
        app.exec()
        print(json.dumps({k: v for k, v in result.items() if k != "frames"}, ensure_ascii=False))
        return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
