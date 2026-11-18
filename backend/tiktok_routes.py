"""Небольшой отдельный роутер: маршруты TikTok легко найти при изучении кода."""

from typing import Literal
from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select

from . import tiktok
from .database import Session, public
from .models import TikTokAccount, TikTokJob
from .schemas import TikTokPublishInput

router = APIRouter(prefix="/api/tiktok")


def required(session, model, identity):
    row = session.get(model, identity)
    if not row:
        raise ValueError("Запись TikTok не найдена")
    return row


@router.get("/accounts")
def accounts():
    with Session() as session:
        return [
            {**public(row), **tiktok.account_access(row)}
            for row in session.scalars(select(TikTokAccount).where(TikTokAccount.tokens != ""))
        ]


class ConnectInput(BaseModel):
    mode: Literal["inbox", "direct"] = "inbox"


@router.post("/connect")
def connect(request: ConnectInput):
    with Session() as session:
        return {"url": tiktok.oauth_start(session, request.mode)}


@router.get("/callback", response_class=HTMLResponse)
def callback(state: str, code: str = "", error: str = ""):
    with Session() as session:
        if error:
            tiktok.consume_tiktok_state(session, state)
            return '<meta charset="utf-8"><h1>Доступ не предоставлен</h1><p>Вернитесь в CLIP TRIBUNE.</p>'
        tiktok.oauth_callback(session, state, code)
    return '<meta charset="utf-8"><h1>TikTok подключён</h1><p>Вернитесь в CLIP TRIBUNE.</p>'


@router.delete("/accounts/{identity}")
def disconnect(identity: str):
    with Session() as session:
        tiktok.disconnect(session, required(session, TikTokAccount, identity))
    return {"disconnected": True}


@router.get("/accounts/{identity}/creator")
def creator(identity: str):
    with Session() as session:
        return tiktok.creator_info(session, required(session, TikTokAccount, identity))


@router.get("/jobs")
def jobs():
    with Session() as session:
        return [
            public(row) for row in session.scalars(select(TikTokJob).order_by(TikTokJob.created_at.desc()))
        ]


@router.post("/jobs")
def create(request: TikTokPublishInput):
    with Session() as session:
        return public(tiktok.enqueue(session, request))


@router.post("/jobs/{identity}/status")
def status(identity: str):
    with Session() as session:
        return public(tiktok.check_status(session, required(session, TikTokJob, identity)))


@router.post("/jobs/{identity}/cancel")
def cancel(identity: str):
    with Session() as session:
        job = required(session, TikTokJob, identity)
        if job.status not in ("pending", "publishing"):
            raise ValueError("Файл уже передан. Управляйте публикацией в TikTok")
        job.status = "cancelled"
        session.commit()
        return public(job)
