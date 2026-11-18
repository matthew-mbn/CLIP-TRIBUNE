"""Официальный TikTok API: Desktop OAuth, черновики и Direct Post.

Каждая отправка требует решения пользователя. Передачу файла и обработку TikTok
считаем разными стадиями: HTTP 201 ещё не означает, что ролик опубликован.
"""

import hashlib
import secrets
from urllib.parse import urlencode, urlparse

import httpx
from sqlalchemy import select, update

from .database import Session
from .models import OAuthState, RenderedClip, TikTokAccount, TikTokJob, now
from .security import decrypt, encrypt, inside
from .youtube import consume_state, secret

API = "https://open.tiktokapis.com/v2"
REDIRECT = "http://127.0.0.1:8765/api/tiktok/callback"


def decoded(response, token_response=False):
    """Не возвращаем пользователю URL с токенами или сырое тело сетевой ошибки."""
    try:
        data = response.json()
    except ValueError:
        raise RuntimeError(f"TikTok: некорректный ответ (HTTP {response.status_code})") from None
    error = data.get("error", {})
    code = error.get("code", "ok") if isinstance(error, dict) else error
    if response.is_error or code not in (None, "", "ok"):
        raise RuntimeError(f"TikTok: {code or 'ошибка запроса'} (HTTP {response.status_code})")
    return data if token_response else data.get("data", {})


def credentials():
    key, password = secret("TIKTOK_CLIENT_KEY"), secret("TIKTOK_CLIENT_SECRET")
    if not key or not password:
        raise ValueError("В настройках TikTok укажите Client Key и Client Secret своего приложения")
    return dict(client_key=key, client_secret=password)


def oauth_start(session, mode):
    values = credentials()
    verifier = secrets.token_urlsafe(64)
    state = "tt_" + secrets.token_urlsafe(32)
    session.add(OAuthState(state=state, verifier=verifier, expires_at=now() + 600))
    session.commit()
    # TikTok Desktop требует SHA256 в hex, в отличие от base64url у Google.
    return "https://www.tiktok.com/v2/auth/authorize/?" + urlencode(
        dict(
            client_key=values["client_key"],
            response_type="code",
            redirect_uri=REDIRECT,
            scope="user.info.basic," + ("video.publish" if mode == "direct" else "video.upload"),
            state=state,
            code_challenge=hashlib.sha256(verifier.encode()).hexdigest(),
            code_challenge_method="S256",
        )
    )


def consume_tiktok_state(session, state):
    if not state.startswith("tt_"):
        raise ValueError("Это не запрос авторизации TikTok")
    return consume_state(session, state)


def oauth_callback(session, state, code):
    verifier = consume_tiktok_state(session, state)
    tokens = decoded(
        httpx.post(
            API + "/oauth/token/",
            data=dict(
                **credentials(),
                code=code,
                code_verifier=verifier,
                redirect_uri=REDIRECT,
                grant_type="authorization_code",
            ),
            timeout=30,
        ),
        True,
    )
    if not tokens.get("access_token") or not tokens.get("refresh_token"):
        raise ValueError("TikTok не выдал необходимые токены доступа")
    tokens["expires_at"] = now() + tokens["expires_in"]
    user = decoded(
        httpx.get(
            API + "/user/info/",
            params={"fields": "open_id,display_name"},
            headers={"Authorization": "Bearer " + tokens["access_token"]},
            timeout=30,
        )
    )["user"]
    account = session.scalar(select(TikTokAccount).where(TikTokAccount.open_id == tokens["open_id"]))
    if not account:
        account = TikTokAccount(open_id=tokens["open_id"], name=user["display_name"], tokens="")
        session.add(account)
    account.name, account.tokens = user["display_name"], encrypt(tokens)
    session.commit()
    return account


def access_token(session, account):
    tokens = decrypt(account.tokens)
    if tokens.get("expires_at", 0) < now() + 60:
        fresh = decoded(
            httpx.post(
                API + "/oauth/token/",
                data=dict(
                    **credentials(),
                    refresh_token=tokens["refresh_token"],
                    grant_type="refresh_token",
                ),
                timeout=30,
            ),
            True,
        )
        tokens.update(fresh)  # Сохраняем также новый refresh_token после ротации.
        tokens["expires_at"] = now() + fresh["expires_in"]
        account.tokens = encrypt(tokens)
        session.commit()
    return tokens["access_token"]


def post(session, account, endpoint, payload):
    try:
        response = httpx.post(
            API + endpoint,
            json=payload,
            headers={"Authorization": "Bearer " + access_token(session, account)},
            timeout=45,
        )
        return decoded(response)
    except httpx.RequestError:
        raise RuntimeError("Не удалось связаться с TikTok. Проверьте соединение и статус отправки.") from None


def creator_info(session, account):
    return post(session, account, "/post/publish/creator_info/query/", {})


def disconnect(session, account):
    decoded(
        httpx.post(
            API + "/oauth/revoke/",
            data=dict(
                **credentials(),
                token=access_token(session, account),
            ),
            timeout=30,
        ),
        True,
    )
    # История сохраняется; пустой токен означает отозванное подключение.
    account.tokens = ""
    session.execute(
        update(TikTokJob)
        .where(TikTokJob.account_id == account.id, TikTokJob.status == "pending")
        .values(status="cancelled")
    )
    session.commit()


def validate_direct(options, info, duration):
    if options["privacy_level"] not in info["privacy_level_options"]:
        raise ValueError("Выберите доступную видимость TikTok; значение по умолчанию не назначается")
    if duration > info["max_video_post_duration_sec"]:
        raise ValueError(
            f"TikTok разрешает этому аккаунту видео до {info['max_video_post_duration_sec']} сек."
        )
    for name in ("comment", "duet", "stitch"):
        if options["allow_" + name] and info[name + "_disabled"]:
            raise ValueError(f"В настройках аккаунта TikTok отключено: {name}")
    if options["commercial"] and not (options["brand_organic"] or options["brand_content"]):
        raise ValueError("Укажите, чей бренд продвигается в коммерческом видео")
    if not options["commercial"] and (options["brand_organic"] or options["brand_content"]):
        raise ValueError("Включите раскрытие коммерческого контента")
    if options["brand_content"] and options["privacy_level"] == "SELF_ONLY":
        raise ValueError("Реклама другого бренда не может иметь видимость «Только я»")


def enqueue(session, request):
    if not request.consent:
        raise ValueError("Подтвердите отправку и условия TikTok")
    clip, account = session.get(RenderedClip, request.clip_id), session.get(TikTokAccount, request.account_id)
    if not clip or not account or not account.tokens:
        raise ValueError("Выберите готовое видео и подключённый аккаунт TikTok")
    if not inside(clip.path).is_file():
        raise ValueError("Файл ролика не найден")
    required_scope = "video.publish" if request.mode == "direct" else "video.upload"
    if required_scope not in decrypt(account.tokens).get("scope", "").split(","):
        raise ValueError("Переподключите TikTok с разрешением для выбранного способа отправки")
    if session.scalar(
        select(TikTokJob).where(TikTokJob.clip_id == clip.id, TikTokJob.account_id == account.id)
    ):
        raise ValueError(
            "Этот ролик уже есть в истории TikTok. Проверьте его статус перед повторной отправкой"
        )
    options = request.model_dump()
    if request.mode == "direct":
        validate_direct(options, creator_info(session, account), clip.duration)
    job = TikTokJob(clip_id=clip.id, account_id=account.id, mode=request.mode, options=options)
    session.add(job)
    session.commit()
    return job


def chunk_plan(size):
    if size <= 0 or size > 4 * 1024**3:
        raise ValueError("TikTok: размер MP4 должен быть от 1 байта до 4 ГБ")
    chunk = min(size, 10 * 1024**2)
    return chunk, max(1, size // chunk)


def upload(session, job):
    account = session.get(TikTokAccount, job.account_id)
    clip = session.get(RenderedClip, job.clip_id)
    path = inside(clip.path)
    size = path.stat().st_size
    chunk_size, count = chunk_plan(size)
    payload = dict(
        source_info=dict(
            source="FILE_UPLOAD", video_size=size, chunk_size=chunk_size, total_chunk_count=count
        )
    )
    endpoint = "/post/publish/inbox/video/init/"
    if job.mode == "direct":
        validate_direct(job.options, creator_info(session, account), clip.duration)
        o = job.options
        payload["post_info"] = dict(
            title=o["title"],
            privacy_level=o["privacy_level"],
            disable_comment=not o["allow_comment"],
            disable_duet=not o["allow_duet"],
            disable_stitch=not o["allow_stitch"],
            brand_organic_toggle=o["brand_organic"],
            brand_content_toggle=o["brand_content"],
            is_aigc=o["synthetic"],
        )
        endpoint = "/post/publish/video/init/"
    # После init не повторяем создание поста автоматически: это могло бы создать дубль.
    data = post(session, account, endpoint, payload)
    job.publish_id, job.upload_url = data["publish_id"], encrypt(data["upload_url"])
    session.commit()
    parsed = urlparse(data["upload_url"])
    if (
        parsed.scheme != "https"
        or not (parsed.hostname or "").endswith(".tiktokapis.com")
        or parsed.username
        or parsed.port not in (None, 443)
    ):
        raise RuntimeError("TikTok вернул недопустимый адрес загрузки")
    with path.open("rb") as stream:
        offset = 0
        for index in range(count):
            session.refresh(job)
            if job.status == "cancelled":
                return
            block = stream.read(size - offset if index == count - 1 else chunk_size)
            try:
                response = httpx.put(
                    data["upload_url"],
                    content=block,
                    headers={
                        "Content-Type": "video/mp4",
                        "Content-Length": str(len(block)),
                        "Content-Range": f"bytes {offset}-{offset + len(block) - 1}/{size}",
                    },
                    timeout=120,
                    follow_redirects=False,
                )
            except httpx.RequestError:
                raise RuntimeError(
                    "Соединение прервано. Проверьте статус TikTok; повторная отправка отключена для защиты от дублей"
                ) from None
            if response.status_code != (201 if index == count - 1 else 206):
                raise RuntimeError(
                    f"TikTok: ошибка передачи файла HTTP {response.status_code}. Проверьте статус"
                )
            offset += len(block)
            # Условное обновление не затирает отмену, сделанную из другого процесса.
            session.execute(
                update(TikTokJob)
                .where(TikTokJob.id == job.id, TikTokJob.status == "publishing")
                .values(progress=offset / size * 100, updated_at=now())
            )
            session.commit()
    session.execute(
        update(TikTokJob)
        .where(TikTokJob.id == job.id, TikTokJob.status == "publishing")
        .values(status="processing", updated_at=now())
    )
    session.commit()


def check_status(session, job):
    if not job.publish_id:
        raise ValueError("TikTok ещё не выдал идентификатор отправки")
    account = session.get(TikTokAccount, job.account_id)
    if not account.tokens:
        raise ValueError("Подключите аккаунт TikTok заново")
    data = post(session, account, "/post/publish/status/fetch/", {"publish_id": job.publish_id})
    remote = data.get("status", "")
    job.result = data
    if remote == "PUBLISH_COMPLETE":
        job.status, job.progress, job.error = "published", 100, None
    elif remote == "SEND_TO_USER_INBOX":
        job.status, job.progress, job.error = "inbox", 100, None
    elif remote == "FAILED":
        job.status, job.error = "failed", data.get("fail_reason", "TikTok не обработал видео")
    job.updated_at = now()
    session.commit()
    return job


def tick():
    """Один последовательный отправитель, а опрос обработки ограничен по частоте."""
    with Session() as session:
        # После аварийного закрытия неопределённый результат требует проверки, не повторной загрузки.
        session.execute(
            update(TikTokJob)
            .where(TikTokJob.status == "publishing", TikTokJob.updated_at < now() - 180)
            .values(status="interrupted", error="Отправка прервана. Проверьте статус в TikTok")
        )
        session.commit()
        job = session.scalar(
            select(TikTokJob).where(TikTokJob.status == "pending").order_by(TikTokJob.created_at)
        )
        if job:
            claimed = session.execute(
                update(TikTokJob)
                .where(TikTokJob.id == job.id, TikTokJob.status == "pending")
                .values(status="publishing", updated_at=now())
            )
            session.commit()
            if claimed.rowcount:
                try:
                    upload(session, job)
                except Exception as error:
                    session.rollback()
                    session.refresh(job)
                    if job.status != "cancelled":
                        job.status, job.error = "interrupted" if job.publish_id else "failed", str(error)
                        session.commit()
        waiting = session.scalar(
            select(TikTokJob)
            .where(TikTokJob.status == "processing", TikTokJob.updated_at < now() - 15)
            .order_by(TikTokJob.updated_at)
        )
        if waiting:
            try:
                check_status(session, waiting)
            except Exception as error:
                waiting.updated_at, waiting.error = now(), str(error)
                session.commit()
