"""Измеряет реальный FFmpeg pipeline на синтетическом материале без публикации."""

import argparse
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import video  # noqa: E402
from backend.config import STORAGE  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=2)
    parser.add_argument("--duration", type=int, default=15)
    parser.add_argument("--resolution", choices=["720", "1080"], default="720")
    args = parser.parse_args()
    peak = [0]
    done = threading.Event()
    process = psutil.Process()

    def sample_memory():
        while not done.wait(0.1):
            total = 0
            for item in [process, *process.children(recursive=True)]:
                try:
                    total += item.memory_info().rss
                except psutil.NoSuchProcess:
                    pass
            peak[0] = max(peak[0], total)

    sampler = threading.Thread(target=sample_memory, daemon=True)
    sampler.start()
    try:
        with tempfile.TemporaryDirectory(dir=STORAGE / "temp") as directory:
            folder = Path(directory)
            source = folder / "benchmark.mp4"
            video.make_test_video(source, max(48, args.count * args.duration * 2))
            metadata = video.probe(source)
            start = time.monotonic()
            features = video.analyze(source, metadata)
            analysis = time.monotonic() - start
            candidates = video.select_candidates(features, metadata["duration"], args.duration, args.count)
            render_start = time.monotonic()
            for index, candidate in enumerate(candidates):
                video.render(
                    source,
                    folder / f"clip-{index}.mp4",
                    candidate,
                    dict(resolution=args.resolution, framing="blur"),
                    metadata,
                )
            rendering = time.monotonic() - render_start
            total = analysis + rendering
            result = dict(
                source="FFmpeg testsrc2 + sine; synthetic benchmark",
                resolution=args.resolution,
                clips=len(candidates),
                clip_duration=args.duration,
                analysis_seconds=round(analysis, 2),
                render_seconds=round(rendering, 2),
                average_render_seconds=round(rendering / max(1, len(candidates)), 2),
                clips_per_hour=round(len(candidates) / total * 3600, 1),
                theoretical_clips_per_day=round(len(candidates) / total * 86400),
                peak_process_tree_memory_mb=round(peak[0] / 1024**2, 1),
                note="Экстраполяция короткого синтетического теста, не гарантия суточной производительности.",
            )
            output = STORAGE / "benchmark.json"
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        done.set()
        sampler.join()


if __name__ == "__main__":
    main()
