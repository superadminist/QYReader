# -*- coding: utf-8 -*-
"""Exercise local SAPI and both lyric surfaces by launching source run.bat."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.fspath(ROOT))

from novelreader.book_loader import BookContent, Chapter
from novelreader.storage import Storage


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def fixture(data_root, fixture_root):
    title = "源码本地语音同步验收"
    sentences = [
        "第一句正在通过系统语音朗读，请在声音读到一半时暂停，再恢复继续朗读。",
        "第二句仍然通过系统语音朗读，主面板和悬浮窗都应该显示实际正在读的文字。",
        "第三句用于重复点击播放和暂停，确认文字不会提前跳到后面的句子。",
        "第四句继续朗读，用于观察前一句结束和下一句开始之间的边界。",
        "第五句继续使用系统语音，确保连续多句时每次暂停都保留正在显示的文字。",
        "第六句检查恢复朗读以后，界面只在新一句确实开始时才改变当前高亮。",
        "第七句延长测试章节，避免反复点击时恰好碰到整本朗读结束的状态。",
        "第八句是最后的检查句，完整朗读以后才允许推进到章节末尾。",
    ]
    if "--gif-trace" in sys.argv:
        sentences = [
            "2.核心产品B：三星堆代表性文物拼装金属冰箱贴核心产品B的冰箱贴将纵目面具、大立人像、神树、神鸟和太阳轮设计为五个独立金属单元，各部分保留文物最具辨识度的轮廓与局部纹样。",
            "单件可以作为小型纪念品独立展示，按照既定顺序拼接后则形成完整的纵向组合图形，让用户在收集和拼装过程中认识不同文物之间的视觉联系，也提升了产品的成套收藏吸引力。",
            "三星堆代表性文物拼装金属冰箱贴如图51所示。",
        ] * 3
    content = "".join(sentences)
    source = fixture_root / "sync.txt"
    source.write_text(content, encoding="utf-8")
    book = BookContent(title, "QA", "txt", [Chapter("第一章 同步验收", content)])
    storage = Storage(os.fspath(data_root / "library.json"))
    storage.set_setting("auto_check_updates", False)
    storage.set_setting("tts_voice", "")
    storage.set_setting("tts_rate", 150 if "--gif-trace" in sys.argv else 200)
    storage.set_setting("tts_sentence_gap", 0.1 if "--gif-trace" in sys.argv else 0.3)
    book_id = storage.book_id(os.fspath(source))
    now = time.time()
    storage.add_book({
        "id": book_id, "title": title, "author": "QA", "format": "txt",
        "path": os.fspath(source), "added_at": now, "last_read_at": now,
        "total_chars": len(content), "chapter_titles": ["第一章 同步验收"],
        "progress": {"chapter_idx": 0, "char_offset": 0, "percent": 0.0},
    })
    storage.write_cache(book_id, book)
    return title


def stop_tree(process):
    if process.poll() is not None:
        return
    root = psutil.Process(process.pid)
    children = root.children(recursive=True)
    for child in children:
        child.terminate()
    root.terminate()
    _, alive = psutil.wait_procs(children + [root], timeout=5)
    for item in alive:
        item.kill()


def main():
    node = Path(r"C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe")
    if not node.is_file():
        raise RuntimeError("Node 20+ runtime is missing")
    with tempfile.TemporaryDirectory(prefix="qyreader-run-bat-sync-") as temporary:
        temporary_root = Path(temporary)
        data_root = temporary_root / "data"
        fixture_root = temporary_root / "fixture"
        data_root.mkdir()
        fixture_root.mkdir()
        title = fixture(data_root, fixture_root)
        trace_path = temporary_root / "sapi-stream-trace.jsonl"
        (temporary_root / "sitecustomize.py").write_text(
            """import os
if os.environ.get('DD_QA_SELECT_REALTEK_OUTPUT') == '1':
    import pyttsx3.drivers.sapi5 as sapi5
    original_init = sapi5.SAPI5Driver.__init__
    def init_with_working_output(self, proxy):
        original_init(self, proxy)
        outputs = self._tts.GetAudioOutputs()
        for index in range(outputs.Count):
            output = outputs.Item(index)
            if 'Realtek(R) Audio' in output.GetDescription():
                self._tts.AudioOutput = output
                break
    sapi5.SAPI5Driver.__init__ = init_with_working_output
if os.environ.get('DD_QA_SAPI_STREAM_TRACE') == '1':
    import json
    import time
    import pyttsx3.drivers.sapi5 as sapi5
    from novelreader.tts_engine import _install_sapi_stream_events
    _install_sapi_stream_events()
    trace_path = os.environ['DD_QA_TRACE_PATH']
    def trace(kind, **data):
        with open(trace_path, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps({'at': time.time(), 'kind': kind, **data}, ensure_ascii=True) + '\\n')
    original_say = sapi5.SAPI5Driver.say
    def say_with_stream(self, text):
        original_say(self, text)
        trace('say', stream=self._dd_current_stream, name=self._proxy._name, length=len(text))
    sapi5.SAPI5Driver.say = say_with_stream
    sink = sapi5.SAPI5DriverEventSink
    original_start = sink._ISpeechVoiceEvents_StartStream
    original_word = sink._ISpeechVoiceEvents_Word
    original_end = sink._ISpeechVoiceEvents_EndStream
    def start_with_trace(self, stream_number, stream_position):
        trace('stream_start', stream=int(stream_number), name=self._driver._proxy._name)
        return original_start(self, stream_number, stream_position)
    def word_with_trace(self, stream_number, stream_position, char, length):
        trace('word', stream=int(stream_number), name=self._driver._proxy._name, char=int(char), length=int(length))
        return original_word(self, stream_number, stream_position, char, length)
    def end_with_trace(self, stream_number, stream_position):
        trace('stream_end', stream=int(stream_number), name=self._driver._proxy._name, stopping=bool(self._driver._stopping))
        return original_end(self, stream_number, stream_position)
    sink._ISpeechVoiceEvents_StartStream = start_with_trace
    sink._ISpeechVoiceEvents_Word = word_with_trace
    sink._ISpeechVoiceEvents_EndStream = end_with_trace
    from novelreader.tts_engine import SpeechController
    original_post = SpeechController._post
    def post_with_trace(self, event, generation=None):
        if event.get('type') in {'sentence_start', 'sentence_done', 'error'}:
            trace('post', event=event.get('type'), generation=generation, offset=event.get('char_offset'), length=len(event.get('text', '')), message=event.get('message'))
        return original_post(self, event, generation)
    SpeechController._post = post_with_trace
""",
            encoding="utf-8",
        )
        port = free_port()
        environment = os.environ.copy()
        environment.update({
            "DOUBAO_NOVEL_DATA": os.fspath(data_root),
            "QTWEBENGINE_REMOTE_DEBUGGING": str(port),
            "QTWEBENGINE_CHROMIUM_FLAGS": "--remote-allow-origins=*",
            "DD_QA_CDP_PORT": str(port),
            "DD_QA_BOOK_TITLE": title,
            "DD_QA_SELECT_REALTEK_OUTPUT": "1",
            "DD_QA_SAPI_STREAM_TRACE": "1" if "--gif-trace" in sys.argv else "0",
            "DD_QA_TRACE_PATH": os.fspath(trace_path),
            "DD_QA_WAIT_THIRD_SENTENCE": "1" if "--gif-trace" in sys.argv else "0",
            "PYTHONPATH": os.fspath(temporary_root) + os.pathsep + environment.get("PYTHONPATH", ""),
        })
        process = subprocess.Popen(
            ["cmd.exe", "/d", "/c", os.fspath(ROOT / "run.bat")],
            cwd=ROOT, env=environment, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        )
        try:
            driver = subprocess.run(
                [os.fspath(node), os.fspath(ROOT / "prototype" / "tests" / "run-bat-sync-cdp.mjs")],
                cwd=ROOT, env=environment, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=120,
            )
            if driver.stderr:
                print(driver.stderr, file=sys.stderr, end="")
            if driver.returncode:
                raise RuntimeError(f"run.bat CDP driver failed: {driver.returncode}")
            capture = json.loads(driver.stdout)
            print(json.dumps({
                "source": "run.bat", "result": "UI passed",
                "floating_pause_resume_clicks": len(capture["timeline"]),
                "main_and_floating_matched": True,
                "third_sentence_reached": capture["thirdSentence"] is not None,
            }, ensure_ascii=False))
        finally:
            stop_tree(process)
            if process.stdout:
                output = process.stdout.read()
                if output:
                    print(output, file=sys.stderr, end="")
            if "--gif-trace" in sys.argv and trace_path.is_file():
                events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
                current_say = last_word = last_end = None
                starts = []
                done_events = []
                for event in events:
                    kind = event["kind"]
                    if kind == "say":
                        current_say = event
                        last_word = last_end = None
                    elif kind == "word":
                        last_word = event
                    elif kind == "stream_end":
                        last_end = event
                    elif kind == "post" and event["event"] == "sentence_start":
                        if not (current_say and last_word and last_word["stream"] == current_say["stream"]
                                and last_word["char"] == 0 and last_word["at"] >= current_say["at"]):
                            raise AssertionError(f"Text advanced from another SAPI stream: {event}")
                        starts.append(event)
                    elif kind == "post" and event["event"] == "sentence_done":
                        if not (current_say and last_end and last_end["stream"] == current_say["stream"]
                                and last_end["at"] >= current_say["at"]):
                            raise AssertionError(f"Sentence completed from another SAPI stream: {event}")
                        done_events.append(event)
                    elif kind == "post" and event["event"] == "error":
                        raise AssertionError(f"Source playback error: {event['message']}")
                if len({event["offset"] for event in starts}) < 3:
                    raise AssertionError("Source playback did not reach the third sentence")
                print(json.dumps({
                    "sapi_stream_events": "passed", "starts": len(starts),
                    "completed_sentences": len(done_events),
                    "first_next_sentence_offset": next(event["offset"] for event in starts if event["offset"]),
                }, ensure_ascii=False))


if __name__ == "__main__":
    main()
