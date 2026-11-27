"""Копии готовых роликов в выбранную папку, без перезаписи чужих файлов."""

from pathlib import Path
import re
import shutil


def copy_video(source, folder, title, identity):
    folder = Path(folder).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).strip(" .")[:100] or "CLIP"
    target = folder / f"{name} · {identity[:8]}.mp4"
    index = 1
    while True:
        try:
            # Режим xb атомарно защищает даже от одновременного экспорта.
            with target.open("xb") as destination:
                try:
                    with Path(source).open("rb") as stream:
                        shutil.copyfileobj(stream, destination)
                except Exception:
                    destination.close()
                    target.unlink(missing_ok=True)
                    raise
            return str(target)
        except FileExistsError:
            target = folder / f"{name} · {identity[:8]} ({index}).mp4"
            index += 1
