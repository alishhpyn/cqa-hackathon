"""Create the initial checklist via the existing HTTP API."""
import json
from urllib.request import Request, urlopen

from app.services.ai.checklist_rules import OFFICIAL_CHECKLIST

base = "http://127.0.0.1:8000/api/checklists"
with urlopen(base) as response:
    existing = json.load(response)
name = "Freedom Broker"
if any(row["name"] == name for row in existing):
    print("Checklist already exists.")
else:
    criteria = []
    for key, rule in OFFICIAL_CHECKLIST.items():
        kind = rule["type"]
        criteria.append({
            "name": "Gross Violations" if key == "08" else rule["name"],
            "description": rule["description"],
            "weight": rule["weight"],
            "answer_type": "numeric" if "scale" in kind else ("yes_no_na" if rule["allows_na"] else "yes_no"),
            "na_allowed": rule["allows_na"],
            "scale": rule.get("scale"),
        })
    body = json.dumps({"name":name, "channel":"both", "language":"ALL", "criteria":criteria})
    with urlopen(Request(base, body.encode("utf-8"), {"Content-Type":"application/json"})) as response:
        print("Created checklist", json.load(response)["id"])
