"""Официальный YouTube API: OAuth PKCE, квоты, тренды и возобновляемая загрузка."""

import base64
import hashlib
import math
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import delete, select, update

from .database import Session, settings
from .models import OAuthState, PublishJob, QuotaUsage, TrendRecord, YouTubeChannel, now
from .security import decrypt, encrypt

API = "https://www.googleapis.com/youtube/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"


class QuotaExceeded(Exception):
    pass


def secret(name):
    from .models import UserSettings

    with Session() as session:
        row = session.get(UserSettings, 1)
        stored = (row.data if row else {}).get("secrets", {})
        if name in stored:
            return decrypt(stored[name])
    return os.getenv(name, "")


def quota_day():
    return datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")


def reserve_quota(session, bucket, cost=1):
    """Атомарный условный UPDATE не позволяет двум процессам потратить остаток дважды."""
    limit = settings(session)["quota_" + bucket]
    key = quota_day() + ":" + bucket
    if not session.get(QuotaUsage, key):
        from sqlalchemy.exc import IntegrityError

        try:
            with session.begin_nested():
                session.add(QuotaUsage(key=key, count=0))
                session.flush()
        except IntegrityError:
            pass
    changed = session.execute(
        update(QuotaUsage)
        .where(QuotaUsage.key == key, QuotaUsage.count + cost <= limit)
        .values(count=QuotaUsage.count + cost)
    )
    session.commit()
    if not changed.rowcount:
        raise QuotaExceeded(f"Локальный дневной лимит {bucket} исчерпан")


def quota_status(session):
    config = settings(session)
    result = {}
    for bucket in ("search", "upload", "general"):
        row = session.get(QuotaUsage, quota_day() + ":" + bucket)
        used = row.count if row else 0
        result[bucket] = dict(
            used=used, limit=config["quota_" + bucket], remaining=max(0, config["quota_" + bucket] - used)
        )
    return dict(
        buckets=result,
        day=quota_day(),
        estimated=True,
        note="Локальный учёт этого приложения. Фактическая квота — в Google Cloud Console.",
    )


def google_error(response):
    if response.status_code < 400:
        return
    try:
        error = response.json().get("error", {})
        reason = (error.get("errors") or [{}])[0].get("reason", "") if isinstance(error, dict) else error
    except Exception:
        reason = ""
    if reason in ("quotaExceeded", "dailyLimitExceeded", "uploadLimitExceeded", "rateLimitExceeded"):
        raise QuotaExceeded(str(reason))
    # Не включаем URL запроса: в нём может находиться API-ключ.
    raise RuntimeError(f"Google API HTTP {response.status_code}: {reason or 'проверьте доступ и настройки'}")


def oauth_start(session):
    client = secret("GOOGLE_CLIENT_ID")
    if not client:
        raise ValueError("Укажите Google Client ID и Client Secret в настройках")
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    session.add(OAuthState(state=state, verifier=verifier, expires_at=now() + 600))
    session.commit()
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
        dict(
            client_id=client,
            redirect_uri=os.getenv("OAUTH_REDIRECT_URI", "http://127.0.0.1:8765/api/youtube/callback"),
            response_type="code",
            scope=SCOPES,
            state=state,
            access_type="offline",
            prompt="consent",
            code_challenge=challenge,
            code_challenge_method="S256",
        )
    )


def consume_state(session, state):
    row = session.get(OAuthState, state)
    if not row or row.expires_at < now():
        raise ValueError("Недействительный или просроченный OAuth state")
    verifier = row.verifier
    consumed = session.execute(delete(OAuthState).where(OAuthState.state == state))
    session.commit()
    if not consumed.rowcount:
        raise ValueError("Этот OAuth callback уже использован")
    return verifier


def oauth_callback(session, state, code):
    verifier = consume_state(session, state)
    response = httpx.post(
        TOKEN_URL,
        data=dict(
            code=code,
            code_verifier=verifier,
            client_id=secret("GOOGLE_CLIENT_ID"),
            client_secret=secret("GOOGLE_CLIENT_SECRET"),
            redirect_uri=os.getenv("OAUTH_REDIRECT_URI", "http://127.0.0.1:8765/api/youtube/callback"),
            grant_type="authorization_code",
        ),
        timeout=30,
    )
    google_error(response)
    tokens = response.json()
    if not tokens.get("refresh_token"):
        raise ValueError("Google не выдал refresh token. Повторите подключение с разрешением offline access")
    tokens["expires_at"] = now() + tokens.get("expires_in", 3600)
    reserve_quota(session, "general")
    response = httpx.get(
        API + "/channels",
        params={"part": "snippet,statistics", "mine": "true"},
        headers={"Authorization": "Bearer " + tokens["access_token"]},
        timeout=30,
    )
    google_error(response)
    channels = response.json().get("items", [])
    if not channels:
        raise ValueError("У этого Google-аккаунта нет доступного YouTube-канала")
    data = channels[0]
    channel = session.scalar(select(YouTubeChannel).where(YouTubeChannel.youtube_id == data["id"]))
    if not channel:
        channel = YouTubeChannel(youtube_id=data["id"], name=data["snippet"]["title"], tokens="")
        session.add(channel)
    channel.tokens = encrypt(tokens)
    channel.statistics = data.get("statistics", {})
    session.commit()
    return channel


def access_token(session, channel):
    tokens = decrypt(channel.tokens)
    if tokens.get("expires_at", 0) < now() + 60:
        response = httpx.post(
            TOKEN_URL,
            data=dict(
                client_id=secret("GOOGLE_CLIENT_ID"),
                client_secret=secret("GOOGLE_CLIENT_SECRET"),
                refresh_token=tokens["refresh_token"],
                grant_type="refresh_token",
            ),
            timeout=30,
        )
        google_error(response)
        tokens.update(response.json())
        tokens["expires_at"] = now() + tokens.get("expires_in", 3600)
        channel.tokens = encrypt(tokens)
        session.commit()
    return tokens["access_token"]


def disconnect(session, channel):
    tokens = decrypt(channel.tokens)
    response = httpx.post(
        "https://oauth2.googleapis.com/revoke",
        data={"token": tokens.get("refresh_token", tokens.get("access_token"))},
        timeout=30,
    )
    # invalid_token означает, что доступ уже отозван.
    if response.status_code not in (200, 400):
        raise RuntimeError("Не удалось отозвать доступ Google. Повторите отключение")
    session.execute(
        update(PublishJob)
        .where(PublishJob.channel_id == channel.id)
        .values(channel_id=None, status="cancelled", error="Канал отключён", finished_at=now())
    )
    session.delete(channel)
    session.commit()


def search_trends(session, query, region="US", hours=24):
    key = secret("YOUTUBE_API_KEY")
    if not key:
        raise ValueError("Для трендов требуется YouTube API key")
    reserve_quota(session, "search")
    response = httpx.get(
        API + "/search",
        params=dict(
            key=key,
            part="snippet",
            q=query,
            type="video",
            regionCode=region,
            maxResults=20,
            order="viewCount",
            publishedAfter=(datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(),
        ),
        timeout=30,
    )
    google_error(response)
    ids = [item["id"]["videoId"] for item in response.json().get("items", [])]
    if not ids:
        return []
    reserve_quota(session, "general")
    response = httpx.get(
        API + "/videos",
        params=dict(key=key, part="snippet,statistics,contentDetails", id=",".join(ids)),
        timeout=30,
    )
    google_error(response)
    records = []
    for item in response.json().get("items", []):
        snippet, stats = item["snippet"], item.get("statistics", {})
        age = max(
            0.25,
            (
                datetime.now(timezone.utc)
                - datetime.fromisoformat(snippet["publishedAt"].replace("Z", "+00:00"))
            ).total_seconds()
            / 3600,
        )
        views, likes, comments = (int(stats.get(k, 0)) for k in ("viewCount", "likeCount", "commentCount"))
        previous = session.scalar(
            select(TrendRecord)
            .where(TrendRecord.video_id == item["id"])
            .order_by(TrendRecord.created_at.desc())
            .limit(1)
        )
        velocity = views / age
        change = None
        if previous and now() - previous.created_at > 60:
            change = max(0, views - previous.data["views"]) / ((now() - previous.created_at) / 3600)
        relevance = sum(word.lower() in snippet["title"].lower() for word in query.split()) / max(
            1, len(query.split())
        )
        score = min(
            100,
            12 * math.log10(velocity + 1)
            + 20 / (1 + age / 24)
            + min(20, (likes + comments) / max(views, 1) * 300)
            + 10 * relevance
            + (min(10, change / max(velocity, 1) * 5) if change is not None else 0),
        )
        data = dict(
            title=snippet["title"],
            channel=snippet["channelTitle"],
            published_at=snippet["publishedAt"],
            views=views,
            likes=stats.get("likeCount"),
            comments=stats.get("commentCount"),
            duration=item["contentDetails"]["duration"],
            url="https://www.youtube.com/watch?v=" + item["id"],
            tags=snippet.get("tags", []),
            description=snippet.get("description", ""),
            velocity=round(velocity),
            delta_velocity=change,
            region=region,
            idea=f"Оригинальный разбор темы «{query}» на собственных материалах",
        )
        record = TrendRecord(video_id=item["id"], query=query, score=round(score, 1), data=data)
        session.add(record)
        records.append(record)
    session.commit()
    return records


def validate_upload_url(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ("www.googleapis.com", "upload.youtube.com"):
        raise RuntimeError("Google вернул неожиданный адрес загрузки")
    return url


def upload(session, job, clip, cancelled=lambda: False):
    """Сохраняем URL сессии до отправки байтов. После сбоя сначала узнаём offset.

    Истёкшую сессию не пересоздаём автоматически: результат мог уже попасть на
    YouTube. Это предотвращает дубли при неоднозначном сетевом сбое.
    """
    from pathlib import Path
    from .video import Cancelled

    if cancelled():
        raise Cancelled("Загрузка остановлена")
    channel = session.get(YouTubeChannel, job.channel_id)
    if not channel:
        raise ValueError("Выберите подключённый канал")
    headers = {"Authorization": "Bearer " + access_token(session, channel)}
    size = Path(clip.path).stat().st_size
    with httpx.Client(timeout=60, follow_redirects=False) as client:
        if not job.upload_url:
            reserve_quota(session, "upload")
            if cancelled():
                raise Cancelled("Загрузка остановлена")
            status = dict(
                privacyStatus=job.options.get("privacy", "private"),
                selfDeclaredMadeForKids=job.options.get("made_for_kids", False),
                containsSyntheticMedia=job.options.get("synthetic", False),
            )
            response = client.post(
                "https://www.googleapis.com/upload/youtube/v3/videos",
                params={
                    "uploadType": "resumable",
                    "part": "snippet,status"
                    + (",paidProductPlacementDetails" if "paid_product_placement" in job.options else ""),
                },
                headers={
                    **headers,
                    "X-Upload-Content-Length": str(size),
                    "X-Upload-Content-Type": "video/mp4",
                },
                json=dict(
                    snippet=dict(
                        title=clip.title[:100],
                        description=clip.metadata_json.get("description", "")[:5000],
                        tags=clip.metadata_json.get("hashtags", []),
                        categoryId=clip.metadata_json.get("category", "22"),
                    ),
                    status=status,
                    **(
                        {
                            "paidProductPlacementDetails": {
                                "hasPaidProductPlacement": job.options["paid_product_placement"]
                            }
                        }
                        if "paid_product_placement" in job.options
                        else {}
                    ),
                ),
            )
            google_error(response)
            job.upload_url = encrypt(validate_upload_url(response.headers["Location"]))
            session.commit()
        url = validate_upload_url(decrypt(job.upload_url))
        # Запрос состояния работает и после перезапуска программы.
        response = client.put(
            url, headers={**headers, "Content-Length": "0", "Content-Range": f"bytes */{size}"}
        )
        if response.status_code in (200, 201):
            return response.json()["id"]
        if response.status_code != 308:
            google_error(response)
            raise RuntimeError(
                "Не удалось восстановить загрузку; проверьте YouTube Studio перед новой попыткой"
            )
        offset = (
            int(response.headers.get("Range", "bytes=0--1").rsplit("-", 1)[-1]) + 1
            if response.headers.get("Range")
            else 0
        )
        with open(clip.path, "rb") as stream:
            while offset < size:
                if cancelled():
                    raise Cancelled("Загрузка остановлена")
                stream.seek(offset)
                chunk = stream.read(8 * 1024**2)
                response = client.put(
                    url,
                    content=chunk,
                    headers={
                        **headers,
                        "Content-Type": "video/mp4",
                        "Content-Range": f"bytes {offset}-{offset + len(chunk) - 1}/{size}",
                    },
                )
                if response.status_code in (200, 201):
                    return response.json()["id"]
                if response.status_code != 308:
                    google_error(response)
                    raise RuntimeError("Неожиданный ответ загрузки")
                next_offset = int(response.headers["Range"].split("-")[-1]) + 1
                if next_offset <= offset:
                    raise RuntimeError("Сервер не подтвердил получение следующего блока")
                offset = next_offset
                job.progress = round(offset / size * 100, 1)
                job.updated_at = now()
                session.commit()
    raise RuntimeError("Сервер не подтвердил завершение загрузки")


def processing_status(session, channel, video_id):
    reserve_quota(session, "general")
    response = httpx.get(
        API + "/videos",
        params={"part": "status,processingDetails", "id": video_id},
        headers={"Authorization": "Bearer " + access_token(session, channel)},
        timeout=30,
    )
    google_error(response)
    return response.json()
