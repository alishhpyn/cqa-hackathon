
from typing import Literal, Optional
from pydantic import BaseModel, Field


class CriterionCreate(BaseModel):
    name: str
    description: str
    weight: float = Field(ge=0, le=100)

    answer_type: Literal[
        "yes_no",
        "yes_no_na",
        "numeric"
    ]

    na_allowed: bool = False

    scale: Optional[list[float]] = None


class ChecklistCreate(BaseModel):
    name: str
    channel: Literal["chat", "voice", "both"]
    language: Literal["RU", "KZ", "EN", "ALL"] = "ALL"

    criteria: list[CriterionCreate]


class CriterionResponse(CriterionCreate):
    id: int


class ChecklistResponse(BaseModel):
    id: int
    name: str
    channel: str
    language: str
    criteria: list[CriterionResponse]
