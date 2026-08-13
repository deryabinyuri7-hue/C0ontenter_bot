"""initial C0ontenter schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-13
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    payment_status = sa.Enum("pending", "succeeded", "failed", name="paymentstatus")
    generation_status = sa.Enum(
        "reserved", "processing", "succeeded", "failed", "timed_out", name="generationstatus"
    )
    ledger_kind = sa.Enum(
        "welcome", "payment", "reservation", "refund", "manual", name="ledgerkind"
    )
    ledger_status = sa.Enum("confirmed", "reserved", "refunded", name="ledgerstatus")
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(255)),
        sa.Column("first_name", sa.String(255)),
        sa.Column("language_code", sa.String(16)),
        sa.Column(
            "welcome_credit_granted", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("telegram_id"),
    )
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"])
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider_payment_id", sa.String(255), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("status", payment_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("provider_payment_id"),
    )
    op.create_index("ix_payments_user_id", "payments", ["user_id"])
    op.create_table(
        "generations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("prompt", sa.Text()),
        sa.Column("cost_credits", sa.Integer(), nullable=False),
        sa.Column("status", generation_status, nullable=False),
        sa.Column("error_code", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_generations_user_id", "generations", ["user_id"])
    op.create_table(
        "credit_ledger",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("generation_id", sa.Integer(), sa.ForeignKey("generations.id")),
        sa.Column("payment_id", sa.Integer(), sa.ForeignKey("payments.id")),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("kind", ledger_kind, nullable=False),
        sa.Column("status", ledger_status, nullable=False),
        sa.Column("note", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("payment_id"),
    )
    op.create_index("ix_credit_ledger_user_id", "credit_ledger", ["user_id"])
    op.create_index("ix_credit_ledger_generation_id", "credit_ledger", ["generation_id"])


def downgrade() -> None:
    op.drop_table("credit_ledger")
    op.drop_table("generations")
    op.drop_table("payments")
    op.drop_table("users")
