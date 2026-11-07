import json
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parents[3] / "data" / "dev_data.json"


def fix_text_encoding(text: str) -> str:
    try:
        return text.encode("latin1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def get_all_conversations():
    with open(DATA_FILE, "r", encoding="utf-8-sig") as file:
        response = json.load(file)

    if not response.get("isSuccess"):
        raise ValueError("DEV API returned an unsuccessful response")

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