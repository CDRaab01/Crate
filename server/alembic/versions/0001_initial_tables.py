"""initial tables — the full CLAUDE.md §4 schema

Revision ID: 0001
Revises:
Create Date: 2026-07-25

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "duplicate_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("item_signature", sa.String(length=255), nullable=False),
        sa.Column("title_template", sa.String(length=80), nullable=False),
        sa.Column("description_template", sa.Text(), nullable=False),
        sa.Column("category_id", sa.String(length=32), nullable=True),
        sa.Column("condition_notes", sa.Text(), nullable=True),
        sa.Column("last_used_price", sa.Numeric(10, 2), nullable=True),
        sa.Column("use_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_duplicate_templates_user_id", "duplicate_templates", ["user_id"], unique=False
    )
    op.create_index(
        "ix_duplicate_templates_item_signature",
        "duplicate_templates",
        ["item_signature"],
        unique=False,
    )

    op.create_table(
        "items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=80), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category_id", sa.String(length=32), nullable=True),
        sa.Column("condition", sa.String(length=16), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("quick_sale_price", sa.Numeric(10, 2), nullable=True),
        sa.Column("patient_price", sa.Numeric(10, 2), nullable=True),
        sa.Column("chosen_price", sa.Numeric(10, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default="USD", nullable=False),
        sa.Column("ebay_listing_id", sa.String(length=64), nullable=True),
        sa.Column("ebay_offer_id", sa.String(length=64), nullable=True),
        sa.Column("weight_oz_est", sa.Numeric(8, 2), nullable=True),
        sa.Column("dims_in_est", sa.JSON(), nullable=True),
        sa.Column("weight_confirmed", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=True),
        sa.Column("date_listed", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["template_id"], ["duplicate_templates.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_items_user_id", "items", ["user_id"], unique=False)

    op.create_table(
        "item_photos",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column("original_path", sa.String(length=512), nullable=False),
        sa.Column("cleaned_path", sa.String(length=512), nullable=True),
        sa.Column("ebay_url", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_item_photos_item_id", "item_photos", ["item_id"], unique=False)

    op.create_table(
        "sales",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("ebay_order_id", sa.String(length=64), nullable=False),
        sa.Column("sale_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("fees", sa.Numeric(10, 2), nullable=True),
        sa.Column("sale_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("buyer_username", sa.String(length=128), nullable=False),
        sa.Column("buyer_address", sa.JSON(), nullable=False),
        sa.Column("ship_status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("tracking_number", sa.String(length=64), nullable=True),
        sa.Column("carrier", sa.String(length=32), nullable=True),
        sa.Column("service", sa.String(length=64), nullable=True),
        sa.Column("label_cost", sa.Numeric(8, 2), nullable=True),
        sa.Column("label_url", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sales_item_id", "sales", ["item_id"], unique=False)
    op.create_index("ix_sales_ebay_order_id", "sales", ["ebay_order_id"], unique=True)

    op.create_table(
        "buyer_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=True),
        sa.Column("ebay_message_id", sa.String(length=64), nullable=False),
        sa.Column("message_type", sa.String(length=20), server_default="other", nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("flagged_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved", sa.Boolean(), server_default="false", nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_buyer_messages_item_id", "buyer_messages", ["item_id"], unique=False)
    op.create_index(
        "ix_buyer_messages_ebay_message_id", "buyer_messages", ["ebay_message_id"], unique=True
    )

    op.create_table(
        "price_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("old_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("new_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("reason", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_price_events_item_id", "price_events", ["item_id"], unique=False)

    op.create_table(
        "ebay_credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("access_token_enc", sa.Text(), nullable=False),
        sa.Column("refresh_token_enc", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refresh_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("environment", sa.String(length=16), server_default="sandbox", nullable=False),
        sa.Column("scopes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ebay_credentials_user_id", "ebay_credentials", ["user_id"], unique=True)

    op.create_table(
        "user_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("drops_enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("drop_interval_days", sa.Integer(), server_default="14", nullable=False),
        sa.Column("drop_step_percent", sa.Numeric(4, 1), server_default="10.0", nullable=False),
        sa.Column("shipping_preference", sa.String(length=16), server_default="cheapest", nullable=False),
        sa.Column("ntfy_topic", sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_settings_user_id", "user_settings", ["user_id"], unique=True)


def downgrade() -> None:
    op.drop_table("user_settings")
    op.drop_table("ebay_credentials")
    op.drop_table("price_events")
    op.drop_table("buyer_messages")
    op.drop_table("sales")
    op.drop_table("item_photos")
    op.drop_table("items")
    op.drop_table("duplicate_templates")
    op.drop_table("users")
