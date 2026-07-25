import datetime
import uuid
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DuplicateTemplate(Base):
    """A reusable listing pattern (e.g. the same lure model sold before).

    item_signature is NORMALIZED TEXT — casefolded brand+model+category tokens, not an
    embedding: LM Studio vision gives no image-embedding path, and text signatures are
    testable (CLAUDE.md §4). Matching lives in a pure module (Phase 3).
    """

    __tablename__ = "duplicate_templates"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    item_signature: Mapped[str] = mapped_column(String(255), index=True)
    title_template: Mapped[str] = mapped_column(String(80))
    description_template: Mapped[str] = mapped_column(Text)
    category_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    condition_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_used_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    use_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_used_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
