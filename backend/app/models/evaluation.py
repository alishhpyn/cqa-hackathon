
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    ForeignKey,
    DateTime,
    Text,
    Index,
    text
)
from sqlalchemy.sql import func

from app.database.database import Base


class Evaluation(Base):
    __tablename__ = "evaluations"

    __table_args__ = (
        Index(
            "uq_active_evaluation",
            "conversation_id",
            "checklist_id",
            "checklist_version",
            unique=True,
            sqlite_where=text("status IN ('queued', 'running')")
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    conversation_id = Column(String, nullable=False)

    checklist_id = Column(
        Integer,
        ForeignKey("checklists.id"),
        nullable=False
    )

    score = Column(Float, nullable=True)
    gross_violation = Column(Boolean, default=False)

    status = Column(String, nullable=False, default="completed")
    checklist_version = Column(String, nullable=True)
    result_json = Column(Text, nullable=True)
    error = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )


class CriterionResult(Base):
    __tablename__ = "criterion_results"

    id = Column(Integer, primary_key=True, index=True)

    evaluation_id = Column(
        Integer,
        ForeignKey("evaluations.id"),
        nullable=False
    )

    criterion_id = Column(Integer, nullable=False)
    criterion_name = Column(String, nullable=False)

    answer = Column(String, nullable=False)
    weight = Column(Float, nullable=False)
    points = Column(Float, nullable=False)
