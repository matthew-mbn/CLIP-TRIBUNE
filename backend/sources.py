"""Импортируем файлы в собственное хранилище, сохраняя оригиналы пользователя."""

import http.client
import shutil
import ssl
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select

from .config import MAX_UPLOAD, STORAGE, VIDEO_EXTENSIONS
from .models import SourceAsset, uid
from .security import file_hash, public_url
from .video import probe


def import_file(session, path, rights=False, source_id=None):
    path = Path(path).resolve()
    if path.suffix.lower() not in VIDEO_EXTENSIONS or not path.is_file():
        raise ValueError("Поддерживаются файлы MP4, MOV, MKV, WEBM")
    if path.stat().st_size > MAX_UPLOAD:
        raise ValueError("Размер файла превышает 20 ГБ")
    metadata = probe(path)
    digest = file_hash(path)
    existing = session.scalar(select(SourceAsset).where(SourceAsset.sha256 == digest))
    if existing:
        # Повторный импорт не снимает уже подтверждённые права.
        if rights and not existing.rights:
            existing.rights = True
            session.commit()
        return existing
    if shutil.disk_usage(STORAGE).free < path.stat().st_size + 1024**3:
        raise ValueError("Недостаточно свободного места для копии исходника")
    destination = STORAGE / "sources" / (uid() + path.suffix.lower())
    shutil.copyfile(path, destination)
    asset = SourceAsset(
        name=path.name,
        path=str(destination),
        sha256=digest,
        rights=rights,
        metadata_json=metadata,
        source_id=source_id,
    )
    session.add(asset)
    try:
        session.commit()
    except Exception:
        destination.unlink(missing_ok=True)
        session.rollback()
        raise
    return asset


def download_media(url, destination):
    """Соединяемся именно с проверенным IP; DNS rebinding не меняет адрес.

    TLS всё равно проверяет имя исходного сервера. Перенаправления запрещены.
    """
    parsed, addresses = public_url(url)
    if Path(parsed.path).suffix.lower() not in VIDEO_EXTENSIONS:
        raise ValueError("Ссылка должна вести непосредственно на видеофайл")

    class PinnedHTTPS(http.client.HTTPSConnection):
        def connect(self):
            import socket

            raw = socket.create_connection((addresses[0], 443), timeout=30)
            self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=parsed.hostname)

    connection = PinnedHTTPS(parsed.hostname, timeout=30)
    try:
        target = parsed.path + ("?" + parsed.query if parsed.query else "")
        connection.request("GET", target, headers={"Host": parsed.hostname})
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError(f"Сервер вернул HTTP {response.status}; редиректы не разрешены")
        total = 0
        with Path(destination).open("wb") as stream:
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_UPLOAD:
                    raise ValueError("Файл слишком большой")
                if shutil.disk_usage(STORAGE).free < len(chunk) + 1024**3:
                    raise ValueError("Недостаточно места для скачивания")
                stream.write(chunk)
    finally:
        connection.close()


def remote_suffix(url):
    return Path(urlparse(url).path).suffix.lower()
