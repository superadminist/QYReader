"""Explicit CPU benchmark using installed isolated models and original QA text."""
import argparse
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from novelreader.kokoro_service import VOICES, create_engine


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--threads", nargs="+", type=int, choices=[1, 2, 4], default=[1, 2, 4])
    args = parser.parse_args()
    import sherpa_onnx
    import psutil
    result = {"model": "Kokoro v1.0 INT8", "runtime": sherpa_onnx.version, "provider": "cpu", "runs": []}
    texts = ["今天是2026年10月11日。我们使用自己编写的文字，验证离线朗读、数字读法和句子停顿。", "静静翻开书页，午后的阳光落在窗边。阅读让每一天多一份发现。", "这是一段中英文测试。Hello QYReader, welcome to offline reading."]
    process = psutil.Process()
    # Fail any accidental Python-side network use. All model assets are local.
    with patch("urllib.request.urlopen", side_effect=AssertionError("offline benchmark attempted HTTP")), patch("socket.create_connection", side_effect=AssertionError("offline benchmark attempted network")):
        for threads in args.threads:
            start = time.perf_counter()
            engine = create_engine(args.model_dir, threads)
            load = time.perf_counter() - start
            for index, (sid, name, chinese) in enumerate(VOICES):
                text = texts[index % len(texts)]
                start = time.perf_counter()
                audio = engine.generate(text, sid=sid, speed=1)
                elapsed = time.perf_counter() - start
                duration = len(audio.samples) / audio.sample_rate
                row = {"threads": threads, "sid": sid, "voice": chinese, "loadSeconds": load, "synthesisSeconds": elapsed,
                       "audioSeconds": duration, "rtf": elapsed / duration, "rssMiB": process.memory_info().rss / 1048576}
                result["runs"].append(row)
                # Samples are for later human listening, not an acoustic pass.
                target = Path(args.output).parent / f"kokoro-{threads}-{name}.wav"
                sherpa_onnx.write_wave(str(target), audio.samples, audio.sample_rate)
                print(json.dumps(row, ensure_ascii=True), flush=True)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
