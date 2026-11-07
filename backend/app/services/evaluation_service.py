
import json
import threading

from app.database.database import SessionLocal
from app.models.evaluation import Evaluation, CriterionResult
from app.models.checklist import Checklist

from app.services.conversation_service import get_conversation_by_id
from app.services.ai.evaluator_core import evaluate_dialog
from app.services.ai.checklist_adapter import convert_checklist_to_ai


# Prevent simultaneous Groq evaluations in this backend process.
AI_EVALUATION_LOCK = threading.Lock()


def process_ai_evaluation(evaluation_id: int):
    """
    Processes one AI evaluation and saves its result to SQLite.
    """

    with AI_EVALUATION_LOCK:
        db = SessionLocal()

        try:
            evaluation = db.query(Evaluation).filter(
                Evaluation.id == evaluation_id
            ).first()

            if evaluation is None:
                return

            evaluation.status = "running"
            evaluation.error = None
            db.commit()

            dialog = get_conversation_by_id(
                evaluation.conversation_id
            )

            if dialog is None:
                raise ValueError("Conversation not found")

            checklist = db.query(Checklist).filter(
                Checklist.id == evaluation.checklist_id
            ).first()

            if checklist is None:
                raise ValueError("Checklist not found")

            ai_checklist, id_map = convert_checklist_to_ai(
                checklist
            )

            result = evaluate_dialog(
                dialog=dialog,
                checklist=ai_checklist,
                checklist_version=evaluation.checklist_version
            )

            evaluation.result_json = json.dumps(
                result,
                ensure_ascii=False
            )

            if not result.get("is_success"):
                evaluation.status = "failed"
                evaluation.error = result.get(
                    "error",
                    "AI evaluation failed"
                )
                db.commit()
                return

            evaluation.score = result.get("total_score")
            evaluation.gross_violation = result.get(
                "gross_error",
                False
            )

            # Save criterion results using SQLite IDs.
            for ai_id, item in result["criteria"].items():
                sqlite_id = id_map.get(ai_id)

                if sqlite_id is None:
                    raise ValueError(
                        f"Unknown AI criterion ID: {ai_id}"
                    )

                criterion_result = CriterionResult(
                    evaluation_id=evaluation.id,
                    criterion_id=sqlite_id,
                    criterion_name=item["name"],
                    answer=str(item["raw_value"]),
                    weight=float(item["weight"]),
                    points=float(item["earned_points"])
                )

                db.add(criterion_result)

            evaluation.status = "completed"
            evaluation.error = None

            db.commit()

        except Exception as error:
            db.rollback()

            evaluation = db.query(Evaluation).filter(
                Evaluation.id == evaluation_id
            ).first()

            if evaluation:
                evaluation.status = "failed"
                evaluation.error = str(error)
                db.commit()

        finally:
            db.close()
