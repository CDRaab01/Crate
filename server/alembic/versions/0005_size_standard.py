"""items: the eBay-standardized size, alongside what the tag actually says

eBay's Size Standardization programme (developer blog, "Size Standardization for eBay
Fashion Listings") began auto-normalizing high-confidence size values in June 2026 and moved
to **full enforcement in August 2026**: apparel and footwear listings with non-standard or
missing size values are "blocked from the site or placed on hold", and the ability to send
custom size values on new listings has been removed.

That collides head-on with a deliberate decision in `apparel/attributes.py`:

    Free-text fields (size, color, material, style) are deliberately NOT enumerated — real
    tags say "Heather Grey", "60% cotton / 40% poly", "M/L". Constraining them would lose
    data that a human read off the garment, which is the one thing this workflow cannot
    re-derive later.

That reasoning is still correct for the ARCHIVE and now wrong for the LISTING. Real readings
from the label pass include "M/L", "別大" and "EUR 30 / US 30 / CN 170/76A" — every one of
them irreplaceable once the garment is boxed, and every one of them now unlistable.

So the two meanings get two columns rather than one column with a lossy compromise:

  * `size`          — unchanged. What is printed on the tag, free text, the archive record.
  * `size_standard` — what eBay is told. Chosen by the human at review from the values eBay
                      itself publishes for the listing's category, so the vocabulary is
                      never guessed and never goes stale in our code.

Nullable, like every other apparel column: pre-existing rows keep their tag text and simply
have no listing value yet, which `_require_ready` reports as a gap the human can fill —
rather than a migration inventing sizes for a wardrobe it has never seen.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-16

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("items", sa.Column("size_standard", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("items", "size_standard")
