"""Отдельный выключатель автопубликации: остановка не зависит от JSON-параметров."""

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"


def upgrade():
    # Старые миграции создают таблицы из текущих моделей. В новой базе поле
    # уже существует; в базе предыдущего EXE добавляем его, не меняя данные.
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("live_recordings")}
    if "auto_tiktok_enabled" in columns:
        return
    op.add_column(
        "live_recordings",
        sa.Column("auto_tiktok_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("live_recordings", "auto_tiktok_enabled")
