"""Защита от одновременной обработки исходника и повторной публикации."""

from alembic import op
from sqlalchemy import inspect, text

revision = "0002"
down_revision = "0001"


def upgrade():
    # Новая установка уже получает индексы вместе с таблицами первой миграции.
    for table, name, column in [
        ("render_jobs", "uq_active_asset_job", "asset_id"),
        ("publish_jobs", "uq_publish_clip", "clip_id"),
    ]:
        if name not in {index["name"] for index in inspect(op.get_bind()).get_indexes(table)}:
            filters = (
                dict(
                    sqlite_where=text("status IN ('pending', 'analyzing', 'rendering')"),
                    postgresql_where=text("status IN ('pending', 'analyzing', 'rendering')"),
                )
                if table == "render_jobs"
                else {}
            )
            op.create_index(name, table, [column], unique=True, **filters)


def downgrade():
    op.drop_index("uq_active_asset_job", table_name="render_jobs")
    op.drop_index("uq_publish_clip", table_name="publish_jobs")
