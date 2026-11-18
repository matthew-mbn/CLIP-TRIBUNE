"""Маленький HTTP-клиент. Окно не обращается к базе или FFmpeg напрямую."""

from pathlib import Path

import httpx

from backend.config import STORAGE, BASE_URL


def request(method, path, data=None):
    token = (STORAGE / ".api-token").read_text(encoding="utf-8")
    response = httpx.request(
        method,
        BASE_URL + "/api" + path,
        json=data,
        headers={"X-Clip-Tribune": token},
        timeout=600,
        trust_env=False,
    )
    if response.is_error:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise RuntimeError(str(detail))
    return response.json()


def copy_clip(identity, destination):
    """Копирование выполняется в фоновом потоке, в том числе для больших файлов."""
    import shutil

    location = request("GET", f"/clips/{identity}/location")
    source = Path(location["path"]).resolve()
    target = Path(destination).resolve()
    if source != target:
        shutil.copyfile(source, target)
    return str(target)
