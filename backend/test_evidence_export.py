import unittest

from run_batch import CRITERION_MAP, build_success_record
from app.services.ai.checklist_rules import OFFICIAL_CHECKLIST, validate_evaluation


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.dialog = {"conversation_id": "test", "transcript": [{"speaker": "client", "text": "Hi"}, {"speaker": "operator", "text": "Hello"}]}
        values = ["Да", "N/A", "N/A", 20, "Да", 10, "Да", "Нет"]
        self.evaluation = {f"{i:02d}": {"value": value, "explanation": "reason", "evidence_replicas": [1]}
                           for i, value in enumerate(values, 1)}
        self.result = {"criteria": {cid: {"raw_value": self.evaluation[cid]["value"], "explanation": "reason", "evidence_replicas": [1]}
                                    for cid in CRITERION_MAP}, "total_score": 100, "gross_error": False}

    def test_rejects_invalid_evidence_in_model_and_export(self):
        for evidence in ([], [0], [3], [True], ["1"]):
            with self.subTest(evidence=evidence):
                self.evaluation["08"]["evidence_replicas"] = evidence
                self.result["criteria"]["08"]["evidence_replicas"] = evidence
                self.assertFalse(validate_evaluation(self.evaluation, self.dialog["transcript"], OFFICIAL_CHECKLIST)[0])
                with self.assertRaises(ValueError):
                    build_success_record(self.dialog, self.result)

    def test_valid_evidence_preserved(self):
        self.assertTrue(validate_evaluation(self.evaluation, self.dialog["transcript"], OFFICIAL_CHECKLIST)[0])
        record = build_success_record(self.dialog, self.result)
        self.assertEqual(record["status"], "ok")
        self.assertEqual(record["criteria"][-1]["evidence_turns"], [1])


if __name__ == "__main__":
    unittest.main()
