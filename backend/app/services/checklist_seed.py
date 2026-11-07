"""Create the official starting checklist once for an empty database."""
from app.models.checklist import Checklist, Criterion
from app.services.ai.checklist_rules import OFFICIAL_CHECKLIST


def ensure_default_checklist(db):
    existing = db.query(Checklist).first()
    if existing is not None:
        return existing
    checklist = Checklist(name='Freedom Broker', channel='both', language='ALL')
    for cid, rule in OFFICIAL_CHECKLIST.items():
        kind = rule['type']
        checklist.criteria.append(Criterion(
            name='Gross Violations' if cid == '08' else rule['name'],
            description=rule['description'], weight=rule['weight'],
            answer_type='numeric' if 'scale' in kind else 'yes_no_na' if rule['allows_na'] else 'yes_no',
            na_allowed=rule['allows_na'], scale=rule.get('scale')))
    db.add(checklist)
    db.commit()
    db.refresh(checklist)
    return checklist
