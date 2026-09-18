"""Store the per-product color replacements approved for publication."""

import sqlalchemy as sa

from alembic import op

revision = "0004_pub_template"
down_revision = "0003_excluded_shirt_colors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "publication_template_snapshot" not in {
        item["name"] for item in sa.inspect(op.get_bind()).get_columns("workflow_runs")
    }:
        op.add_column(
            "workflow_runs",
            sa.Column("publication_template_snapshot", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("workflow_runs", "publication_template_snapshot")
