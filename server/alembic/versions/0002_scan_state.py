"""items: brand/model + scan-pipeline state

brand/model are an addition over the CLAUDE.md §4 sketch: the duplicate-template signature
(Phase 3) is built from brand+model+category tokens, and template creation happens at SALE
time — long after the vision draft response is gone — so they must persist on the item.
processed_at/scan_error let the async scan pipeline report per-draft state honestly
(NULL processed_at = still running; scan_error = why it died).

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-25

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("items", sa.Column("brand", sa.String(length=64), nullable=True))
    op.add_column("items", sa.Column("model", sa.String(length=64), nullable=True))
    op.add_column("items", sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("items", sa.Column("scan_error", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("items", "scan_error")
    op.drop_column("items", "processed_at")
    op.drop_column("items", "model")
    op.drop_column("items", "brand")
