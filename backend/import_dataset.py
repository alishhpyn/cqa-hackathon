import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


ROOT = Path(__file__).resolve().parent.parent


def build_url(base_url: str, group_id: str) -> str:
    parts = urlsplit(base_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["group_id"] = group_id
    return urlunsplit((
        parts.scheme,
        parts.netloc,
        parts.path,
        urlencode(query),
        parts.fragment
    ))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", choices=["dev", "prod"], required=True)
    args = parser.parse_args()

    group_id = args.dataset.upper()
    expected = 65 if group_id == "DEV" else 10

    api_url = os.getenv("CQA_ORGANIZER_API_URL")
    if not api_url:
        print("ERROR: CQA_ORGANIZER_API_URL is not set")
        return 1

    url = build_url(api_url, group_id)

    print(f"Downloading {group_id} dataset...")

    try:
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json"},
            method="GET"
        )

        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()

        payload = json.loads(raw.decode("utf-8-sig"))

    except Exception as exc:
        print(f"ERROR downloading dataset: {type(exc).__name__}: {exc}")
        return 1

    if not isinstance(payload, dict) or payload.get("isSuccess") is not True:
        print("ERROR: Organizer API did not return isSuccess=true")
        if isinstance(payload, dict):
            print("API error:", payload.get("error", "Unknown error"))
        return 1

    data = payload.get("data")
    if not isinstance(data, dict):
        print("ERROR: Missing data object")
        return 1

    if data.get("dataset_group_id") != group_id:
        print("ERROR: Returned dataset_group_id does not match request")
        return 1

    records = data.get("records")
    if not isinstance(records, list) or len(records) != expected:
        actual = len(records) if isinstance(records, list) else "invalid"
        print(f"ERROR: Expected {expected} records, received {actual}")
        return 1

    ids = []
    for index, record in enumerate(records, 1):
        if not isinstance(record, dict):
            print(f"ERROR: Record #{index} is not an object")
            return 1

        conversation_id = record.get("conversation_id")
        transcript = record.get("transcript")

        if not conversation_id or not isinstance(transcript, list):
            print(f"ERROR: Invalid record #{index}")
            return 1

        if any(
            not isinstance(turn, dict)
            or not isinstance(turn.get("text"), str)
            for turn in transcript
        ):
            print(f"ERROR: Invalid transcript in {conversation_id}")
            return 1

        ids.append(str(conversation_id))

    if len(ids) != len(set(ids)):
        print("ERROR: Duplicate conversation_id values")
        return 1

    output = ROOT / "data" / f"{args.dataset}_data.json"
    output.parent.mkdir(parents=True, exist_ok=True)

    temp = output.with_suffix(".json.tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")

    temp.replace(output)

    print(f"SUCCESS: {group_id}")
    print(f"Records: {len(records)}")
    print(f"Unique IDs: {len(set(ids))}")
    print(f"Saved: {output}")
    print("Encoding: UTF-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
