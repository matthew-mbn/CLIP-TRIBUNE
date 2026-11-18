"""Останавливает только процессы, созданные этим проектом, с проверкой PID reuse."""

import json
import time
from pathlib import Path

import httpx
import psutil

ROOT = Path(__file__).resolve().parent.parent
storage = ROOT / "storage"
try:
    token = (storage / ".api-token").read_text(encoding="utf-8")
    httpx.post(
        "http://127.0.0.1:8765/api/control/stop",
        headers={"X-Clip-Tribune": token},
        timeout=3,
        trust_env=False,
    )
    time.sleep(1)
except OSError, httpx.HTTPError:
    pass
manifest = storage / "processes.json"
if manifest.exists():
    for record in reversed(json.loads(manifest.read_text(encoding="utf-8"))):
        try:
            process = psutil.Process(record["pid"])
            if abs(process.create_time() - record["created"]) > 0.01:
                continue
            if not Path(process.exe()).resolve().is_relative_to(ROOT):
                continue
            descendants = process.children(recursive=True)
            process.terminate()
            _, alive = psutil.wait_procs([process, *descendants], timeout=5)
            for child in alive:
                child.kill()
        except psutil.NoSuchProcess:
            pass
    manifest.unlink(missing_ok=True)
print("Clip Tribune остановлен.")
