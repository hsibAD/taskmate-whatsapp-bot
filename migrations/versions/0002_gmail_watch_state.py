"""Persist Gmail history cursor and watch expiration."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "gmail_watch_states" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "gmail_watch_states",
        sa.Column("email_address", sa.String(length=320), nullable=False),
        sa.Column("history_id", sa.String(length=255), nullable=False),
        sa.Column("expiration_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("email_address"),
    )


def downgrade() -> None:
    if "gmail_watch_states" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("gmail_watch_states")
