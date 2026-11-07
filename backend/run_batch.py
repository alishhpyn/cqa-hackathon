"""Batch CQA evaluation and export in organizer JSON schema 1.0.

Run from repository root:
  python backend/run_batch.py --dataset dev
  python backend/run_batch.py --dataset prod --input data/prod_data.json
  python backend/run_batch.py --dataset prod --input data/prod_data.json --retry-errors
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.services.ai.evaluator_core import evaluate_dialog
from app.services.ai.groq_client import DEFAULT_MODEL

CRITERION_MAP = {
    "01": "contact",
    "02": "discovery",
    "03": "identification",
    "04": "consultation",
    "05": "empathy",
    "06": "dialogue",
    "07": "closure",
    "08": "critical",
}


def load_records(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as f:
        payload = json.load(f)
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        data = payload.get("data", payload)
        records = data.get("records") if isinstance(data, dict) else None
    else:
        records = None
    if not isinstance(records, list):
        raise ValueError("Input JSON must contain data.records or be a list")
    for i, item in enumerate(records):
        if not isinstance(item, dict) or not (item.get("conversation_id") or item.get("id")):
            raise ValueError(f"Record #{i + 1} has no conversation_id")
        if not isinstance(item.get("transcript"), list):
            raise ValueError(f"Record {item.get('conversation_id')} has no transcript list")
        # Preserve transcript order and provide deterministic 1-based evidence indexes.
        for turn_no, turn in enumerate(item["transcript"], 1):
            if isinstance(turn, dict):
                turn["turn_id"] = turn_no
    ids = [str(x.get("conversation_id") or x.get("id")) for x in records]
    if len(ids) != len(set(ids)):
        raise ValueError("Input contains duplicate conversation_id values")
    return records


def to_json_value(criterion_id: str, raw: Any) -> Any:
    if raw is None or (isinstance(raw, str) and raw.strip().upper() in {"N/A", "NA", "НЕПРИМЕНИМО"}):
        return None
    if criterion_id in {"01", "02", "03", "05", "07", "08"}:
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().lower()
        if text in {"да", "yes", "иә", "иа", "true"}:
            return True
        if text in {"нет", "no", "жоқ", "жок", "false"}:
            return False
        raise ValueError(f"Unexpected binary value for criterion {criterion_id}: {raw!r}")
    value = int(float(raw))
    allowed = {"04": {0, 5, 10, 15, 20}, "06": {0, 4, 7, 10}}[criterion_id]
    if value not in allowed:
        raise ValueError(f"Unexpected scale value for criterion {criterion_id}: {raw!r}")
    return value


def build_success_record(dialog: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    result_criteria = result.get("criteria") or {}
    criteria = []
    for source_id, target_id in CRITERION_MAP.items():
        item = result_criteria.get(source_id)
        if not isinstance(item, dict):
            raise ValueError(f"Evaluation result is missing criterion {source_id}")
        criteria.append({
            "criterion_id": target_id,
            "value": to_json_value(source_id, item.get("raw_value")),
            "rationale": str(item.get("explanation") or ""),
            "evidence_turns": item.get("evidence_replicas") or [],
        })
    score = result.get("total_score")
    return {
        "conversation_id": str(dialog.get("conversation_id") or dialog.get("id")),
        "status": "ok",
        "criteria": criteria,
        "score": {
            "final_score": round(float(score), 2) if score is not None else None,
            "critical_flag": bool(result.get("gross_error", False)),
        },
    }


def atomic_save(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run batch CQA evaluation and export schema 1.0")
    parser.add_argument("--dataset", choices=["dev", "prod"], required=True)
    parser.add_argument("--input", type=Path, help="Dataset JSON (default: data/<dataset>_data.json)")
    parser.add_argument("--retry-errors", action="store_true", help="Retry records currently saved with status=error")
    parser.add_argument("--mock", action="store_true", help="Use evaluator mock mode; for pipeline tests only")
    args = parser.parse_args()

    input_path = args.input or (PROJECT_ROOT / "data" / f"{args.dataset}_data.json")
    if not input_path.is_absolute():
        input_path = PROJECT_ROOT / input_path
    output_path = PROJECT_ROOT / "results" / args.dataset / "results.json"
    if not input_path.exists():
        print(f"ERROR: dataset file not found: {input_path}", file=sys.stderr)
        return 2

    records = load_records(input_path)
    expected = 65 if args.dataset == "dev" else 10
    if len(records) != expected:
        print(f"ERROR: {args.dataset.upper()} must contain exactly {expected} records; found {len(records)}", file=sys.stderr)
        return 2

    team_name = os.getenv("CQA_TEAM_NAME", "")
    if not team_name:
        print("ERROR: set CQA_TEAM_NAME in environment before running export", file=sys.stderr)
        return 2
    model_name = os.getenv("GROQ_MODEL", DEFAULT_MODEL)
    if output_path.exists():
        with output_path.open("r", encoding="utf-8") as f:
            existing = json.load(f)
        if existing.get("schema_version") != "1.0" or not isinstance(existing.get("results"), list):
            raise ValueError(f"Existing export has unsupported schema: {output_path}")
        by_id = {str(x.get("conversation_id")): x for x in existing["results"]}
    else:
        by_id = {}

    if args.retry_errors:
        selected = [r for r in records if (by_id.get(str(r.get("conversation_id") or r.get("id")), {}).get("status") == "error")]
    else:
        selected = [r for r in records if str(r.get("conversation_id") or r.get("id")) not in by_id]

    print(f"Dataset: {args.dataset.upper()} | records: {len(records)} | to evaluate: {len(selected)}")
    for index, dialog in enumerate(selected, 1):
        conversation_id = str(dialog.get("conversation_id") or dialog.get("id"))
        print(f"[{index}/{len(selected)}] Evaluating {conversation_id} ...", flush=True)
        try:
            evaluated = evaluate_dialog(dialog=dialog, checklist=None, mock=args.mock)
            if evaluated.get("is_success"):
                exported = build_success_record(dialog, evaluated)
            else:
                exported = {
                    "conversation_id": conversation_id,
                    "status": "error",
                    "criteria": [],
                    "score": None,
                    "error": str(evaluated.get("error") or "Evaluation failed"),
                }
        except Exception as exc:
            exported = {
                "conversation_id": conversation_id,
                "status": "error",
                "criteria": [],
                "score": None,
                "error": f"{type(exc).__name__}: {exc}",
            }
        by_id[conversation_id] = exported
        payload = {
            "schema_version": "1.0",
            "team_name": team_name,
            "model": {"mode": "external_api", "name": model_name},
            "results": [by_id[str(r.get("conversation_id") or r.get("id"))] for r in records if str(r.get("conversation_id") or r.get("id")) in by_id],
        }
        atomic_save(output_path, payload)
        print(f"  saved: {exported['status']}", flush=True)

    # Always write the canonical source order, including previously saved outcomes.
    final_payload = {
        "schema_version": "1.0",
        "team_name": team_name,
        "model": {"mode": "external_api", "name": model_name},
        "results": [by_id[str(r.get("conversation_id") or r.get("id"))] for r in records if str(r.get("conversation_id") or r.get("id")) in by_id],
    }
    atomic_save(output_path, final_payload)
    statuses = {"ok": sum(x.get("status") == "ok" for x in final_payload["results"]),
                "error": sum(x.get("status") == "error" for x in final_payload["results"])}
    print(f"DONE: {output_path}")
    print(f"Saved {len(final_payload['results'])}/{len(records)} | OK={statuses['ok']} | ERROR={statuses['error']}")
    return 0 if len(final_payload["results"]) == len(records) else 1

if __name__ == "__main__":
    raise SystemExit(main())
