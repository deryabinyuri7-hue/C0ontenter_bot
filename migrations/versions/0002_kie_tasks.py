"""store KIE task and result data

Revision ID: 0002_kie_tasks
Revises: 0001_initial
Create Date: 2026-08-13
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_kie_tasks"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("generations", sa.Column("provider_task_id", sa.String(255)))
    op.add_column("generations", sa.Column("result_url", sa.Text()))
    op.add_column("generations", sa.Column("aspect_ratio", sa.String(8)))
    op.create_unique_constraint(
        "uq_generations_provider_task_id", "generations", ["provider_task_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_generations_provider_task_id", "generations", type_="unique")
    op.drop_column("generations", "aspect_ratio")
    op.drop_column("generations", "result_url")
    op.drop_column("generations", "provider_task_id")
