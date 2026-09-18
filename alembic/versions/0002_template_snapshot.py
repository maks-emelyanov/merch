"""Keep the approved product template with each run."""

import sqlalchemy as sa

from alembic import op

revision = "0002_template_snapshot"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "template_snapshot" not in {
        item["name"] for item in sa.inspect(op.get_bind()).get_columns("workflow_runs")
    }:
        op.add_column("workflow_runs", sa.Column("template_snapshot", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("workflow_runs", "template_snapshot")
