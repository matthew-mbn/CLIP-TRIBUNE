"""Имя автора исходника для заголовков, независимо от платформы публикации."""

import re
from urllib.parse import unquote, urlparse


def clean_name(value):
    """Убираем переносы строк и служебные символы, сохраняя Unicode-ники."""
    if not isinstance(value, str):
        return ""
    return " ".join("".join(c for c in value if c.isprintable() or c.isspace()).split()).lstrip("@")[:100]


def source_identity(info, url):
    """Сохраняем только публичное имя и исходную ссылку, без signed URL загрузчика.

    У Twitch-клипа uploader — зритель, создавший клип. Стример находится в channel.
    У YouTube uploader_id — @ник; channel_id — технический ID, его не используем.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    parts = unquote(parsed.path).strip("/").split("/")
    creator = ""
    if host in ("twitch.tv", "www.twitch.tv", "m.twitch.tv", "clips.twitch.tv"):
        platform = "twitch"
        is_clip = host == "clips.twitch.tv" or "clip" in parts
        creator = clean_name(info.get("channel"))
        if not creator and not is_clip:
            creator = clean_name(info.get("uploader_id")) or clean_name(info.get("uploader"))
        if not creator and host != "clips.twitch.tv" and (len(parts) == 1 or "clip" in parts):
            if re.fullmatch(r"[A-Za-z0-9_]{3,25}", parts[0]):
                creator = parts[0]
    elif host in ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"):
        platform = "youtube"
        handle = info.get("uploader_id")
        if isinstance(handle, str) and handle.startswith("@"):
            creator = clean_name(handle)
        if not creator and parts[0].startswith("@"):
            creator = clean_name(parts[0])
        creator = creator or clean_name(info.get("channel")) or clean_name(info.get("uploader"))
    else:
        return {}
    return dict(source_platform=platform, source_creator=creator, source_url=url)


def recording_identity(recording):
    identity = source_identity({}, recording.url)
    if recording.creator_name:
        identity["source_creator"] = recording.creator_name
    return identity


def creator_title(identity):
    """Единый заголовок библиотеки, YouTube и TikTok; лимит YouTube — 100 символов."""
    platform = identity.get("source_platform")
    if platform not in ("twitch", "youtube"):
        return ""  # Для локального файла без сведений об авторе остаётся обычный заголовок.
    creator = clean_name(identity.get("source_creator")) or "автор не определён"
    return f"{platform.upper()}: {creator}"[:100]
