
import json
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parents[3] / "data" / "dev_data.json"


def get_all_conversations():
    with open(DATA_FILE, "r", encoding="utf-8-sig") as file:
        response = json.load(file)

    if not response.get("isSuccess"):
        raise ValueError("DEV API returned an unsuccessful response")

    return response["data"]["records"]


def get_conversation_by_id(conversation_id: str):
    conversations = get_all_conversations()

    for conversation in conversations:
        if conversation["conversation_id"] == conversation_id:
            return conversation

    return None
