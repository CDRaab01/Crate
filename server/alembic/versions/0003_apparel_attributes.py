"""items: apparel item specifics + storage location

The archive-first round. Crate photographs a wardrobe now and lists it whenever the eBay
keyset arrives, which makes tag data (size/size_type/department/material) and tape-measure
data (measurements_in) load-bearing: they exist only on the physical garment, so a draft
captured without them costs an unboxing to repair. item_kind gates the whole apparel block
so general goods (the original lure/tool path) are unaffected — existing rows default to
'general' and read exactly as they did before.

storage_location is the other half of the same problem: a registry that can't tell you
which bin a sold shirt is in is not usable at ship time.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-12

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (column, type) in model declaration order; downgrade drops them in reverse.
_COLUMNS = (
    ("item_kind", sa.String(length=16)),
    ("size", sa.String(length=32)),
    ("size_type", sa.String(length=16)),
    ("department", sa.String(length=16)),
    ("color", sa.String(length=48)),
    ("material", sa.String(length=96)),
    ("style", sa.String(length=64)),
    ("fit", sa.String(length=16)),
    ("sleeve_length", sa.String(length=16)),
    ("measurements_in", sa.JSON()),
    ("storage_location", sa.String(length=64)),
)


def upgrade() -> None:
    # item_kind is NOT NULL with a server default so pre-existing drafts stay valid without
    # a backfill pass; everything else is honestly nullable (absent = nobody has read the
    # tag yet, which is exactly what the completeness check reports).
    op.add_column(
        "items",
        sa.Column("item_kind", sa.String(length=16), nullable=False, server_default="general"),
    )
    for name, type_ in _COLUMNS:
        if name == "item_kind":
            continue
        op.add_column("items", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(_COLUMNS):
        op.drop_column("items", name)
