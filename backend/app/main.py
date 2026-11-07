
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from app.schemas.evaluation import EvaluationRequest
from app.services.scoring_service import calculate_score

from app.services.conversation_service import (
    get_all_conversations,
    get_conversation_by_id
)

from app.database.database import Base, engine, get_db
from app.models.checklist import Checklist, Criterion
from app.models.evaluation import Evaluation, CriterionResult
from app.schemas.checklist import ChecklistCreate


# Create database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="CQA Backend",
    description="Conversation Quality Analytics API",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------------
# Health
# -------------------------

@app.get("/api/health")
def health_check():
    return {"status": "OK"}


# -------------------------
# Conversations
# -------------------------

@app.get("/api/conversations")
def list_conversations():
    conversations = get_all_conversations()

    return {
        "total": len(conversations),
        "conversations": conversations
    }


@app.get("/api/conversations/{conversation_id}")
def conversation_details(conversation_id: str):
    conversation = get_conversation_by_id(conversation_id)

    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found"
        )

    return conversation


# -------------------------
# Checklist helper
# -------------------------

def checklist_to_dict(checklist):
    return {
        "id": checklist.id,
        "name": checklist.name,
        "channel": checklist.channel,
        "language": checklist.language,
        "criteria": [
            {
                "id": criterion.id,
                "name": criterion.name,
                "description": criterion.description,
                "weight": criterion.weight,
                "answer_type": criterion.answer_type,
                "na_allowed": criterion.na_allowed,
                "scale": criterion.scale
            }
            for criterion in checklist.criteria
        ]
    }


# -------------------------
# Checklists
# -------------------------

@app.get("/api/checklists")
def list_checklists(db: Session = Depends(get_db)):
    checklists = db.query(Checklist).all()

    return [
        checklist_to_dict(checklist)
        for checklist in checklists
    ]


@app.post("/api/checklists")
def create_checklist(
    checklist_data: ChecklistCreate,
    db: Session = Depends(get_db)
):
    new_checklist = Checklist(
        name=checklist_data.name,
        channel=checklist_data.channel,
        language=checklist_data.language
    )

    for item in checklist_data.criteria:
        criterion = Criterion(
            name=item.name,
            description=item.description,
            weight=item.weight,
            answer_type=item.answer_type,
            na_allowed=item.na_allowed,
            scale=item.scale
        )

        new_checklist.criteria.append(criterion)

    db.add(new_checklist)
    db.commit()
    db.refresh(new_checklist)

    return checklist_to_dict(new_checklist)


@app.put("/api/checklists/{checklist_id}")
def update_checklist(
    checklist_id: int,
    checklist_data: ChecklistCreate,
    db: Session = Depends(get_db)
):
    checklist = db.query(Checklist).filter(
        Checklist.id == checklist_id
    ).first()

    if checklist is None:
        raise HTTPException(
            status_code=404,
            detail="Checklist not found"
        )

    checklist.name = checklist_data.name
    checklist.channel = checklist_data.channel
    checklist.language = checklist_data.language

    # Replace old criteria with updated criteria
    checklist.criteria.clear()

    for item in checklist_data.criteria:
        criterion = Criterion(
            name=item.name,
            description=item.description,
            weight=item.weight,
            answer_type=item.answer_type,
            na_allowed=item.na_allowed,
            scale=item.scale
        )

        checklist.criteria.append(criterion)

    db.commit()
    db.refresh(checklist)

    return checklist_to_dict(checklist)




@app.post("/api/evaluate/{conversation_id}")
def evaluate_conversation(
    conversation_id: str,
    request: EvaluationRequest,
    db: Session = Depends(get_db)
):
    conversation = get_conversation_by_id(conversation_id)

    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found"
        )

    checklist = db.query(Checklist).filter(
        Checklist.id == request.checklist_id
    ).first()

    if checklist is None:
        raise HTTPException(
            status_code=404,
            detail="Checklist not found"
        )

    criteria = [
        {
            "id": item.id,
            "name": item.name,
            "weight": item.weight,
            "answer_type": item.answer_type,
            "na_allowed": item.na_allowed,
            "scale": item.scale
        }
        for item in checklist.criteria
    ]

    try:
        result = calculate_score(criteria, request.answers)

        # Save general evaluation
        evaluation = Evaluation(
            conversation_id=conversation_id,
            checklist_id=checklist.id,
            score=result["score"],
            gross_violation=result["gross_violation"]
        )

        db.add(evaluation)
        db.flush()

        # Save individual criterion results
        for item in result["details"]:
            criterion_result = CriterionResult(
                evaluation_id=evaluation.id,
                criterion_id=item["criterion_id"],
                criterion_name=item["criterion"],
                answer=str(item["answer"]),
                weight=item["weight"],
                points=item["points"]
            )

            db.add(criterion_result)

        db.commit()
        db.refresh(evaluation)

    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(error))

    except Exception:
        db.rollback()
        raise

    return {
        "evaluation_id": evaluation.id,
        "conversation_id": conversation_id,
        "checklist_id": checklist.id,
        **result
    }


@app.get("/api/results/{conversation_id}")
def get_evaluation_results(
    conversation_id: str,
    db: Session = Depends(get_db)
):
    evaluations = (
        db.query(Evaluation)
        .filter(Evaluation.conversation_id == conversation_id)
        .order_by(Evaluation.id.desc())
        .all()
    )

    if not evaluations:
        raise HTTPException(
            status_code=404,
            detail="No evaluation results found"
        )

    results = []

    for evaluation in evaluations:
        criterion_results = (
            db.query(CriterionResult)
            .filter(
                CriterionResult.evaluation_id == evaluation.id
            )
            .all()
        )

        results.append({
            "evaluation_id": evaluation.id,
            "conversation_id": evaluation.conversation_id,
            "checklist_id": evaluation.checklist_id,
            "score": evaluation.score,
            "gross_violation": evaluation.gross_violation,
            "created_at": evaluation.created_at,
            "details": [
                {
                    "criterion_id": item.criterion_id,
                    "criterion": item.criterion_name,
                    "answer": item.answer,
                    "weight": item.weight,
                    "points": item.points
                }
                for item in criterion_results
            ]
        })

    return {
        "total": len(results),
        "results": results
    }
