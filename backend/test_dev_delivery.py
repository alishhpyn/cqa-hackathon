"""Verify checked-in DEV output against the local organizer input, without API calls."""
import json
import unittest
from pathlib import Path

from app.services.ai.checklist_rules import calculate_score

ROOT = Path(__file__).resolve().parent.parent
INPUT = ROOT / 'data' / 'dev_data.json'
OUTPUT = ROOT / 'results' / 'dev' / 'results.json'
MAP = {'contact': '01', 'discovery': '02', 'identification': '03', 'consultation': '04',
       'empathy': '05', 'dialogue': '06', 'closure': '07', 'critical': '08'}


@unittest.skipUnless(INPUT.exists() and OUTPUT.exists(), 'Local DEV data and result file required')
class DeliveryTests(unittest.TestCase):
    def test_ids_evidence_and_scores(self):
        dataset = json.loads(INPUT.read_text(encoding='utf-8-sig'))['data']['records']
        result = json.loads(OUTPUT.read_text(encoding='utf-8-sig'))
        records = result['results']
        self.assertEqual(result['schema_version'], '1.0')
        self.assertEqual(len(dataset), 65)
        self.assertEqual(len(records), 65)
        by_id = {x['conversation_id']: x for x in dataset}
        self.assertEqual(len(by_id), 65)
        self.assertEqual({x['conversation_id'] for x in records}, set(by_id))
        for row in records:
            if row['status'] == 'error':
                self.assertEqual(row['criteria'], [])
                self.assertIsNone(row['score'])
                self.assertTrue(row.get('error'))
                continue
            self.assertEqual(row['status'], 'ok')
            self.assertEqual(len(row['criteria']), 8)
            self.assertEqual({x['criterion_id'] for x in row['criteria']}, set(MAP))
            evaluations = {}
            for c in row['criteria']:
                self.assertTrue(c.get('rationale'))
                self.assertTrue(c.get('evidence_turns'))
                self.assertTrue(all(type(i) is int and 1 <= i <= len(by_id[row['conversation_id']]['transcript'])
                                    for i in c['evidence_turns']))
                v = c['value']
                evaluations[MAP[c['criterion_id']]] = {'value': 'N/A' if v is None else 'Да' if v is True else 'Нет' if v is False else v}
            score = calculate_score(evaluations)
            self.assertEqual(row['score']['final_score'], score['total_score'])
            self.assertEqual(row['score']['critical_flag'], score['gross_error'])


if __name__ == '__main__': unittest.main()
