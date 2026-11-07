
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    ForeignKey,
    JSON
)
from sqlalchemy.orm import relationship

from app.database.database import Base


class Checklist(Base):
    __tablename__ = "checklists"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    channel = Column(String, nullable=False)
    language = Column(String, default="ALL")

    criteria = relationship(
        "Criterion",
        back_populates="checklist",
        cascade="all, delete-orphan"
    )


class Criterion(Base):
    __tablename__ = "criteria"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=False)
    weight = Column(Float, nullable=False)

    answer_type = Column(String, nullable=False)
    na_allowed = Column(Boolean, default=False)
    scale = Column(JSON, nullable=True)

    checklist_id = Column(
        Integer,
        ForeignKey("checklists.id"),
        nullable=False
    )

    checklist = relationship(
        "Checklist",
        back_populates="criteria"
    )
