"""Exercise the API flow using a temporary database and a deterministic model response."""
import tempfile
import unittest
import io
import os
import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database.database import Base, get_db
from app.services.ai.checklist_rules import OFFICIAL_CHECKLIST
from app.services.ai.evaluator_core import evaluate_dialog
from app.services import conversation_service


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        def db_override():
            db = self.sessions()
            try: yield db
            finally: db.close()
        app.dependency_overrides[get_db] = db_override
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.engine.dispose()

    def checklist_payload(self):
        criteria = []
        for cid, rule in OFFICIAL_CHECKLIST.items():
            kind = rule['type']
            criteria.append({'name': 'Gross Violations' if cid == '08' else rule['name'],
                'description': rule['description'], 'weight': rule['weight'],
                'answer_type': 'numeric' if 'scale' in kind else ('yes_no_na' if rule['allows_na'] else 'yes_no'),
                'na_allowed': rule['allows_na'], 'scale': rule.get('scale')})
        return {'name': 'Test checklist', 'channel': 'both', 'language': 'ALL', 'criteria': criteria}

    def test_import_and_navigation_from_provided_dev_data(self):
        response = self.client.get('/api/conversations')
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body['total'], 65)
        first = body['conversations'][0]
        detail = self.client.get('/api/conversations/' + first['conversation_id'])
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()['transcript'][0]['turn_id'], 1)

    def test_import_endpoint_validates_and_saves_before_switching(self):
        source = Path(__file__).resolve().parent.parent / 'data' / 'dev_data.json'
        payload = json.loads(source.read_text(encoding='utf-8-sig'))
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            with patch.dict(os.environ, {'CQA_ORGANIZER_API_URL': 'https://example.invalid/data'}), \
                 patch.object(conversation_service, 'DATA_DIR', directory), \
                 patch.object(conversation_service, 'ACTIVE_FILE', directory / 'active_dataset.txt'), \
                 patch.object(conversation_service, 'urlopen', return_value=io.BytesIO(json.dumps(payload).encode('utf-8'))):
                response = self.client.post('/api/imports', json={'group_id': 'DEV'})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()['total'], 65)
                self.assertTrue((directory / 'dev_data.json').exists())
                self.assertEqual((directory / 'active_dataset.txt').read_text(encoding='utf-8'), 'dev')
            invalid = dict(payload)
            invalid['data'] = dict(payload['data'], records=payload['data']['records'][:-1])
            with patch.dict(os.environ, {'CQA_ORGANIZER_API_URL': 'https://example.invalid/data'}), \
                 patch.object(conversation_service, 'DATA_DIR', directory), \
                 patch.object(conversation_service, 'ACTIVE_FILE', directory / 'active_dataset.txt'), \
                 patch.object(conversation_service, 'urlopen', return_value=io.BytesIO(json.dumps(invalid).encode('utf-8'))):
                response = self.client.post('/api/imports', json={'group_id': 'DEV'})
                self.assertEqual(response.status_code, 502)
                self.assertEqual((directory / 'active_dataset.txt').read_text(encoding='utf-8'), 'dev')

    def test_checklist_evaluation_appeal_review(self):
        created = self.client.post('/api/checklists', json=self.checklist_payload())
        self.assertEqual(created.status_code, 200, created.text)
        checklist = created.json()
        dialog = {'conversation_id': 'example', 'transcript': [
            {'timestamp': '00:01', 'speaker': 'client', 'text': 'Общий вопрос'},
            {'timestamp': '00:02', 'speaker': 'operator', 'text': 'Здравствуйте, я Алия.'}]}
        def fake_evaluate(*args, **kwargs):
            kwargs['mock'] = True
            return evaluate_dialog(*args, **kwargs)
        with patch('app.main.get_conversation_by_id', return_value=dialog), \
             patch('app.services.evaluation_service.get_conversation_by_id', return_value=dialog), \
             patch('app.services.evaluation_service.SessionLocal', self.sessions), \
             patch('app.services.evaluation_service.evaluate_dialog', side_effect=fake_evaluate):
            response = self.client.post('/api/evaluations', json={'conversation_id': 'example',
                'checklist_id': checklist['id'], 'checklist_version': '1'})
        self.assertEqual(response.status_code, 202, response.text)
        evaluation_id = response.json()['evaluation_id']
        evaluation = self.client.get(f'/api/evaluations/{evaluation_id}').json()
        self.assertEqual(evaluation['status'], 'completed', evaluation)
        results = self.client.get('/api/results/example').json()
        details = results['results'][0]['details']
        criterion = next(x for x in details if x['criterion_id'] == checklist['criteria'][0]['id'])
        appeal = self.client.post('/api/appeals', json={'evaluation_id': evaluation_id,
            'criterion_result_id': criterion['criterion_result_id'], 'comment': 'Проверить приветствие'})
        self.assertEqual(appeal.status_code, 200, appeal.text)
        decision = self.client.post(f"/api/appeals/{appeal.json()['id']}/review", json={
            'reviewer_answer': 'NO', 'reviewer_reason': 'Приветствия не было'})
        self.assertEqual(decision.status_code, 200, decision.text)
        self.assertEqual(decision.json()['original_answer'], 'Да')
        self.assertLess(decision.json()['new_score'], evaluation['score'])
        saved = self.client.get('/api/appeals').json()['appeals'][0]
        self.assertEqual(saved['reviewer_answer'], 'NO')
        self.assertEqual(saved['original_answer'], 'Да')


if __name__ == '__main__': unittest.main()
