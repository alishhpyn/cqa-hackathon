
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey
)
from sqlalchemy.sql import func

from app.database.database import Base


class Appeal(Base):
    __tablename__ = "appeals"

    id = Column(Integer, primary_key=True, index=True)

    evaluation_id = Column(
        Integer,
        ForeignKey("evaluations.id"),
        nullable=False
    )

    criterion_result_id = Column(
        Integer,
        ForeignKey("criterion_results.id"),
        nullable=False
    )

    comment = Column(Text, nullable=False)
    original_answer = Column(String, nullable=True)

    status = Column(
        String,
        default="pending",
        nullable=False
    )

    reviewer_answer = Column(String, nullable=True)
    reviewer_reason = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    reviewed_at = Column(
        DateTime(timezone=True),
        nullable=True
    )
