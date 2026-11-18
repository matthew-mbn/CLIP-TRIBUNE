"""Проверяем новую установку и обновление базы без потери подключений."""

from pathlib import Path
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from backend import database


@pytest.mark.parametrize("legacy", [False, True])
def test_auto_migration_preserves_old_account_and_stays_off(tmp_path, monkeypatch, legacy):
    engine = sa.create_engine("sqlite:///" + str(tmp_path / "migration.db"))
    monkeypatch.setattr(database, "engine", engine)
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "backend/migrations"))
    try:
        if legacy:
            command.upgrade(config, "0005")
            with engine.begin() as connection:
                # 0001 использует актуальные модели: убираем новое поле,
                # чтобы воспроизвести схему реально установленной 0.5.0.
                connection.execute(sa.text("ALTER TABLE live_recordings DROP COLUMN auto_tiktok_enabled"))
                connection.execute(
                    sa.text(
                        "INSERT INTO tiktok_accounts (id,created_at,open_id,name,tokens) VALUES ('a',1,'test','Creator','encrypted-test-token')"
                    )
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO live_recordings (id,created_at,url,title,platform,status,options,clipping_enabled,updated_at,seconds,bytes,message) VALUES ('r',1,'https://www.twitch.tv/example','Stream','twitch','finished','{}',1,1,0,0,'Done')"
                    )
                )
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == "0006"
            if legacy:
                assert (
                    connection.scalar(sa.text("SELECT tokens FROM tiktok_accounts WHERE id='a'"))
                    == "encrypted-test-token"
                )
                assert (
                    connection.scalar(sa.text("SELECT auto_tiktok_enabled FROM live_recordings WHERE id='r'"))
                    == 0
                )
    finally:
        engine.dispose()
