"""Живой предпросмотр держит одно подключение, поэтому реклама не начинается заново."""

import base64
import os
import subprocess
import threading
from uuid import uuid4
from PIL import Image
from .config import FFMPEG, STORAGE
from .live import resolve_stream, stream_inputs, validate_live_url

sessions = {}
lock = threading.Lock()


def stop_all():
    with lock:
        identities = list(sessions)
    for identity in identities:
        stop(identity)


def start(url, height):
    url, _ = validate_live_url(url)
    stop_all()
    _, streams, _ = resolve_stream(url, height)
    identity = uuid4().hex
    path = STORAGE / "temp" / (identity + ".preview.png")
    command = [FFMPEG, "-v", "error", "-y"] + stream_inputs([next(s for s in streams if s["video"])])
    command += [
        "-t",
        "600",
        "-an",
        "-vf",
        "fps=1,scale='min(960,iw)':-2",
        "-threads",
        "2",
        "-update",
        "1",
        "-atomic_writing",
        "1",
        str(path),
    ]
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    timer = threading.Timer(600, stop, [identity])
    timer.daemon = True
    with lock:
        sessions[identity] = (process, path, timer)
    timer.start()
    return {"id": identity}


def frame(identity):
    with lock:
        item = sessions.get(identity)
    if not item:
        raise ValueError("Предпросмотр завершён. Откройте его заново")
    process, path, _ = item
    try:
        data = path.read_bytes()
        from io import BytesIO

        with Image.open(BytesIO(data)) as image:
            width, height = image.size
        return dict(png=base64.b64encode(data).decode("ascii"), width=width, height=height)
    except OSError, ValueError:
        if process.poll() is not None:
            raise ValueError("Соединение предпросмотра завершилось. Повторите подключение")
        return {"pending": True}


def stop(identity):
    with lock:
        item = sessions.pop(identity, None)
    if item:
        process, path, timer = item
        timer.cancel()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        path.unlink(missing_ok=True)
    return {"stopped": True}
