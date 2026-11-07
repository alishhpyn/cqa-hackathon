"""Advisory evidence checks; never alter scores or request another evaluation."""
from .checklist_rules import normalize_value


def check_criterion06(evaluation, transcript):
    criterion = evaluation.get('06') if isinstance(evaluation, dict) else None
    if not isinstance(criterion, dict) or normalize_value(criterion.get('value')) != 4:
        return []
    evidence = criterion.get('evidence_replicas')
    if not isinstance(transcript, list) or not isinstance(evidence, list):
        return ['06=4: невозможно проверить роли без транскрипта и списка реплик.']
    if any(type(n) is not int or not 1 <= n <= len(transcript) for n in evidence):
        return ['06=4: список реплик содержит некорректные номера.']
    operators = [n for n in evidence if isinstance(transcript[n-1], dict) and str(transcript[n-1].get('speaker', '')).lower() == 'operator']
    clients = [n for n in evidence if isinstance(transcript[n-1], dict) and str(transcript[n-1].get('speaker', '')).lower() == 'client']
    if not any(operator < client for operator in operators for client in clients):
        return ['06=4: в доказательствах нет ответа оператора и последующей реплики клиента; проверьте обоснование вручную.']
    return []
