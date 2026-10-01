"""Explicit real-Qt acceptance gate for the six UI repair items.

All app writes and evidence belong to an isolated temporary directory. No
system DPI, user library, or device preferences are changed by this driver.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.fspath(ROOT))
import stage4_window_probe as probe


def native_action(args):
    """Operate only on the explicitly supplied test-host PID."""
    # The standard probe reports DPI-virtualized coordinates; desktop captures
    # must use physical pixels so the complete native window is included.
    probe.user32.SetProcessDPIAware()
    if args.action == "snapshot":
        return probe.snapshot(args.pid)
    if args.action == "place":
        probe._place(args.pid, args.role, args.x, args.y, args.width, args.height)
        return probe.snapshot(args.pid)
    if args.action == "drag":
        mode = probe._drag(args.pid, args.role, args.from_x, args.from_y, args.dx, args.dy)
        return {**probe.snapshot(args.pid), "dragMode": mode}
    from PIL import ImageGrab
    item = probe._role_window(args.pid, args.role)
    if args.action == "capture":
        rect = item["rect"]
        try:
            image = ImageGrab.grab(bbox=(rect["left"], rect["top"], rect["right"], rect["bottom"]), all_screens=True)
            extrema = image.convert("RGB").getextrema()
            available = any(high - low > 15 for low, high in extrema)
            if available:
                image.save(args.output)
            result = {"path": args.output if available else None, "size": image.size, "available": available, "extrema": extrema}
        except OSError as exc:
            result = {"path": None, "available": False, "reason": str(exc)}
    elif args.action == "flow":
        frames = []
        rect = item["rect"]
        # Intermediate native sizes exercise the real compositor, in addition
        # to the pointer-based system-resize gesture performed by the CDP gate.
        for index in range(8):
            offset = (index if index < 4 else 7 - index) * 14
            probe._place(args.pid, args.role, rect["left"], rect["top"], rect["width"] + offset, rect["height"] + offset)
            time.sleep(.055)
            args.action = "capture"
            args.output = os.fspath(Path(args.output_dir) / f"{args.role}-cycle-{args.cycle:02d}-frame-{index:02d}.png")
            if not frames or frames[-1]["available"]:
                frames.append(native_action(args))
        result = {"frames": frames, "window": probe._role_window(args.pid, args.role)}
    else:
        raise ValueError(args.action)
    return result


def fixtures(data_root, fixture_root):
    from novelreader.book_loader import BookContent, Chapter
    from novelreader.storage import Storage
    storage = Storage(os.fspath(data_root / "library.json"))
    storage.set_setting("auto_check_updates", False)
    storage.set_setting("auto_open_last", False)
    storage.set_setting("cache_dir", os.fspath(data_root / "cache"))
    ids = []
    for index in range(10):
        title = f"UI修复验收 {index + 1:02d}"
        text = "夜间章节标题与正文必须清晰可读。连续缩放保持完整内容与圆角。" * 30
        source = fixture_root / f"中文 空格 {index:02d}.txt"
        source.write_text(text, encoding="utf-8")
        book = BookContent(title, "QA", "txt", [Chapter("第一章 夜间验收", text), Chapter("第二章", text)])
        bid = storage.book_id(os.fspath(source))
        storage.add_book({"id": bid, "title": title, "author": "QA", "format": "txt", "path": os.fspath(source), "added_at": time.time() - index, "last_read_at": time.time() - index, "total_chars": len(text) * 2, "chapter_titles": [chapter.title for chapter in book.chapters], "progress": {"chapter_idx": 0, "char_offset": 0, "percent": 0}})
        storage.write_cache(bid, book)
        ids.append(bid)
    return ids


def stop_tree(process):
    import psutil
    try:
        items = psutil.Process(process.pid).children(recursive=True)
    except psutil.NoSuchProcess:
        items = []
    if process.poll() is None:
        items.append(psutil.Process(process.pid))
    for item in reversed(items):
        try:
            item.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(items, timeout=5)
    for item in alive:
        item.kill()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--node")
    parser.add_argument("--capture-python", default=sys.executable, help="Python runtime with Pillow for desktop capture")
    parser.add_argument("--output-dir")
    parser.add_argument("--dpi", default="1,1.25,1.5")
    parser.add_argument("--cycles", type=int, default=20)
    parser.add_argument("--single-process", action="store_true", help="Diagnostic fallback for isolated desktops without a shared GPU context")
    parser.add_argument("--mock-source-reveal", action="store_true", help="Observe the backend source path without opening Explorer")
    parser.add_argument("--action", choices=("capture", "flow", "snapshot", "place", "drag"))
    parser.add_argument("--pid", type=int)
    parser.add_argument("--role", default="main")
    parser.add_argument("--cycle", type=int, default=0)
    parser.add_argument("--output")
    for name in ("x", "y", "width", "height", "from-x", "from-y", "dx", "dy"):
        parser.add_argument(f"--{name}", type=int, default=0)
    args = parser.parse_args()
    if args.action:
        print(json.dumps(native_action(args)))
        return 0
    if not args.node:
        parser.error("--node is required for the acceptance run")
    from stage4_desktop_qa import _resolve_window_host_pid
    probe.user32.SetProcessDPIAware()
    system_scale = probe.user32.GetDpiForSystem() / 96
    output = Path(args.output_dir or tempfile.mkdtemp(prefix="qyreader-ui-repair-")).resolve()
    if output.is_relative_to(ROOT):
        raise SystemExit("QA evidence must be outside the repository")
    output.mkdir(parents=True, exist_ok=True)
    data_root, fixture_root = output / "data", output / "fixture"
    data_root.mkdir(exist_ok=True)
    fixture_root.mkdir(exist_ok=True)
    ids = fixtures(data_root, fixture_root)
    (output / "fixture-ids.json").write_text(json.dumps(ids), encoding="utf-8")
    results = []
    for scale in map(float, args.dpi.split(",")):
        scale_dir = output / f"dpi-{scale:g}"
        scale_dir.mkdir(exist_ok=True)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        env = os.environ.copy()
        env["DD_QA_TRACE"] = "1"
        env["DD_QA_SYSTEM_SCALE"] = str(system_scale)
        env["DD_QA_QT_MULTIPLIER"] = str(scale / system_scale)
        env.update({"DOUBAO_NOVEL_DATA": str(data_root), "QTWEBENGINE_REMOTE_DEBUGGING": str(port), "QTWEBENGINE_CHROMIUM_FLAGS": "--remote-allow-origins=*", "QT_SCALE_FACTOR": str(scale), "QT_AUTO_SCREEN_SCALE_FACTOR": "0", "DD_QA_CDP_PORT": str(port), "DD_QA_SCREENSHOT_DIR": str(scale_dir), "DD_QA_CHECKPOINT": str(scale_dir / "result.json"), "DD_QA_SCALE_FACTOR": str(scale), "DD_QA_CYCLES": str(args.cycles), "DD_QA_PYTHON": sys.executable, "DD_QA_CAPTURE_PYTHON": args.capture_python, "DD_QA_WINDOW_PROBE": str(ROOT / "tests/stage4_window_probe.py"), "DD_QA_UI_PROBE": str(Path(__file__).resolve())})
        if args.single_process:
            env["QTWEBENGINE_CHROMIUM_FLAGS"] += " --single-process"
            env["DD_QA_SINGLE_PROCESS"] = "1"
        env["QT_SCALE_FACTOR"] = str(scale / system_scale)
        if args.mock_source_reveal:
            hook_dir = scale_dir / "qa-hook"
            hook_dir.mkdir(exist_ok=True)
            (hook_dir / "sitecustomize.py").write_text(
                "import json,os\nfrom pathlib import Path\nfrom novelreader.qt_host import DesktopWindow\n"
                "def reveal(self,path):\n    Path(os.environ['DD_QA_REVEAL_LOG']).write_text(json.dumps({'path':str(path)}),encoding='utf-8')\n    return True\n"
                "DesktopWindow.revealSourceFile=reveal\n", encoding="utf-8")
            env["PYTHONPATH"] = str(hook_dir) + os.pathsep + str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
            env["DD_QA_REVEAL_LOG"] = str(scale_dir / "reveal-source.json")
        with (scale_dir / "host.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(["cmd.exe", "/d", "/c", str(ROOT / "run.bat")], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                env["DD_QA_HOST_PID"] = str(_resolve_window_host_pid(process, ROOT / "tests/stage4_window_probe.py", timeout=35))
                driven = subprocess.run([args.node, str(ROOT / "prototype/tests/ui-repair-cdp.mjs")], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
                (scale_dir / "driver.log").write_text(driven.stdout + "\n" + driven.stderr, encoding="utf-8")
                if driven.returncode:
                    raise RuntimeError(f"DPI {scale} gate failed: {driven.stderr[-3000:]}")
                results.append(json.loads((scale_dir / "result.json").read_text(encoding="utf-8")))
            finally:
                stop_tree(process)
    summary = {"source": "run.bat", "evidence": str(output), "results": results}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
