# Batch evaluation and export

This patch adds `backend/run_batch.py`. It evaluates the official 8-criterion checklist and writes organizer schema 1.0 to `results/<dataset>/results.json`.

## Prepare local files (do not commit them)

- Put the DEV response JSON at `data/dev_data.json` (65 records).
- Put the PROD response JSON at `data/prod_data.json` (10 records).
- Create `backend/.env` with `GROQ_API_KEY=...` and `GROQ_MODEL=qwen/qwen3.8-27b`. Never commit this file.
- Set `CQA_TEAM_NAME` in PowerShell before running.

## Run from repository root (PowerShell)

```powershell
$env:CQA_TEAM_NAME = "YOUR_TEAM_NAME"
.\backend\venv\Scripts\python.exe backend\run_batch.py --dataset dev
```

Resume skips all already-saved conversation IDs. To retry only saved error records:

```powershell
.\backend\venv\Scripts\python.exe backend\run_batch.py --dataset dev --retry-errors
```

For PROD, first save the organizer response as `data/prod_data.json`, then run:

```powershell
.\backend\venv\Scripts\python.exe backend\run_batch.py --dataset prod
```

`--mock` is only for testing the pipeline; never use its output for submission. The script enforces 65 DEV and 10 PROD records and saves atomically after each completed record.
