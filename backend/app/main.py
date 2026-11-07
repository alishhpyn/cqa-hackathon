import json
from fastapi import BackgroundTasks
from app.schemas.evaluation import AIEvaluationRequest
from app.services.evaluation_service import process_ai_evaluation
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from app.schemas.evaluation import EvaluationRequest
from app.services.scoring_service import calculate_score
from sqlalchemy.exc import IntegrityError

from app.services.conversation_service import (
    get_all_conversations,
    get_conversation_by_id
)

from app.database.database import Base, engine, get_db
from app.models.checklist import Checklist, Criterion
from app.models.evaluation import Evaluation, CriterionResult
from app.models.appeal import Appeal
from app.schemas.appeal import AppealCreate, AppealReview
from app.schemas.checklist import ChecklistCreate
from datetime import datetime, timezone


# Create database tables
Base.metadata.create_all(bind=engine)

# Ensure indexes are created for existing database tables
for index in Evaluation.__table__.indexes:
    if index.name == "uq_active_evaluation":
        index.create(bind=engine, checkfirst=True)

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

# -------------------------
# AI Evaluations
# -------------------------



@app.post("/api/evaluations", status_code=202)
def create_ai_evaluation(
    request: AIEvaluationRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    conversation = get_conversation_by_id(request.conversation_id)

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

    # Check for an existing active evaluation
    existing_evaluation = db.query(Evaluation).filter(
        Evaluation.conversation_id == request.conversation_id,
        Evaluation.checklist_id == request.checklist_id,
        Evaluation.checklist_version == request.checklist_version,
        Evaluation.status.in_(["queued", "running"])
    ).order_by(Evaluation.id.desc()).first()

    if existing_evaluation:
        return {
            "evaluation_id": existing_evaluation.id,
            "conversation_id": existing_evaluation.conversation_id,
            "checklist_id": existing_evaluation.checklist_id,
            "checklist_version": existing_evaluation.checklist_version,
            "status": existing_evaluation.status
        }

    evaluation = Evaluation(
        conversation_id=request.conversation_id,
        checklist_id=checklist.id,
        checklist_version=request.checklist_version,
        status="queued",
        score=None,
        gross_violation=False
    )

    try:
        db.add(evaluation)
        db.commit()
        db.refresh(evaluation)

    except IntegrityError:
        db.rollback()

        # Another request created the active evaluation first
        existing_evaluation = db.query(Evaluation).filter(
            Evaluation.conversation_id == request.conversation_id,
            Evaluation.checklist_id == request.checklist_id,
            Evaluation.checklist_version == request.checklist_version,
            Evaluation.status.in_(["queued", "running"])
        ).order_by(Evaluation.id.desc()).first()

        if existing_evaluation:
            return {
                "evaluation_id": existing_evaluation.id,
                "conversation_id": existing_evaluation.conversation_id,
                "checklist_id": existing_evaluation.checklist_id,
                "checklist_version": existing_evaluation.checklist_version,
                "status": existing_evaluation.status
            }

        raise HTTPException(
            status_code=409,
            detail="Could not create evaluation. Please try again."
        )

    background_tasks.add_task(
        process_ai_evaluation,
        evaluation.id
    )

    return {
        "evaluation_id": evaluation.id,
        "conversation_id": evaluation.conversation_id,
        "checklist_id": evaluation.checklist_id,
        "checklist_version": evaluation.checklist_version,
        "status": evaluation.status
    }



@app.get("/api/evaluations/{evaluation_id}")
def get_ai_evaluation(
    evaluation_id: int,
    db: Session = Depends(get_db)
):
    evaluation = db.query(Evaluation).filter(
        Evaluation.id == evaluation_id
    ).first()

    if evaluation is None:
        raise HTTPException(
            status_code=404,
            detail="Evaluation not found"
        )

    result = None

    if evaluation.result_json:
        result = json.loads(evaluation.result_json)

    return {
        "evaluation_id": evaluation.id,
        "conversation_id": evaluation.conversation_id,
        "checklist_id": evaluation.checklist_id,
        "checklist_version": evaluation.checklist_version,
        "status": evaluation.status,
        "score": evaluation.score,
        "gross_violation": evaluation.gross_violation,
        "result": result,
        "error": evaluation.error
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
                    "criterion_result_id": item.id,
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



@app.post("/api/appeals")
def create_appeal(
    request: AppealCreate,
    db: Session = Depends(get_db)
):
    evaluation = db.query(Evaluation).filter(
        Evaluation.id == request.evaluation_id
    ).first()

    if evaluation is None:
        raise HTTPException(
            status_code=404,
            detail="Evaluation not found"
        )

    criterion_result = db.query(CriterionResult).filter(
        CriterionResult.id == request.criterion_result_id,
        CriterionResult.evaluation_id == evaluation.id
    ).first()

    if criterion_result is None:
        raise HTTPException(
            status_code=404,
            detail="Criterion result not found"
        )

    if not request.comment.strip():
        raise HTTPException(
            status_code=400,
            detail="Comment cannot be empty"
        )

    appeal = Appeal(
        evaluation_id=evaluation.id,
        criterion_result_id=criterion_result.id,
        comment=request.comment.strip(),
        status="pending"
    )

    db.add(appeal)
    db.commit()
    db.refresh(appeal)

    return {
        "id": appeal.id,
        "evaluation_id": appeal.evaluation_id,
        "criterion_result_id": appeal.criterion_result_id,
        "comment": appeal.comment,
        "status": appeal.status
    }



@app.get("/api/appeals")
def get_appeals(db: Session = Depends(get_db)):
    appeals = db.query(Appeal).order_by(
        Appeal.id.desc()
    ).all()

    results = []

    for appeal in appeals:
        criterion_result = db.query(CriterionResult).filter(
            CriterionResult.id == appeal.criterion_result_id
        ).first()

        results.append({
            "id": appeal.id,
            "evaluation_id": appeal.evaluation_id,
            "criterion_result_id": appeal.criterion_result_id,
            "criterion": (
                criterion_result.criterion_name
                if criterion_result else None
            ),
            "original_answer": (
                criterion_result.answer
                if criterion_result else None
            ),
            "comment": appeal.comment,
            "status": appeal.status,
            "reviewer_answer": appeal.reviewer_answer,
            "reviewer_reason": appeal.reviewer_reason,
            "created_at": appeal.created_at
        })

    return {
        "total": len(results),
        "appeals": results
    }



@app.post("/api/appeals/{appeal_id}/review")
def review_appeal(
    appeal_id: int,
    request: AppealReview,
    db: Session = Depends(get_db)
):
    appeal = db.query(Appeal).filter(
        Appeal.id == appeal_id
    ).first()

    if appeal is None:
        raise HTTPException(
            status_code=404,
            detail="Appeal not found"
        )

    if appeal.status == "reviewed":
        raise HTTPException(
            status_code=400,
            detail="Appeal has already been reviewed"
        )

    evaluation = db.query(Evaluation).filter(
        Evaluation.id == appeal.evaluation_id
    ).first()

    criterion_result = db.query(CriterionResult).filter(
        CriterionResult.id == appeal.criterion_result_id
    ).first()

    if evaluation is None or criterion_result is None:
        raise HTTPException(
            status_code=404,
            detail="Evaluation or criterion result not found"
        )

    checklist = db.query(Checklist).filter(
        Checklist.id == evaluation.checklist_id
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


    saved_results = db.query(CriterionResult).filter(
        CriterionResult.evaluation_id == evaluation.id
    ).all()

    saved_by_criterion = {
        item.criterion_id: item
        for item in saved_results
    }

    answers = {}

    for criterion in criteria:
        criterion_id = criterion["id"]
        criterion_key = str(criterion_id)

        if criterion["name"] == "Gross Violations":
            answers[criterion_key] = (
                "YES" if evaluation.gross_violation else "NO"
            )
            continue

        saved_item = saved_by_criterion.get(criterion_id)

        if saved_item:
            answer = saved_item.answer

            if criterion["answer_type"] == "numeric":
                try:
                    answer = float(answer)
                    if answer.is_integer():
                        answer = int(answer)
                except ValueError:
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid saved numeric answer"
                    )

            answers[criterion_key] = answer

        elif criterion["na_allowed"]:
            answers[criterion_key] = "N/A"

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Missing answer for {criterion['name']}"
            )

    original_answer = criterion_result.answer

    answers[str(criterion_result.criterion_id)] = (
        request.reviewer_answer
    )


    try:
        result = calculate_score(criteria, answers)

        # Update every criterion result
        for detail in result["details"]:
            saved_item = next(
                (
                    item for item in saved_results
                    if item.criterion_id == detail["criterion_id"]
                ),
                None
            )

            if saved_item:
                saved_item.answer = str(detail["answer"])
                saved_item.points = detail["points"]

        # Update overall evaluation
        evaluation.score = result["score"]
        evaluation.gross_violation = result["gross_violation"]

        # Save reviewer decision
        appeal.reviewer_answer = str(request.reviewer_answer)
        appeal.reviewer_reason = request.reviewer_reason.strip()
        appeal.status = "reviewed"
        appeal.reviewed_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(evaluation)
        db.refresh(appeal)

    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(error))

    except Exception:
        db.rollback()
        raise

    return {
        "appeal_id": appeal.id,
        "status": appeal.status,
        "original_answer": original_answer,
        "reviewer_answer": appeal.reviewer_answer,
        "reviewer_reason": appeal.reviewer_reason,
        "new_score": evaluation.score,
        "gross_violation": evaluation.gross_violation
    }
