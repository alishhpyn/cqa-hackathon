import unittest
import copy
from unittest.mock import patch

from run_batch import CRITERION_MAP, build_success_record
from app.services.ai.checklist_rules import OFFICIAL_CHECKLIST, validate_evaluation, calculate_score
from app.services.ai.prompt_builder import build_system_prompt
from app.services.ai.evaluator_core import evaluate_dialog


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

    def test_prompt_respects_a_replaced_criterion(self):
        configured = copy.deepcopy(OFFICIAL_CHECKLIST)
        configured['06']['name'] = 'Новое правило проверки'
        configured['06']['description'] = 'Проверяйте уникальное правило для нового критерия.'
        configured['06']['allowed_values'] = [0, 1]
        configured['06']['scale'] = [0, 1]
        configured['06']['scale_max'] = 1
        prompt = build_system_prompt(configured)
        self.assertIn('Проверяйте уникальное правило для нового критерия.', prompt)
        self.assertNotIn('Ступень 4: Клиенту пришлось переспросить', prompt)
        self.assertIn('Критерий 03: оценивай необходимость', prompt)
        self.assertIn('Ступень 4: Клиенту пришлось переспросить', build_system_prompt())

    def test_ui_float_scale_accepts_model_integer_not_boolean(self):
        configured = copy.deepcopy(OFFICIAL_CHECKLIST)
        configured['06']['allowed_values'] = [0.0, 4.0, 7.0, 10.0]
        self.assertTrue(validate_evaluation(self.evaluation, self.dialog['transcript'], configured)[0])
        self.evaluation['06']['value'] = True
        self.assertFalse(validate_evaluation(self.evaluation, self.dialog['transcript'], configured)[0])

    def test_advisory_warning_preserves_score_and_skips_changed_rule(self):
        self.evaluation['06'] = {'value': 4, 'explanation': 'Проверьте объяснение.', 'evidence_replicas': [2]}
        with patch('app.services.ai.evaluator_core.evaluate_dialog_via_groq', return_value=(self.evaluation, 0.0, {})):
            official = evaluate_dialog(self.dialog)
            custom = copy.deepcopy(OFFICIAL_CHECKLIST)
            custom['06']['description'] = 'Новое правило оценки.'
            modified = evaluate_dialog(self.dialog, checklist=custom)
        self.assertTrue(official['is_success'])
        self.assertEqual(official['criteria']['06']['raw_value'], 4)
        self.assertTrue(official['warnings'])
        self.assertEqual(modified['warnings'], [])
        self.assertEqual(official['total_score'], modified['total_score'])

    def test_custom_eighth_criterion_is_not_forced_to_be_a_flag(self):
        custom = {'08': {'name': 'Custom criterion', 'type': 'binary', 'weight': 25,
                         'allowed_values': ['Да', 'Нет'], 'allows_na': False}}
        result = calculate_score({'08': {'value': 'Да'}}, checklist=custom)
        self.assertEqual(result['total_score'], 100.0)
        self.assertFalse(result['gross_error'])


if __name__ == "__main__":
    unittest.main()
