import io
import os
import pathlib
import sqlite3
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

from openpyxl import Workbook

from strengthos.ingestion import WorkbookLimitError, extract_rows, inspect_workbook, validate_mapping
from strengthos.metrics import compute
from strengthos.main import Login, Signup, app, health, list_ollama_models, login, ollama_models, setup_status, signup
from strengthos.setup import credentials, main as setup_coach
from fastapi import HTTPException, Response
from argon2 import PasswordHasher


def workbook(headers, rows):
    book = Workbook()
    sheet = book.active
    sheet.title = "Week 1"
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


class IngestionTests(unittest.TestCase):
    def test_wide_worksheet_within_200_column_limit_previews(self):
        book = Workbook()
        book.active.cell(1, 157, 'synthetic')
        stream = io.BytesIO()
        book.save(stream)
        self.assertEqual(len(inspect_workbook(stream.getvalue())['sheets']), 1)

        book.active.cell(1, 201, 'synthetic')
        stream = io.BytesIO()
        book.save(stream)
        with self.assertRaisesRegex(WorkbookLimitError, '200 columns'):
            inspect_workbook(stream.getvalue())

    def test_missing_dimension_metadata_is_scanned(self):
        data = workbook(['block', 'week', 'session', 'exercise', 'set'], [['B1', 'W1', 'D1', 'Squat', 1]])
        # A read-only worksheet with absent dimensions is a common Excel export.
        import zipfile
        from xml.etree import ElementTree as ET
        source = io.BytesIO(data)
        output = io.BytesIO()
        with zipfile.ZipFile(source) as original, zipfile.ZipFile(output, 'w') as rebuilt:
            for member in original.infolist():
                content = original.read(member.filename)
                if member.filename == 'xl/worksheets/sheet1.xml':
                    root = ET.fromstring(content)
                    dimension = root.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}dimension')
                    if dimension is not None:
                        root.remove(dimension)
                    content = ET.tostring(root)
                rebuilt.writestr(member, content)
        preview = inspect_workbook(output.getvalue())
        self.assertEqual(preview['sheets'], ['Week 1'])

    def test_two_layouts_preview_and_extract(self):
        cases = [
            (['block', 'week', 'session', 'exercise', 'set'], ['B1', 'W1', 'D1', 'Squat', 1], {'block': 'A', 'week': 'B', 'session': 'C', 'exercise_label': 'D', 'set_index': 'E'}),
            (['set', 'exercise', 'session', 'week', 'block'], [1, 'Squat', 'D1', 'W1', 'B1'], {'block': 'E', 'week': 'D', 'session': 'C', 'exercise_label': 'B', 'set_index': 'A'}),
        ]
        for headers, row, columns in cases:
            data = workbook(headers, [row])
            preview = inspect_workbook(data)
            mapping = {'sheet': 'Week 1', 'header_row': 1, 'columns': columns}
            validate_mapping(mapping, preview['sheets'])
            actual = extract_rows(data, mapping)
            self.assertEqual(actual[0]['exercise_label'], 'Squat')
            self.assertEqual(actual[0]['set_index'], 1)

    def test_wide_week_grid_carries_exercise_and_actual_load(self):
        book = Workbook()
        sheet = book.active
        sheet.title = 'Training'
        sheet['C1'] = 'Week1'
        sheet['L1'] = 'Week2'
        sheet['C2'] = 'Sets'
        sheet['A3'] = 'DAY 1'
        sheet['B4'] = 'Squat'
        sheet['C4'] = 'Set 1'
        sheet['D4'] = 5
        sheet['E4'] = 100
        sheet['G4'] = 5
        sheet['H4'] = 8
        sheet['C5'] = 'Set 2'
        sheet['D5'] = 4
        sheet['E5'] = 90
        sheet['G5'] = 4
        sheet['L4'] = 'Set 1'
        sheet['M4'] = 5
        sheet['N4'] = 105
        sheet['O4'] = 'RIR1-2'
        sheet['C6'] = 'Set 3'
        sheet['D6'] = '10,10'
        sheet['E6'] = '32,41'
        sheet['G6'] = '10,9'
        sheet['H6'] = '7,8'
        stream = io.BytesIO()
        book.save(stream)
        mapping = {'layout': 'wide_week_grid', 'sheet': 'Training', 'header_row': 2,
                   'week_columns': ['C', 'L'], 'block_label': 'B1'}
        validate_mapping(mapping, ['Training'])
        rows = extract_rows(stream.getvalue(), mapping)
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[1]['exercise_label'], 'Squat')
        self.assertEqual(rows[0]['actual_load'], 100)
        self.assertIsNone(rows[1]['actual_load'])
        self.assertEqual((rows[1]['target_rir_min'], rows[1]['target_rir_max']), (1, 2))
        self.assertEqual([(r['side'], r['actual_load'], r['actual_reps']) for r in rows[-2:]], [('right', '32', '10'), ('left', '41', '9')])

    def test_wide_zero_is_skipped_and_date_requires_cell_override(self):
        book = Workbook()
        sheet = book.active
        sheet.title = 'Training'
        sheet['C1'] = 'Week1'
        sheet['C2'] = 'Sets'
        sheet['A3'] = 'DAY 1'
        sheet['B4'] = 'Squat'
        sheet['C4'] = 'Set 1'
        sheet['D4'] = datetime(2026, 12, 10)
        sheet['E4'] = 100
        sheet['G4'] = 0
        sheet['H4'] = 9
        stream = io.BytesIO()
        book.save(stream)
        mapping = {'layout': 'wide_week_grid', 'sheet': 'Training', 'header_row': 2,
                   'week_columns': ['C'], 'block_label': 'B1', 'zero_actual_status': 'skipped',
                   'cell_overrides': {'Training!D4': 5}}
        preview = inspect_workbook(stream.getvalue())
        self.assertEqual(preview['correction_cells'][0]['location'], 'Training!D4')
        self.assertIn('unresolved_target_date', [issue['code'] for issue in preview['issues']])
        row = extract_rows(stream.getvalue(), mapping)[0]
        self.assertEqual(row['target_reps'], 5)
        self.assertEqual(row['actual_status'], 'skipped')
        self.assertIsNone(row['actual_reps'])
        self.assertIsNone(row['actual_load'])
        self.assertIsNone(row['actual_rpe'])
        self.assertEqual(row['_raw_actual_rpe'], 9)

    def test_date_formatted_exercise_targets_become_ranges(self):
        book = Workbook()
        sheet = book.active
        sheet.title = 'Training'
        sheet['C1'] = 'Week1'
        sheet['C2'] = 'Sets'
        sheet['A3'] = 'DAY 1'
        sheet['B4'] = 'Squat'
        sheet['C4'] = 'Set 1'
        sheet['D4'] = datetime(2026, 12, 10)
        sheet['D4'].number_format = 'd-m'
        sheet['F4'] = datetime(2026, 5, 4)
        sheet['F4'].number_format = 'd-m'
        stream = io.BytesIO()
        book.save(stream)
        preview = inspect_workbook(stream.getvalue())
        self.assertEqual(preview['correction_cells'], [])
        self.assertIn('date_formatted_ranges', [issue['code'] for issue in preview['issues']])
        mapping = {'layout': 'wide_week_grid', 'sheet': 'Training', 'header_row': 2,
                   'week_columns': ['C'], 'block_label': 'B1'}
        row = extract_rows(stream.getvalue(), mapping)[0]
        self.assertEqual((row['target_reps_min'], row['target_reps_max']), (10, 12))
        self.assertEqual((row['target_rpe_min'], row['target_rpe_max']), (4, 5))
        self.assertIsNone(row['target_reps'])
        self.assertIsNone(row['target_rpe'])

    def test_reject_non_workbook(self):
        with self.assertRaises(ValueError):
            inspect_workbook(b'not a workbook')


class MetricTests(unittest.TestCase):
    def test_volume_and_e1rm(self):
        rows = [
            {'id': '1', 'set_type': 'top', 'status': 'completed', 'reps': 5, 'load_kg': 100, 'target_rpe': 7, 'actual_rpe': 8},
            {'id': '2', 'set_type': 'backoff', 'status': 'completed', 'reps': 3, 'load_kg': 120, 'target_rpe': 8, 'actual_rpe': 8.5},
        ]
        metrics = {m['key']: m for m in compute(rows)}
        self.assertEqual(metrics['volume_load_kg']['value'], 860)
        self.assertEqual(metrics['completed_sets']['value'], 2)
        self.assertEqual(metrics['mean_rpe_deviation']['value'], 0.75)
        self.assertAlmostEqual(metrics['e1rm_kg']['value'], 132)

    def test_missing_failed_skipped_distinct(self):
        rows = [
            {'id': '1', 'set_type': 'top', 'status': 'completed', 'reps': 5, 'load_kg': 100},
            {'id': '2', 'set_type': 'backoff', 'status': 'failed', 'reps': 0, 'load_kg': 110},
            {'id': '3', 'set_type': 'backoff', 'status': 'skipped', 'reps': None, 'load_kg': None},
            {'id': '4', 'set_type': 'backoff', 'status': None, 'reps': None, 'load_kg': None},
        ]
        metrics = {m['key']: m for m in compute(rows)}
        self.assertEqual(metrics['completed_sets']['value'], 1)
        self.assertEqual(metrics['failed_sets']['value'], 1)
        self.assertEqual(metrics['completion_rate']['sample_count'], 3)
        self.assertEqual(metrics['volume_load_kg']['value'], 500)

    def test_e1rm_does_not_mix_exercises_or_sides(self):
        rows = [
            {'id': '1', 'exercise_id': 'squat', 'side': 'right', 'set_type': 'top', 'status': 'completed', 'reps': 5, 'load_kg': 100},
            {'id': '2', 'exercise_id': 'squat', 'side': 'left', 'set_type': 'top', 'status': 'completed', 'reps': 5, 'load_kg': 90},
        ]
        metric = next(m for m in compute(rows) if m['key'] == 'e1rm_kg')
        self.assertIsNone(metric['value'])
        self.assertEqual(metric['state'], 'insufficient')


class SchemaContractTests(unittest.TestCase):
    def test_starter_sql_executes_and_import_snapshot_columns_exist(self):
        connection = sqlite3.connect(':memory:')
        sql = (pathlib.Path(__file__).parents[1] / 'db' / 'schema.sql').read_text(encoding='utf-8')
        connection.executescript(sql)
        columns = {row[1] for row in connection.execute('PRAGMA table_info(import_jobs)')}
        self.assertIn('preview_json', columns)
        self.assertIn('snapshot_path', columns)
        set_columns = {row[1] for row in connection.execute('PRAGMA table_info(prescribed_sets)')}
        self.assertTrue({'target_reps_min', 'target_reps_max', 'target_rpe_min', 'target_rpe_max', 'target_rir_min', 'target_rir_max'} <= set_columns)
        week_columns = {row[1]: row[3] for row in connection.execute('PRAGMA table_info(training_weeks)')}
        self.assertEqual(week_columns['week_key'], 1)
        self.assertEqual(week_columns['start_date'], 0)
        self.assertEqual(week_columns['end_date'], 0)
        block_columns = {row[1]: row[3] for row in connection.execute('PRAGMA table_info(training_blocks)')}
        self.assertEqual(block_columns['start_date'], 0)
        self.assertEqual(connection.execute('PRAGMA foreign_keys').fetchone()[0], 1)


class OllamaContractTests(unittest.TestCase):
    def test_model_discovery_matches_api_contract(self):
        response = io.BytesIO(b'{"models":[{"name":"qwen3:1.7b","digest":"abc","size":123}]}')
        with patch('strengthos.main.urlopen', return_value=response):
            self.assertEqual(ollama_models(), [{'name': 'qwen3:1.7b', 'digest': 'abc', 'size_bytes': 123}])

    def test_health_reports_ollama_reachability(self):
        models = [{'name': 'qwen3:1.7b', 'digest': 'abc', 'size_bytes': 123}]
        with patch('strengthos.main.ollama_models', return_value=models):
            self.assertEqual(health()['ollama'], 'ok')
            self.assertEqual(list_ollama_models(), models)
        with patch('strengthos.main.ollama_models', side_effect=OSError):
            self.assertEqual(health()['ollama'], 'unavailable')
            with self.assertRaises(HTTPException) as error:
                list_ollama_models()
            self.assertEqual(error.exception.status_code, 503)


class LoginContractTests(unittest.TestCase):
    def test_first_run_signup_creates_only_one_coach(self):
        with tempfile.TemporaryDirectory() as directory, patch('strengthos.main.data_dir', pathlib.Path(directory)):
            self.assertEqual(setup_status(), {'signup_available': True, 'needs_email_setup': False})
            self.assertEqual(signup(Signup(email='Coach@Example.com', password='long-test-password')), {'ok': True})
            self.assertEqual(setup_status(), {'signup_available': False, 'needs_email_setup': False})
            self.assertIn('csrf_token', login(Login(email='coach@example.com', password='long-test-password'), Response()))
            with self.assertRaises(HTTPException) as error:
                signup(Signup(email='other@example.com', password='another-long-password'))
            self.assertEqual(error.exception.status_code, 409)
            self.assertEqual(credentials(pathlib.Path(directory))[0], 'coach@example.com')
        with self.assertRaises(ValueError):
            Signup(email='coach@example.com', password='short')
        paths = app.openapi()['paths']
        self.assertIn('/api/v1/auth/signup', paths)
        self.assertIn('/api/v1/auth/setup-status', paths)

    def test_setup_and_login_require_matching_email_and_password(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(os.environ, {'STRENGTHOS_DATA_DIR': directory}), \
             patch('builtins.input', return_value='Coach@Example.com'), \
             patch('strengthos.setup.getpass', side_effect=['long-test-password', 'long-test-password']), \
             patch('strengthos.main.data_dir', pathlib.Path(directory)):
            setup_coach()
            self.assertEqual(credentials(pathlib.Path(directory))[0], 'coach@example.com')
            response = Response()
            self.assertIn('csrf_token', login(Login(email='COACH@example.com', password='long-test-password'), response))
            self.assertIn('strengthos_session=', response.headers['set-cookie'])
            for email, password in [('other@example.com', 'long-test-password'), ('coach@example.com', 'wrong')]:
                with self.assertRaises(HTTPException) as error:
                    login(Login(email=email, password=password), Response())
                self.assertEqual(error.exception.status_code, 401)
            with self.assertRaises(ValueError):
                Login(password='long-test-password')
            with self.assertRaises(ValueError):
                Login(email='not-an-email', password='long-test-password')

    def test_existing_password_can_add_email_without_replacing_hash(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(os.environ, {'STRENGTHOS_DATA_DIR': directory}), \
             patch('builtins.input', return_value='coach@example.com'), \
             patch('strengthos.setup.getpass', return_value='long-test-password'), \
             patch('strengthos.main.data_dir', pathlib.Path(directory)):
            password_path = pathlib.Path(directory) / 'coach_password.hash'
            password_hash = PasswordHasher().hash('long-test-password')
            password_path.write_text(password_hash)
            self.assertEqual(setup_status(), {'signup_available': False, 'needs_email_setup': True})
            setup_coach()
            self.assertEqual(password_path.read_text(), password_hash)
            self.assertEqual(credentials(pathlib.Path(directory))[0], 'coach@example.com')
            self.assertEqual(setup_status(), {'signup_available': False, 'needs_email_setup': False})


if __name__ == '__main__':
    unittest.main()
