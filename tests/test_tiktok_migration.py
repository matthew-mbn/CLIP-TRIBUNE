"""Проверяем новую установку и обновление базы без потери подключений."""

from pathlib import Path
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from backend import database


@pytest.mark.parametrize("legacy", [None, "0005", "0006", "0007"])
def test_auto_migration_preserves_old_account_and_stays_off(tmp_path, monkeypatch, legacy):
    engine = sa.create_engine("sqlite:///" + str(tmp_path / "migration.db"))
    monkeypatch.setattr(database, "engine", engine)
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "backend/migrations"))
    try:
        if legacy:
            command.upgrade(config, legacy)
            with engine.begin() as connection:
                # 0001 использует актуальные модели: убираем новое поле,
                # чтобы воспроизвести схему реально установленной 0.5.0.
                columns = ["creator_name"]
                if legacy != "0007":
                    columns += ["auto_youtube_enabled", "youtube_auto_state"]
                for column in columns:
                    connection.execute(sa.text(f"ALTER TABLE live_recordings DROP COLUMN {column}"))
                if legacy == "0005":
                    connection.execute(sa.text("ALTER TABLE live_recordings DROP COLUMN auto_tiktok_enabled"))
                connection.execute(
                    sa.text(
                        "INSERT INTO tiktok_accounts (id,created_at,open_id,name,tokens) VALUES ('a',1,'test','Creator','encrypted-test-token')"
                    )
                )
                extra_column, extra_value = (",auto_tiktok_enabled", ",0") if legacy != "0005" else ("", "")
                if legacy == "0007":
                    extra_column += ",auto_youtube_enabled,youtube_auto_state"
                    extra_value += ",0,'{}'"
                connection.execute(
                    sa.text(
                        f"INSERT INTO live_recordings (id,created_at,url,title,platform,status,options,clipping_enabled,updated_at,seconds,bytes,message{extra_column}) VALUES ('r',1,'https://www.twitch.tv/example','Stream','twitch','finished','{{}}',1,1,0,0,'Done'{extra_value})"
                    )
                )
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == "0008"
            if legacy:
                assert (
                    connection.scalar(sa.text("SELECT tokens FROM tiktok_accounts WHERE id='a'"))
                    == "encrypted-test-token"
                )
                assert (
                    connection.scalar(sa.text("SELECT auto_tiktok_enabled FROM live_recordings WHERE id='r'"))
                    == 0
                )
                assert (
                    connection.scalar(
                        sa.text("SELECT auto_youtube_enabled FROM live_recordings WHERE id='r'")
                    )
                    == 0
                )
                assert (
                    connection.scalar(sa.text("SELECT youtube_auto_state FROM live_recordings WHERE id='r'"))
                    == "{}"
                )
                assert (
                    connection.scalar(sa.text("SELECT creator_name FROM live_recordings WHERE id='r'")) == ""
                )
    finally:
        engine.dispose()
