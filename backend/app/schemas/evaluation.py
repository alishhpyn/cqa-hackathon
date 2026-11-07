
from pydantic import BaseModel
from typing import Union


class EvaluationRequest(BaseModel):
    checklist_id: int
    answers: dict[str, Union[str, int, float]]


class EvaluationResponse(BaseModel):
    conversation_id: str
    checklist_id: int
    score: float | None
    gross_violation: bool
    details: list[dict]
