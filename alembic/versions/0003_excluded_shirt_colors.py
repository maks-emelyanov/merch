"""Record product-specific shirt colors excluded by contrast QA."""

import sqlalchemy as sa

from alembic import op

revision = "0003_excluded_shirt_colors"
down_revision = "0002_template_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "excluded_shirt_colors" not in {
        item["name"] for item in sa.inspect(op.get_bind()).get_columns("workflow_runs")
    }:
        op.add_column("workflow_runs", sa.Column("excluded_shirt_colors", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("workflow_runs", "excluded_shirt_colors")
