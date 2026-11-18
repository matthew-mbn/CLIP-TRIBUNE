"""Initial local studio schema."""

from alembic import op
from backend.models import Base

revision = "0001"
down_revision = None


def upgrade():
    Base.metadata.create_all(bind=op.get_bind())


def downgrade():
    Base.metadata.drop_all(bind=op.get_bind())
