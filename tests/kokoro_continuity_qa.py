"""Cold-cache production synthesis and optional silent playback-consumer QA.

No speakers, book imports, or user data are involved. Model assets are read only;
each invocation preserves its own data/cache below the output directory.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import uuid
import wave
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from novelreader import kokoro_service
from novelreader.tts_engine import SpeechController


def original_chapter(count):
    """Original prose with a unique sentence number: never loop cached text."""
    scenes = [
        "晨光穿过木窗，照亮了桌上的旧地图，林舟决定沿着溪水寻找山中的石桥",
        "小路两旁长着细密的青草，远处传来鸟鸣，他把见闻认真记在随身的本子里",
        "溪边的老人指向山脚，说那里有一座安静的小屋，雨天可以听见屋檐落水",
        "走过竹林时，风把落叶送到脚边，他停下来看清道路，再继续慢慢向前",
        "石桥下的水很清，几条小鱼躲在石头后面，阳光让水纹显得格外明亮",
        "午后的云影掠过山谷，林舟找到一块平整的石头，坐下来整理今天的记录",
        "归途经过村口，孩子们正在放纸船，他帮忙把一只搁浅的小船推回水中",
        "夜色渐渐落在窗外，他翻开笔记，把新的发现写好，期待明天继续出发",
    ]
    return "\n".join(f"行程的第{index + 1}页记录着，{scenes[index % len(scenes)]}。" for index in range(count))


def chapter_chunks(content):
    chunks, offset = [], 0
    while offset < len(content):
        text, end, _ = SpeechController._next_chunk(content, offset)
        if not text:
            break
        if end <= offset:
            raise AssertionError("Production sentence splitter did not advance")
        chunks.append(text)
        offset = end
    if len(set(chunks)) != len(chunks):
        raise AssertionError("Cold chapter must contain unique sentence texts")
    return chunks


def audio_seconds(path):
    with wave.open(str(path), "rb") as source:
        return source.getnframes() / source.getframerate()


def rounded(value):
    return round(value, 6)


def production_run(data_root, texts, voice, rate, threads, simulate_playback):
    """Keep service queue/cache behavior, adding timing observers only."""
    service = kokoro_service.KokoroService(data_root, threads=threads)
    started = time.perf_counter()
    timing_lock = threading.Lock()
    generations, completed, engine_loads, hash_times = {}, {}, [], []
    futures, submitted, rows = {}, {}, []
    trace_path = Path(data_root) / "sentence-timings.jsonl"
    create_engine = kokoro_service.create_engine
    file_hash = kokoro_service.file_hash
    generate = service._generate

    class ObservedEngine:
        def __init__(self, engine):
            self.engine = engine

        def __getattr__(self, name):
            return getattr(self.engine, name)

        def generate(self, text, *args, **kwargs):
            began = time.perf_counter()
            audio = self.engine.generate(text, *args, **kwargs)
            seconds = time.perf_counter() - began
            with timing_lock:
                generations[text] = {
                    "synthesisSeconds": seconds,
                    "audioSeconds": len(audio.samples) / audio.sample_rate,
                }
            return audio

    def observed_create(*args, **kwargs):
        began = time.perf_counter()
        engine = create_engine(*args, **kwargs)
        engine_loads.append(time.perf_counter() - began)
        return ObservedEngine(engine)

    def observed_hash(*args, **kwargs):
        began = time.perf_counter()
        value = file_hash(*args, **kwargs)
        hash_times.append(time.perf_counter() - began)
        return value

    def observed_generate(key, text, sid, requested_rate):
        began = time.perf_counter()
        path = generate(key, text, sid, requested_rate)
        ended = time.perf_counter()
        with timing_lock:
            completed[text] = {
                "workerStartSeconds": began - started,
                "readySeconds": ended - started,
                "serviceWorkSeconds": ended - began,
            }
        return path

    def request(index, priority):
        if index not in submitted:
            submitted[index] = time.perf_counter() - started
        # Re-requesting the current item also exercises production promotion.
        futures[index] = service.request(texts[index], voice, rate, priority=priority)
        return futures[index]

    try:
        with patch.object(kokoro_service, "create_engine", side_effect=observed_create), patch.object(kokoro_service, "file_hash", side_effect=observed_hash), patch.object(service, "_generate", side_effect=observed_generate):
            virtual_end = 0.0
            for index, text in enumerate(texts):
                current = request(index, 0)
                for following in range(index + 1, min(index + 4, len(texts))):
                    request(following, 10)
                wait_started = time.perf_counter()
                path = current.result()
                actual_start = time.perf_counter() - started
                future_wait = time.perf_counter() - wait_started
                duration = audio_seconds(path)
                with timing_lock:
                    timing = dict(completed.get(text, {
                        "workerStartSeconds": submitted[index],
                        "readySeconds": actual_start,
                        "serviceWorkSeconds": 0.0,
                    }))
                    synthesis = dict(generations.get(text, {}))
                if simulate_playback:
                    playback_start = actual_start
                    wait_seconds = max(0.0, playback_start - virtual_end)
                else:
                    # A continuously fed producer is an optimistic estimate;
                    # it cannot establish real consumer/prefetch continuity.
                    playback_start = max(virtual_end, timing["readySeconds"])
                    wait_seconds = max(0.0, timing["readySeconds"] - virtual_end)
                virtual_end = playback_start + duration
                row = {
                    "index": index,
                    "characters": len(text),
                    "submittedSeconds": submitted[index],
                    **timing,
                    "requestWaitSeconds": future_wait,
                    "waitSeconds": wait_seconds,
                    "playbackStartSeconds": playback_start,
                    "audioSeconds": duration,
                    "synthesisSeconds": synthesis.get("synthesisSeconds", 0.0),
                    "rtf": synthesis.get("synthesisSeconds", 0.0) / duration,
                    "generated": bool(synthesis),
                }
                rows.append(row)
                notice = json.dumps({"threads": threads, "consumer": "sleep" if simulate_playback else "virtual", **{key: rounded(value) if isinstance(value, float) else value for key, value in row.items()}}, ensure_ascii=True)
                with trace_path.open("a", encoding="utf-8") as trace:
                    trace.write(notice + "\n")
                print(notice, flush=True)
                if simulate_playback:
                    time.sleep(duration)
            elapsed = time.perf_counter() - started
    finally:
        service.close()

    for row in rows:
        row["bufferedAudioSeconds"] = sum(
            later["audioSeconds"] for later in rows[row["index"] + 1:]
            if later["readySeconds"] <= row["playbackStartSeconds"]
        )
        row["queueWaitSeconds"] = max(0.0, row["workerStartSeconds"] - row["submittedSeconds"])
    total_audio = sum(row["audioSeconds"] for row in rows)
    generated_count = len(generations)
    steady = rows[1:]
    steady_audio = sum(row["audioSeconds"] for row in steady)
    stalls = [row for row in steady if row["waitSeconds"] > 0.3]
    summary = {
        "mode": "silent-realtime-consumer" if simulate_playback else "throughput-with-optimistic-virtual-consumer",
        "speakerPlayback": False,
        "modelId": service.snapshot()["modelId"],
        "threads": threads,
        "sentenceCount": len(rows),
        "longChapter": len(rows) >= 20 and total_audio >= 200,
        "minimumContinuityAudioSeconds": 200,
        "generatedSentenceCount": generated_count,
        "uncachedRatio": generated_count / len(rows),
        "cacheReplayRatio": 1 - generated_count / len(rows),
        "initialWaitSeconds": rows[0]["waitSeconds"],
        "engineLoadSeconds": sum(engine_loads),
        "modelHashSeconds": sum(hash_times),
        "audioSeconds": total_audio,
        "synthesisSeconds": sum(row["synthesisSeconds"] for row in rows),
        "aggregateRTF": sum(row["synthesisSeconds"] for row in rows) / total_audio,
        "steadyServiceRTF": sum(row["serviceWorkSeconds"] for row in steady) / steady_audio if steady_audio else None,
        "elapsedSeconds": elapsed,
        "postStartWaitSeconds": sum(row["waitSeconds"] for row in steady),
        "stallCountOver300ms": len(stalls),
        "maximumPostStartWaitSeconds": max((row["waitSeconds"] for row in steady), default=0.0),
        "minimumBufferedAudioSeconds": min((row["bufferedAudioSeconds"] for row in steady[:-3]), default=0.0),
        "continuityGatePassed": bool(simulate_playback and len(rows) >= 20 and total_audio >= 200 and generated_count == len(rows) and not stalls),
        "rows": rows,
    }
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--threads", nargs="+", type=int, choices=[1, 2, 4, 8], default=[2])
    parser.add_argument("--sentences", type=int, default=32, help="Original unique sentences; fewer than 20 is only a smoke run")
    parser.add_argument("--voice", choices=[f"kokoro:v1.0:{name}" for _, name, _ in kokoro_service.VOICES], default="kokoro:v1.0:zf_xiaobei")
    parser.add_argument("--rate", type=int, default=200)
    parser.add_argument("--simulate-playback", action="store_true", help="Silently sleep each WAV duration; required for the continuity gate")
    parser.add_argument("--warm-run", action="store_true", help="Separately report cached replay with no playback sleep")
    args = parser.parse_args()
    if args.sentences < 1 or not 80 <= args.rate <= 400:
        parser.error("--sentences must be positive and --rate must be between 80 and 400")
    model_dir, output = args.model_dir.resolve(), args.output.resolve()
    if not (model_dir / "manifest.json").is_file():
        parser.error("--model-dir must be an installed production model containing manifest.json")
    manifest = json.loads((model_dir / "manifest.json").read_text(encoding="utf-8"))
    model_id = manifest.get("modelId", kokoro_service.MODEL_ID)
    variant = next((name for name, package in kokoro_service.MODEL_PACKAGES.items() if package["modelId"] == model_id), None)
    if variant is None:
        parser.error("Model manifest has an unsupported modelId")
    if output == model_dir or model_dir in output.parents:
        parser.error("--output must be outside the read-only model directory")
    if output.exists():
        parser.error("--output already exists; choose a new output path to preserve prior QA")
    output.parent.mkdir(parents=True, exist_ok=True)
    # The native Windows WAV writer does not use extended-length paths.
    # Keep QA folder names short even under the desktop artifact directory.
    workspace = output.parent / ("qa-" + uuid.uuid4().hex[:8])
    workspace.mkdir()
    chapter = original_chapter(args.sentences)
    (workspace / "original-chapter.txt").write_text(chapter, encoding="utf-8")
    texts = chapter_chunks(chapter)
    result = {
        "model": model_id,
        "variant": variant,
        "modelDirectory": str(model_dir),
        "workspace": str(workspace),
        "voice": args.voice,
        "rate": args.rate,
        "characters": len(chapter),
        "speakerPlayback": False,
        "status": "running",
        "evidenceBoundary": "Silent production-service consumer simulation; no acoustic, MCI, or human voice-quality proof. Virtual-only runs cannot pass the continuity gate.",
        "runs": [],
    }
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    # Guard accidental Python-side network use; model reading remains local.
    with patch("urllib.request.urlopen", side_effect=AssertionError("offline QA attempted HTTP")), patch("socket.create_connection", side_effect=AssertionError("offline QA attempted network")):
        for run_index, threads in enumerate(args.threads):
            data_root = workspace / f"r{run_index}"
            data_root.mkdir()
            (data_root / "kokoro-model.json").write_text(json.dumps({"directory": str(model_dir), "variant": variant}), encoding="utf-8")
            cold = production_run(data_root, texts, args.voice, args.rate, threads, args.simulate_playback)
            cold["cacheState"] = "fresh-empty-cache"
            if cold["uncachedRatio"] != 1:
                raise AssertionError("Cold production run reused audio instead of synthesizing every unique sentence")
            run = {"cold": cold}
            if args.warm_run:
                warm = production_run(data_root, texts, args.voice, args.rate, threads, False)
                warm["cacheState"] = "cache-replay"
                warm["continuityGatePassed"] = False
                if warm["generatedSentenceCount"]:
                    raise AssertionError("Warm replay unexpectedly synthesized audio")
                run["warm"] = warm
            result["runs"].append(run)
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["status"] = "complete"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "workspace": str(workspace), "continuityGatePassed": [run["cold"]["continuityGatePassed"] for run in result["runs"]]}, ensure_ascii=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
