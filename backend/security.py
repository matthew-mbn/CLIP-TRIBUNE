"""Защита локальных файлов и секретов. Эти функции общие для API и воркера."""

import hashlib
import ipaddress
import json
import os
import socket
from pathlib import Path
from urllib.parse import urlparse

from cryptography.fernet import Fernet

from .config import STORAGE


def cipher():
    # Ключ лежит отдельно от базы. Без него резервная копия токенов бесполезна.
    key_file = STORAGE / ".encryption.key"
    if not key_file.exists():
        try:
            with key_file.open("xb") as stream:
                stream.write(Fernet.generate_key())
            if os.name != "nt":
                key_file.chmod(0o600)
        except FileExistsError:
            pass
    return Fernet(key_file.read_bytes())


def encrypt(value):
    return cipher().encrypt(json.dumps(value).encode()).decode()


def decrypt(value):
    return json.loads(cipher().decrypt(value.encode()))


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inside(path, root=STORAGE):
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(Path(root).resolve()):
        raise ValueError("Файл находится вне разрешённой папки")
    return resolved


def public_url(url):
    """Проверка URL перед сетевым запросом. Возвращает проверенные публичные IP."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Нужна прямая HTTPS-ссылка без логина и пароля")
    if parsed.port not in (None, 443):
        raise ValueError("Разрешён только HTTPS-порт 443")
    addresses = {info[4][0] for info in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)}
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("Локальные и внутренние сетевые адреса запрещены")
    return parsed, sorted(addresses)
