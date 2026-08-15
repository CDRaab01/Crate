"""item_photos: what each photo is a photo OF

Capture is becoming guided — the app asks for the front, then the tag, rather than
accepting N undifferentiated shots — and the server needs to know which is which for three
separate reasons, none of which order can answer:

  * Identification reads only the first MAX_IDENTIFY_PHOTOS photos by order, so a tag shot
    taken fourth never reaches the model at all.
  * The narrow label pass (size/size_type/material) has to be pointed at the tag photo
    specifically; running it over a garment shot is wasted latency and invites a guess.
  * eBay treats the first uploaded photo as the listing's gallery image, and today that is
    simply whichever photo was taken first — so a tag-first shoot would put a care label on
    the face of a listing.

Nullable, deliberately: every photo captured before guided capture existed has no known
role, and "we don't know" must not be encoded as "front" — that would silently promote an
arbitrary photo to hero image. Membership is enforced in the app (PHOTO_ROLES +
normalize_enum), like every other Crate vocabulary; there are no CHECK constraints in this
schema and this is not the place to start one.

Note role is deliberately NOT part of any filename. photo_store derives original_{n}/
cleaned_{n} from order, and both the photo_file route and the delete path depend on that,
so role stays a column and cover-ness stays a derived property.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("item_photos", sa.Column("role", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("item_photos", "role")
