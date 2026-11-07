
from pydantic import BaseModel, Field


class AppealCreate(BaseModel):
    evaluation_id: int
    criterion_result_id: int
    comment: str = Field(min_length=1)


class AppealReview(BaseModel):
    reviewer_answer: str | int | float
    reviewer_reason: str = Field(min_length=1)
