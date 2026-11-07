"""
Единая точка входа для оценки диалогов (модуль для интеграции с FastAPI бэкендом).
Предоставляет функцию evaluate_dialog(dialog, checklist, model, mock)
"""

import time
from typing import Dict, Any, Optional

from .checklist_rules import (
    calculate_score,
    validate_evaluation,
    OFFICIAL_CHECKLIST
)

from .prompt_builder import (
    build_system_prompt,
    format_transcript_for_llm
)

from .groq_client import (
    evaluate_dialog_via_groq,
    GroqClientError
)

PROMPT_VERSION = "v2.0-dynamic"
CHECKLIST_VERSION_DEFAULT = "v1.0-official-8criteria"


def evaluate_dialog(
    dialog: Dict[str, Any],
    checklist: Optional[Dict[str, Any]] = None,
    model: Optional[str] = None,
    mock: bool = False,
    checklist_version: Optional[str] = None
) -> Dict[str, Any]:
    """
    Основная функция оценки диалога.

    Параметры:
      - dialog: словарь диалога (conversation_id/id, language, channel, transcript)
      - checklist: словарь критериев (по умолчанию официальный чек-лист)
      - model: идентификатор модели Groq (по умолчанию qwen/qwen3.8-27b)
      - mock: режим имитации без реального вызова API
      - checklist_version: пользовательский строковый идентификатор версии чек-листа

    Возвращает стандартизированный словарь результатов для FastAPI / БД.
    """
    t_start = time.time()
    cl = checklist or OFFICIAL_CHECKLIST
    cl_ver = checklist_version or CHECKLIST_VERSION_DEFAULT
    conv_id = dialog.get("conversation_id") or dialog.get("id", "unknown_dialog")
    model_name = model or "qwen/qwen3.8-27b"
    transcript = dialog.get("transcript", [])

    # Базовая валидация структуры входного диалога
    if not isinstance(transcript, list) or len(transcript) == 0:
        return {
            "dialog_id": conv_id,
            "checklist_version": cl_ver,
            "model": model_name,
            "prompt_version": PROMPT_VERSION,
            "is_success": False,
            "error": "Пустой или отсутствующий транскрипт диалога",
            "total_score": None,
            "gross_error": False,
            "applicable_weight_sum": 0.0,
            "earned_points_sum": 0.0,
            "criteria": None,
            "metrics": {
                "pure_model_time_sec": 0.0,
                "total_duration_sec": 0.0,
                "attempts": 0,
                "rate_limit_429_count": 0,
                "token_usage": None
            }
        }

    user_prompt = format_transcript_for_llm(dialog)
    system_prompt = build_system_prompt(cl)

    if mock:
        llm_output = {}
        for cid, rule in cl.items():
            llm_output[cid] = {
                "value": "Да" if rule.get("type") in ["binary", "binary_na"] else (10 if cid == "06" else (20 if cid == "04" else "Нет")),
                "explanation": f"Тестовая оценка критерия {cid}",
                "evidence_replicas": [1]
            }
        pure_time = 0.01
        meta = {
            "model": "mock",
            "pure_model_time": pure_time,
            "total_duration": pure_time,
            "total_attempts": 1,
            "rate_limit_429_count": 0,
            "token_usage": None
        }
    else:
        try:
            llm_output, pure_time, meta = evaluate_dialog_via_groq(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model_name
            )
        except GroqClientError as gce:
            return {
                "dialog_id": conv_id,
                "checklist_version": cl_ver,
                "model": model_name,
                "prompt_version": PROMPT_VERSION,
                "is_success": False,
                "error": f"Ошибка Groq API ({gce.error_type}): {gce}",
                "total_score": None,
                "gross_error": False,
                "applicable_weight_sum": 0.0,
                "earned_points_sum": 0.0,
                "criteria": None,
                "metrics": {
                    "pure_model_time_sec": 0.0,
                    "total_duration_sec": round(time.time() - t_start, 2),
                    "attempts": 0,
                    "rate_limit_429_count": 0,
                    "token_usage": None
                }
            }
        except Exception as e:
            return {
                "dialog_id": conv_id,
                "checklist_version": cl_ver,
                "model": model_name,
                "prompt_version": PROMPT_VERSION,
                "is_success": False,
                "error": f"Непредвиденная системная ошибка: {e}",
                "total_score": None,
                "gross_error": False,
                "applicable_weight_sum": 0.0,
                "earned_points_sum": 0.0,
                "criteria": None,
                "metrics": {
                    "pure_model_time_sec": 0.0,
                    "total_duration_sec": round(time.time() - t_start, 2),
                    "attempts": 0,
                    "rate_limit_429_count": 0,
                    "token_usage": None
                }
            }

    # Валидация ответа в Python
    is_valid, v_errors = validate_evaluation(llm_output, transcript, checklist=cl)
    if not is_valid:
        return {
            "dialog_id": conv_id,
            "checklist_version": cl_ver,
            "model": model_name,
            "prompt_version": PROMPT_VERSION,
            "is_success": False,
            "error": f"Ошибка валидации ответа модели: {'; '.join(v_errors)}",
            "total_score": None,
            "gross_error": False,
            "applicable_weight_sum": 0.0,
            "earned_points_sum": 0.0,
            "criteria": None,
            "raw_output": llm_output,
            "metrics": {
                "pure_model_time_sec": meta.get("pure_model_time", 0.0),
                "total_duration_sec": meta.get("total_duration", 0.0),
                "attempts": meta.get("total_attempts", 1),
                "rate_limit_429_count": meta.get("rate_limit_429_count", 0),
                "token_usage": meta.get("token_usage")
            }
        }

    # Расчёт официального балла
    score_res = calculate_score(llm_output, checklist=cl)

    return {
        "dialog_id": conv_id,
        "checklist_version": cl_ver,
        "model": meta.get("model", model_name),
        "prompt_version": PROMPT_VERSION,
        "is_success": True,
        "error": None,
        "total_score": score_res["total_score"],
        "gross_error": score_res["gross_error"],
        "applicable_weight_sum": score_res["applicable_weight_sum"],
        "earned_points_sum": score_res["earned_points_sum"],
        "criteria": score_res["criteria"],
        "metrics": {
            "pure_model_time_sec": meta.get("pure_model_time", 0.0),
            "total_duration_sec": meta.get("total_duration", 0.0),
            "attempts": meta.get("total_attempts", 1),
            "rate_limit_429_count": meta.get("rate_limit_429_count", 0),
            "token_usage": meta.get("token_usage")
        }
    }
