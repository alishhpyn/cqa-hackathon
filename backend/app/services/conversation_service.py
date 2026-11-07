
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "data"
ACTIVE_FILE = DATA_DIR / "active_dataset.txt"


def fix_text_encoding(text: str) -> str:
    try:
        return text.encode("latin1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def get_active_dataset() -> str:
    if ACTIVE_FILE.exists():
        value = ACTIVE_FILE.read_text(encoding="utf-8").strip().lower()
        if value in ("dev", "prod"):
            return value

    return "dev"


def set_active_dataset(group_id: str):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    temp = ACTIVE_FILE.with_suffix(".tmp")
    temp.write_text(group_id.lower(), encoding="utf-8")
    temp.replace(ACTIVE_FILE)


def get_dataset_file(group_id: str) -> Path:
    if group_id.lower() not in ("dev", "prod"):
        raise ValueError("Invalid dataset group_id")

    return DATA_DIR / f"{group_id.lower()}_data.json"


def build_api_url(base_url: str, group_id: str) -> str:
    parts = urlsplit(base_url)

    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key != "group_id"
    ]
    query.append(("group_id", group_id.upper()))

    return urlunsplit((
        parts.scheme,
        parts.netloc,
        parts.path,
        urlencode(query),
        parts.fragment
    ))


def import_dataset(group_id: str):
    group_id = group_id.strip().upper()

    if group_id not in ("DEV", "PROD"):
        raise ValueError("group_id must be DEV or PROD")

    api_url = os.getenv("CQA_ORGANIZER_API_URL")

    if not api_url:
        raise RuntimeError("Organizer API URL is not configured")

    url = build_api_url(api_url, group_id)

    try:
        request = Request(
            url,
            headers={"Accept": "application/json"},
            method="GET"
        )

        with urlopen(request, timeout=60) as response:
            raw = response.read()

        payload = json.loads(raw.decode("utf-8-sig"))

    except Exception as exc:
        raise RuntimeError(
            f"Could not download {group_id} dataset: {exc}"
        ) from exc

    if not isinstance(payload, dict) or payload.get("isSuccess") is not True:
        error = payload.get("error", "Unknown API error") if isinstance(payload, dict) else "Invalid API response"
        raise RuntimeError(f"Organizer API error: {error}")

    data = payload.get("data")

    if not isinstance(data, dict):
        raise RuntimeError("Organizer response has no data object")

    if str(data.get("dataset_group_id", "")).upper() != group_id:
        raise RuntimeError("Returned dataset_group_id does not match request")

    records = data.get("records")

    if not isinstance(records, list):
        raise RuntimeError("Organizer response has no records array")

    expected = 65 if group_id == "DEV" else 10

    if len(records) != expected:
        raise RuntimeError(
            f"Expected {expected} records, received {len(records)}"
        )

    ids = []

    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise RuntimeError(f"Record {index} is invalid")

        conversation_id = record.get("conversation_id")
        transcript = record.get("transcript")

        if not conversation_id or not isinstance(transcript, list):
            raise RuntimeError(f"Record {index} has invalid conversation data")

        for turn in transcript:
            if not isinstance(turn, dict) or not isinstance(turn.get("text"), str):
                raise RuntimeError(
                    f"Invalid transcript turn in {conversation_id}"
                )

        ids.append(str(conversation_id))

    if len(ids) != len(set(ids)):
        raise RuntimeError("Duplicate conversation_id values in dataset")

    output = get_dataset_file(group_id)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    temp = output.with_suffix(".json.tmp")

    with temp.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")

    temp.replace(output)

    # Switch active dataset only after successful download and save.
    set_active_dataset(group_id)

    return {
        "group_id": group_id,
        "total": len(records),
        "conversations": get_all_conversations(group_id)
    }


def get_all_conversations(group_id: str = None):
    group_id = (group_id or get_active_dataset()).lower()
    data_file = get_dataset_file(group_id)

    if not data_file.exists():
        raise FileNotFoundError(
            f"Dataset {group_id.upper()} has not been imported"
        )

    with data_file.open("r", encoding="utf-8-sig") as file:
        response = json.load(file)

    if not response.get("isSuccess"):
        raise ValueError(f"{group_id.upper()} dataset is invalid")

    conversations = response["data"]["records"]

    for conversation in conversations:
        transcript = conversation.get("transcript", [])

        for turn_id, message in enumerate(transcript, start=1):
            message["turn_id"] = turn_id

            if isinstance(message.get("text"), str):
                message["text"] = fix_text_encoding(message["text"])

    return conversations


def get_conversation_by_id(conversation_id: str):
    conversations = get_all_conversations()

    for conversation in conversations:
        if conversation["conversation_id"] == conversation_id:
            return conversation

    return None
