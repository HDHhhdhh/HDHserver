"""Literal test projection oracle; source reads plus OS-temp fixture I/O only."""
from __future__ import annotations
import argparse
import ast
import datetime as dt
import hashlib
import json
import os
import re
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from types import ModuleType, SimpleNamespace
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TODAY = '2026-10-01'
NAME = '다항식 (LV.2)'
LABEL = '단원평가 / ' + NAME
URL = 'https://map.example/unit-round-2'
CONFIG = {'categories': {'UNIT': {'label': '단원평가', 'tests': [{'id': 'unit-r2', 'sourceId': 'unit-source', 'name': NAME, 'curriculum': '공수1', 'round': '2', 'answerKeys': {'2': ['1', '3', '4', '2']}}]}, 'REVIEW': {'label': '복습', 'tests': [{'id': 'review-r1', 'name': '복습 A', 'curriculum': '공수1', 'round': '1', 'sourceFiles': {'solutionFileId': 'CONFIG_SOLUTION'}}]}}}
LINK_MAP = {'unit-source': {'2': {'answerUrl': URL}}}
PRIMARY = {'testId': 'unit-r2', 'name': LABEL, 'score': '2/4', 'wrong': ['2', '4', 0, 'bad'], 'submittedAnswers': ['1', '2', '4', '1'], 'wrongDetails': [{'raw': 'must not leak'}], 'createdAt': '2026-09-29T10:00:00Z', 'memo': ' 검토 '}
RECORDS = {'2026-09-29': {'7': [PRIMARY, {'name': 'invalid', 'score': '1/0'}, None]}, '2026-09-30': {'8': {'tests': [{'testId': 'unit-source', 'name': LABEL, 'score': '4/4', 'createdAt': '2026-09-30T10:00:00Z', 'answersText': '1. 1\n2. 3\n3. 4\n4. 2'}]}}, TODAY: {'9': [{'testId': 'review-r1', 'name': '복습 / 복습 A', 'score': '3/4', 'wrong': [1]}]}, '2026-10-02': {'7': [{**PRIMARY, 'score': '4/4'}]}, 'bad-date': {'7': [PRIMARY]}}
LOGS = {'2026-09-29': {'7': {'tests': [{**PRIMARY, 'score': '4/4'}]}}, '2026-09-30': {'10': {'tests': [{'name': LABEL, 'score': '1/4', 'wrong': [2, 3, 4], 'createdAt': '2026-09-30T11:00:00Z', 'memo': 'legacy'}]}}}
STUDENTS = [{'id': '7', 'name': '가학생', 'level': '상', 'curriculum': '공수1'}, {'id': '8', 'name': '나학생', 'level': 'unknown'}, {'id': '9', 'name': '라학생', 'level': '중상'}, {'id': '10', 'name': '다학생', 'level': '중'}]

def function_body_sha256(node):

    def canonical(value):
        if isinstance(value, ast.AST):
            return {'node': type(value).__name__, **{key: canonical(item) for key, item in ast.iter_fields(value) if item is not None and item != []}}
        if isinstance(value, list):
            return [canonical(item) for item in value]
        return value
    data = json.dumps(canonical(node), ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(data.encode('utf-8')).hexdigest()

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str).encode('utf-8')).hexdigest()

def functions(path):
    return {n.name: n for n in ast.parse(path.read_text(encoding='utf-8-sig')).body if isinstance(n, ast.FunctionDef)}

def module_from(path, name):
    m = ModuleType(name)
    m.__file__ = str(path)
    sys.modules[name] = m
    exec(compile(path.read_text(encoding='utf-8-sig'), str(path), 'exec'), m.__dict__)
    return m

def runtime(root):
    assert root.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    os.environ['DATA_MIRROR_DIR'] = str(root / '_data_mirror')
    temp_root = Path(tempfile.gettempdir()).resolve()

    def audit(event, args):
        if event == 'socket.connect':
            raise AssertionError('verification must not open network connections')
        if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
            flags = args[2] if len(args) > 2 and isinstance(args[2], int) else 0
            if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                assert Path(os.fsdecode(args[0])).resolve().is_relative_to(temp_root), ('write outside OS-temp', args[0])
        elif event in {'os.rename', 'os.link', 'os.symlink'}:
            for target in args[:2]:
                if isinstance(target, (str, bytes, os.PathLike)):
                    assert Path(os.fsdecode(target)).resolve().is_relative_to(temp_root), (event, target)
    sys.addaudithook(audit)
    assert 'core.paths' not in sys.modules
    p = ModuleType('core.paths')
    p.BASE = root
    p.DB_PATH = root / 'app.sqlite'
    p.DATA_DIR = root / 'data'
    p.FILES_DIR = root / 'files'
    for n, f in {'LOGS_PATH': 'logs.json', 'STU_PATH': 'students.json', 'PRG_PATH': 'progress.json', 'TESTS_PATH': 'tests.json', 'TESTS_CFG_PATH': 'tests-config.json', 'WATCH_PATH': 'watch.json', 'UPD_PATH': 'updates.json', 'ABS_PATH': 'absent.json'}.items():
        setattr(p, n, root / f)
    p.__getattr__ = lambda name: root / (name.lower() + '.json')
    sys.modules['core.paths'] = p
    for name in ('core.student_notifications', 'core.student_notification_hooks'):
        m = ModuleType(name)
        m.__getattr__ = lambda attr: lambda *args, **kwargs: None
        sys.modules[name] = m
    m = ModuleType('routes.api_basic')
    m.get_log_repository = lambda: SimpleNamespace(read_json_map=lambda: deepcopy(LOGS))
    sys.modules[m.__name__] = m

def detail(answer_url=URL):
    common = {'type': 'UNIT', 'curriculum': '공수1', 'testName': NAME, 'unitName': '다항식', 'testLevel': 2, 'term': ''}
    return {'range': {'start': '2026-09-29', 'end': TODAY}, 'filters': {'test': '', 'type': '', 'curriculum': '', 'unit_name': '', 'test_level': '', 'term': '', 'band': ''}, 'total': 3, 'answerUrl': answer_url, 'records': [{**common, 'sid': '8', 'studentName': '나학생', 'level': '', 'pct': 100.0, 'correct': 4, 'total': 4, 'wrong': [], 'wrongDetails': [], 'createdAt': '2026-09-30T10:00:00Z', 'memo': '', 'testId': 'unit-source'}, {**common, 'sid': '7', 'studentName': '가학생', 'level': '상', 'pct': 50.0, 'correct': 2, 'total': 4, 'wrong': [2, 4], 'wrongDetails': [{'questionNo': 2, 'myAnswer': '2', 'correctAnswer': '3'}, {'questionNo': 4, 'myAnswer': '1', 'correctAnswer': '2'}], 'createdAt': '2026-09-29T10:00:00Z', 'memo': '검토', 'testId': 'unit-r2'}, {**common, 'sid': '10', 'studentName': '다학생', 'level': '중', 'pct': 25.0, 'correct': 1, 'total': 4, 'wrong': [2, 3, 4], 'wrongDetails': [], 'createdAt': '2026-09-30T11:00:00Z', 'memo': 'legacy', 'testId': ''}]}

def statistics():
    hist = {'0-49': 0, '50-59': 0, '60-69': 0, '70-79': 0, '80-89': 0, '90-100': 0}
    singles = {}
    for pct, correct, bucket in [(25.0, 1.0, '0-49'), (50.0, 2.0, '50-59'), (75.0, 3.0, '70-79'), (100.0, 4.0, '90-100')]:
        singles[pct] = {'count': 1, 'avg_pct': pct, 'median_pct': pct, 'p90_pct': pct, 'min_pct': pct, 'max_pct': pct, 'stddev_pct': 0.0, 'avg_correct': correct, 'avg_total': 4.0, 'pct_hist': {**hist, bucket: 1}}
    unit = {'count': 3, 'avg_pct': 58.33, 'median_pct': 50.0, 'p90_pct': 50.0, 'min_pct': 25.0, 'max_pct': 100.0, 'stddev_pct': 31.18, 'avg_correct': 2.33, 'avg_total': 4.0, 'pct_hist': {**hist, '0-49': 1, '50-59': 1, '90-100': 1}}
    review = singles[75.0]
    return {'range': {'start': '2026-09-29', 'end': TODAY}, 'updatedAt': '2026-10-01T00:00:00Z', 'by_test': {NAME: {**unit, 'bands': {'상': singles[50.0], '중': singles[25.0], '하': singles[100.0]}, 'wrong_freq': {'2': 2, '3': 1, '4': 2}}, '복습 A': {**review, 'bands': {'중상': review}, 'wrong_freq': {'1': 1}}}, 'by_test_id': {'unit-r2': singles[50.0], 'unit-source': singles[100.0], 'review-r1': review}, 'by_test_signature': {'UNIT␟공수1␟' + NAME + '␟␟2': unit, 'REVIEW␟공수1␟복습 A␟␟1': review}, 'summary': {'UNIT': unit, 'REVIEW': review}, 'unit_rows': [{**unit, 'type': 'UNIT', 'curriculum': '공수1', 'unit_name': '다항식', 'test_level': 2}], 'series_rows': {'REVIEW': [{**review, 'type': 'REVIEW', 'curriculum': '공수1', 'term': '', 'test_name': '복습 A'}]}, 'final_rows': [], 'hell_rows': []}

def routes(source_root, root, tag):
    from flask import Flask
    for name, value in [('tests.json', RECORDS), ('logs.json', LOGS), ('students.json', STUDENTS), ('tests-config.json', CONFIG), ('test_answer_link_map.json', LINK_MAP)]:
        (root / name).write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in root.glob('*.json')}
    m = module_from(source_root / 'routes/api_tests.py', 'routes._test_projection_' + tag)
    m.TEST_ANSWER_LINK_MAP_PATH = root / 'test_answer_link_map.json'
    m.get_log_repository = lambda: SimpleNamespace(read_json_map=lambda: deepcopy(LOGS))
    m.academy_network_allowed = lambda: True

    class FrozenDate(dt.date):

        @classmethod
        def today(cls):
            return cls(2026, 10, 1)
    m.dt = SimpleNamespace(date=FrozenDate, timedelta=dt.timedelta)
    m.utc_now_isoz = lambda: '2026-10-01T00:00:00Z'
    app = Flask('test-projection-' + tag)
    app.config['TESTING'] = True
    app.register_blueprint(m.bp_api_tests)
    c = app.test_client()
    r = c.get('/api/tests-records?test_id=unit-r2&recent_days=3')
    assert r.status_code == 200
    assert r.get_json() == detail(), r.get_json()
    s = c.get('/api/tests-stats?start=2026-09-29&end=' + TODAY + '&include_wrong=1')
    assert s.status_code == 200
    assert s.get_json() == statistics(), s.get_json()
    assert c.get('/api/tests-records').status_code == 400
    band = c.get('/api/tests-records?test_id=unit-r2&recent_days=3&band=상').get_json()
    assert band['records'] == [detail()['records'][1]] and band['total'] == 1
    filtered = c.get('/api/tests-records?type=UNIT&curriculum=공수1&unit_name=다항식&test_level=2&recent_days=3').get_json()
    assert filtered['records'] == detail()['records']
    m.academy_network_allowed = lambda: False
    assert c.get('/api/tests-records?testId=unit-r2&recent_days=3').get_json() == detail('')
    public = c.get('/api/tests').get_json()
    for field in ('submittedAnswers', 'answersText', 'wrongDetails', 'must not leak'):
        assert field not in json.dumps(public, ensure_ascii=False)
    for url in ('/api/submit-test', '/api/ocr-test-sheet', '/api/ocr-test-sheet-review', '/student-test/7'):
        assert c.post(url, json={}).status_code in (404, 405)
    for p, (stamp, data) in before.items():
        assert p.read_bytes() == data and p.stat().st_mtime_ns == stamp, p.name + ' GET mutation'
    candidates = m._legacy_test_record_candidates()
    candidates[0]['wrong'].append(999)
    assert 999 not in m._legacy_test_record_candidates()[0]['wrong']
    m.academy_network_allowed = lambda: True
    app.json.sort_keys = False
    unsorted_detail = c.get('/api/tests-records?test_id=unit-r2&recent_days=3').get_data()
    unsorted_stats = c.get('/api/tests-stats?start=2026-09-29&end=' + TODAY + '&include_wrong=1').get_data()
    return {'detail': digest(r.get_json()), 'stats': digest(s.get_json()), 'public': digest(public), 'unsorted_detail_body': hashlib.sha256(unsorted_detail).hexdigest(), 'unsorted_stats_body': hashlib.sha256(unsorted_stats).hexdigest()}
ASSIGNMENT_FUNCTIONS = {'_normalize_test_assignment_status', '_test_assignment_status_label', '_is_active_test_assignment_status', '_round_label_for_assignment', '_fallback_assigned_test_from_label', '_normalized_test_curriculum', '_assigned_test_curriculum', '_filter_assigned_tests_for_student_curriculum', '_assigned_test_label', '_normalized_test_status_map', '_append_unique_assigned_test_label', '_collect_assigned_test_metadata', '_student_assigned_test_labels', '_build_student_assigned_test_items', '_student_assigned_tests_for_date', '_academy_restricted_assigned_tests'}

def original_assignments(source_root):
    from core.network_access import strip_answer_link_fields
    from core.test_answer_links import resolve_test_assignment_answer_url
    from core.update_assignment_rules import sid_lookup
    fs = functions(source_root / 'routes/api_basic.py')
    nodes = [n for name, n in fs.items() if name in ASSIGNMENT_FUNCTIONS]
    assert len(nodes) == len(ASSIGNMENT_FUNCTIONS)
    scope = {'re': re, '_sid_lookup': sid_lookup, 'TEST_ASSIGN_CLEAR_META_KEY': '__testsClearedAt', 'TEST_ASSIGN_DAILY_ITEMS_KEY': 'testAssignmentDailyTests', 'strip_answer_link_fields': strip_answer_link_fields, '_test_assignment_answer_url': lambda item: resolve_test_assignment_answer_url(item, tests_config=CONFIG, answer_link_map=LINK_MAP)}
    tree = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *nodes], type_ignores=[])
    exec(compile(ast.fix_missing_locations(tree), 'original-assigned-tests', 'exec'), scope)
    return scope

def assignment_fixture():
    logs = {TODAY: {'7': {'assignedTests': [{'id': 'direct', 'label': '직접', 'categoryKey': 'UNIT', 'curriculum': '공수1', 'answerUrl': 'https://direct.example/answer', 'unknown': {'keep': True}}, {'id': 'review-r1', 'label': '설정', 'categoryKey': 'REVIEW', 'curriculum': '공수1'}, {'id': 'unit-r2', 'label': '생성', 'categoryKey': 'UNIT', 'curriculum': '공수1', 'round': '2'}, {'id': 'old', 'label': '완료', 'curriculum': '공수1'}], 'testAssignmentDailyTests': [{'label': '직접', 'daily': True}, {'label': '생성', 'round': '2'}]}}}
    progress = {TODAY: {'7': {'tests': {'생성': 'interrupted', '설정': 'assigned', '직접': 'assigned', '완료': 'done', '삭제': 'none'}}}}
    expected = [{'id': 'direct', 'label': '직접', 'categoryKey': 'UNIT', 'curriculum': '공수1', 'answerUrl': 'https://direct.example/answer', 'unknown': {'keep': True}, 'daily': True, 'status': 'assigned', 'statusLabel': '배정'}, {'id': 'unit-r2', 'label': '생성', 'categoryKey': 'UNIT', 'curriculum': '공수1', 'round': '2', 'status': 'interrupted', 'statusLabel': '배부', 'answerUrl': URL}, {'id': 'review-r1', 'label': '설정', 'categoryKey': 'REVIEW', 'curriculum': '공수1', 'status': 'assigned', 'statusLabel': '배정', 'answerUrl': 'https://drive.google.com/file/d/CONFIG_SOLUTION/view?usp=drivesdk'}]
    return (progress, logs, expected)

def assignments(build, filter_curriculum, restrict):
    progress, logs, expected = assignment_fixture()
    before = digest((progress, logs, CONFIG, LINK_MAP))
    actual = build(progress, logs, TODAY, '007', {})
    assert actual == expected, actual
    assert build({TODAY: {'7': {'__testsClearedAt': 'stamp'}}}, logs, TODAY, '007', logs) == []
    assert build({TODAY: {'7': {'tests': {'완료': 'done', '직접': 'skip'}}}}, logs, TODAY, '7', {}) == []
    assert build({}, {}, TODAY, '7', logs) == [expected[0], {**expected[1], 'status': 'assigned', 'statusLabel': '배정'}]
    label = '단원평가 / 공수1 / 상 / 2회차 / fallback'
    assert build({TODAY: {'7': {'tests': {label: {'status': 'interrupted'}}}}}, {}, TODAY, '7', {}) == [{'label': label, 'name': 'fallback', 'status': 'interrupted', 'statusLabel': '배부', 'categoryLabel': '단원평가', 'curriculum': '공수1', 'difficulty': '상', 'round': '2'}]
    assert filter_curriculum(actual, {'curriculum': '공통 수학 1'}) == expected
    assert filter_curriculum(actual, {'curriculum': '대수'}) == []
    outside = restrict(actual, False)
    assert outside == [{**{k: v for k, v in x.items() if k != 'answerUrl'}, 'answerRestricted': True} for x in expected]
    assert digest((progress, logs, CONFIG, LINK_MAP)) == before
    return {'assigned': digest(actual), 'outside': digest(outside)}

def bootstrap(source_root, build, filter_curriculum, restrict, tag):
    m = module_from(source_root / 'routes/student_bootstrap_projection.py', 'routes._bootstrap_projection_' + tag)
    progress, logs, expected = assignment_fixture()
    student = {'id': '7', 'name': '가학생', 'curriculum': '공수1'}
    repo = SimpleNamespace(read_entry=lambda date, sid: SimpleNamespace(entry=deepcopy(logs[TODAY]['7'])), read_json_map=lambda: deepcopy(logs))
    deps = m.StudentBootstrapProjectionDependencies(students_path='students', videos_path='videos', updates_path='updates', watch_path='watch', load=lambda path: deepcopy({'students': [student], 'videos': [], 'updates': {}, 'watch': {}}[path]), load_absent=lambda: {'by_date': {}, 'by_student': {}}, load_progress=lambda: deepcopy(progress), load_material_state=lambda: ({}, {}, {}, False), get_log_repository=lambda: repo, homework_books_from_log=lambda entry: [], student_is_registered=lambda *args: True, student_is_self_study=lambda *args: False, student_absent=lambda *args: False, active_alias_sid=lambda *args: '', dashboard_enabled=lambda: False, dashboard_projection=lambda **kwargs: {}, build_latest_status=lambda value: {}, student_completion_videos=lambda *args: [], course_videos_completed=lambda *args: False, load_updates_with_auto_assign=lambda **kwargs: {}, build_auto_blocked=lambda *args: {}, blocked_mids=lambda *args: set(), eligible_review_mids=lambda *args: set(), filter_self_study_assignment=lambda value, *args: value, filter_auto_assignment=lambda value, *args: value, review_states_through_date=lambda *args: {}, student_primary_video_mids=lambda *args: set(), academy_restricted_videos=lambda items, allowed: items, review_video_projection=lambda *args: [], assigned_material_list=lambda value: [], filter_materials=lambda *args: {}, assigned_tests=build, filter_tests_for_curriculum=filter_curriculum, academy_restricted_tests=restrict, today_iso=lambda: TODAY, dashboard_course_block_message='course blocked')
    from core.network_access import ACADEMY_ACCESS_MESSAGE
    actual, status = m.build_student_bootstrap_payload(deps, sid='7', date=TODAY, public_request=True, academy_allowed_resolver=lambda: True)
    expected_payload = {'ok': True, 'date': TODAY, 'students': [student], 'student': student, 'videos': [], 'reviewVideos': [], 'updates': {TODAY: {'7': []}}, 'materials': {}, 'assigns': {'7': []}, 'absent': {'by_date': {TODAY: []}, 'by_student': {}}, 'logs': logs, 'assignedTests': expected, 'homeworkBooks': [], 'selfStudy': False, 'courseVideosCompleted': False, 'academyAccessAllowed': True, 'outsideAcademyBlocked': False, 'networkBlocked': False, 'academyOnlyMessage': ACADEMY_ACCESS_MESSAGE}
    assert status == 200 and actual == expected_payload, actual
    outside, status = m.build_student_bootstrap_payload(deps, sid='7', date=TODAY, public_request=True, academy_allowed_resolver=lambda: False)
    assert status == 200 and outside == {**expected_payload, 'assignedTests': restrict(expected, False), 'academyAccessAllowed': False, 'outsideAcademyBlocked': True, 'networkBlocked': True}
    return digest(actual)

def hashes(source_root):
    result = {}
    for rel in ('routes/api_tests.py', 'routes/api_basic.py', 'routes/student_bootstrap_projection.py'):
        result[rel] = {name: function_body_sha256(node) for name, node in functions(source_root / rel).items()}
    return result
PRE_EXTRACTION_BODY_SHA256 = {'test_record_projection': {'_strip_prefix_for_display': 'f6c6c3b82b784a0253552dae6a9b399a50d7e37eb0f6873d69763c778550ae80', '_parse_unit_and_test_level': 'ff4ac89a09c7b27212fa0cf6ab1b66fbefeedf8b2c0eb0c2d1613cdc8daf6c4b', '_canon_test_name': '089c3756388ce000c586822a20014fcb84138c4be2543254b960e8f9fc7c8a75', '_normalize_test_type': '3b9981f7db664536b75264a7c7567e56f685e5f61fe8177d3836e2955f649eba', '_normalize_test_term': '8e9545589c1a9db04726798ff01ad588718dda6fa4992b66fdbc94b37842f88a', '_build_test_catalog': '96c8d2007072069d3c3ef30ac69f583b4adbc0c4f0bdfce0c69e546c337591c0', '_resolve_test_meta': '5b18512cab45aa3da184ec0119c28eea63a08cec6d86725b71d7c843d42b36fc', '_record_meta': 'cc1af698042ba6aa4ef59200739afab602379339f69e3ba7ad592672d90b596f', '_meta_matches_target': '96a5044caf5dd23352b4cb8c4529bea4461550c21c338caf66304fc3e543b59d', '_strip_answer_line_number': '89eeb837e7741a3e743cac9b9765ce7fab33ddb80697e6a3a10aa8827cb9398d', '_parse_answer_spec': '3c18235cbc976949fc585d09c04f9e9e25c960d0941c5e0f27100016726ee86e', '_find_test_def_by_id': '116f2fb2c67211548f70279c9abe83f33432e542622e2b087c8bfb0d81133294', '_get_answer_key_for_round': '64c8783ddd11369b25b14fc51c157d127c614abe84d8128bd224ec330268a253', '_wrong_answer_details': '4a08d5293600980d8def2edf30e61f2a8609a01edb16bf6f5a2375d9025169dc', '_normalize_wrong_numbers': 'fc04fc4f34242a401f2b2be375cc9e3b5c858a15267d8830db56944aa0407aba', '_submitted_answers_from_record': '119dae9b2ade5e4dfc0e54f7988c6a76dbbc66129f93a172ab69f8c61222dbee', '_sanitize_tests_payload_for_public_api': 'e2a75e8d55d1c4c50cb4b70f287f85771b3618b547813ab72ee7c75932725eed', '_parse_date': 'f2d569dcfdd41657da1efe6c715b7e2b6fee7abc2658a381752f1907db567bbd', '_normalized_test_record_candidates': '0da22f42d31801ad013a6bbd77e049d151e98891bfec8b991c1443ee446069dd'}, 'test_statistics_projection': {'_stats_signature': 'eec3163d152cc6423807407035fec17922be6e46ea801c5eda51e60a5b8a8309', '_score_bucket': 'beb516acf197d24625a1a1a7f0448734214f79927b601ee2f306d8b313a5e036', '_make_stats_agg': '66d6062e4e79127470bcab388e2c0cbde969f2b246a997d9c58d7e4b33e94b84', '_push_stats_agg': '8d6e571806daafa536dbb9894add48832391edc5121a59bffbf6870c94d20b53', '_finalize_stats_agg': '10cc904668fe0c04c20cd7402809a4219c61e3bc344db099d0040d3364a710df'}, 'student_test_projection': {'_normalize_test_assignment_status': '26fe679a716243393e1694e6bc87760869a7fe9060bb4ab8019f6f5e0f1e8973', '_test_assignment_status_label': '462a8f6cb71f992b0bc92134736b23eace0aa7783ce6a7ce4182ec4b05e68ec8', '_is_active_test_assignment_status': '2ed3557a0d2bd4465605fbe5f71f6571c1f96460b46dc8bd18b2253bb099d949', '_round_label_for_assignment': '46d189c8a6db2e99bfe1122c7f4aec91c7ccc3e194e2132429f445114756d71d', '_fallback_assigned_test_from_label': '9a0ced5ded1b283d8b61c865643d8abaa69b17c860cfef90d4af8f297c291c1c', '_normalized_test_curriculum': 'c7de5217b4cfda39c78163c3873e64bd4c2bcf2a3a29e0f9aba190ccce29c4f0', '_assigned_test_curriculum': 'fbe10bb01dcd1d7c120af8eb4b71f977569776010bbf9d23678b83405a660c05', '_filter_assigned_tests_for_student_curriculum': '51fe008d19c38bb3ed3e12623f0c194d938cf57ab1ccd149d566296a3ef7a449', '_assigned_test_label': '417b50a4cb322245e3bdd9d81d2b18c041190cbe50fdfa71c23c69168e222cfe', '_normalized_test_status_map': '76cfd46cc434447e36b2c4089040aa19b01d2e70f1ec77d8dc7de84b2406ad68', '_append_unique_assigned_test_label': '1163bee5d08fa6857f3494841b233a413c8d6a85db6a067767d753731fc06794', '_collect_assigned_test_metadata': '50e7cd04e4dc8eeac748f8bac438f3fa9373baf4cfae774d3fde13e10c7f4072', '_student_assigned_test_labels': 'ec78780857123c23332b7e36cc548f04a05b9b76e720b3c2f1bb9a0b5da4baaa'}}
PRE_EXTRACTION_PAYLOAD_SHA256 = {'routes': {'detail': '07850b17b2336ab2038bff5afd2f92ede671d5e40ff849d3e808129da43f74ad', 'stats': '8bc73eac1996facc40455075c0e72c9ccc81d600c39ee7d7d3c52c115515f885', 'public': '5afeda1d668edeb1279af61d0d4d22ff057142073c8710cb24ed1a5f6a5c346b', 'unsorted_detail_body': 'bdfe6d2d03ab6d51c4e4fa5adcfa879f6d51e8e1ebedbf7a0a73894b974da5ee', 'unsorted_stats_body': '6e4a0c485fb11efde024268e193f53b8fe590a9753733e4b60049913dbc4555c'}, 'assignments': {'assigned': 'd95bf439085ce2ba9b6d3ad6faa05756473012d4128a6e26d54c90aadde3398d', 'outside': '24488dab515bbff9fdca3b1b8b50af09947e3322ac3d5b2dc4286e2a51ad2b45'}, 'bootstrap': 'a4596530877c4d12be8972223b0066a1ef63c7f1a33e126b24d1028d65081f08'}
PRE_EXTRACTION_ROUTE_BODY_SHA256 = {'_is_public_student_request': '87075039c5d14db9777404d6b136a440ce37498ea564c768a7a211e28cd8a4c8', '_academy_request_allowed': '54566031d34edad1daf64321418c5d1d28e5a83b5f6e89568ac28445b9438216', '_public_session_available': '710a1450483259938cbfb62b0b82e9e5beffdf953665fa261fef9e6a6853f396', '_tests_config_lock': 'cae7a142896749785dfc7c82d64fc2cfea937217577aacddc6e92abf95afb5bc', 'get_tests_config': 'e0ff83fe52317516d3e69723692b586f5d097a7e37d15da4c899ed424d84878a', '_load_tests_cfg': '0c28e8ab1b8a99a9a2c5ce55a666da23e341304dab6dc1a223ecfa36bcd998f7', '_admin_test_answer_url': 'ac3ba621483990193a368858219ea2ffa1712be501d16391c5626d37a0b49fdc', '_test_record_file_signature': 'e64da94847d84a215251e222152375098b740f146baa8bb688363019ee6b9ec2', '_legacy_test_record_candidates': '6221e56a535a8b9a12a3d3a1bd640c5118af3e413de77d726e4de3dd87312590', 'post_tests_config': '855c1e0ec26207a75bdf507b8cefa889e0ccc4c7e56ba089192758207413b0c7', 'patch_tests_config_test': '096236b712e8cbf78accd9bd0a87bc2d628de42d5badad9fcfdb6fac1c74291b', '_handle_quick_printer_export': '662176f910aebb658d7b8f644680e9f1c298f56a0aad6564e687d2bca414fc7a'}

def verify_pure_boundaries(source_root):
    allowed = {'__future__', 'copy', 'datetime', 're', 'statistics', 'typing', 'core.progress_rules', 'core.test_answer_links', 'core.update_assignment_rules', 'core.test_record_projection'}
    checked = 0
    for name, expected in PRE_EXTRACTION_BODY_SHA256.items():
        path = source_root / ('core/' + name + '.py')
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all((alias.name in allowed for alias in node.names)), (name, node)
            elif isinstance(node, ast.ImportFrom):
                assert node.module in allowed, (name, node.module)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {'open', 'eval', 'exec', '__import__'}, (name, node.func.id)
        actual = functions(path)
        for function_name, expected_hash in expected.items():
            assert function_body_sha256(actual[function_name]) == expected_hash, function_name
            checked += 1
    route_functions = functions(source_root / 'routes/api_tests.py')
    for name, expected_hash in PRE_EXTRACTION_ROUTE_BODY_SHA256.items():
        assert function_body_sha256(route_functions[name]) == expected_hash, name
    return checked

def pure_literal_matrix():
    from core import test_record_projection as records
    from core import test_statistics_projection as statistics
    catalog = records.build_test_catalog(CONFIG)
    snap = {'name': LABEL, 'test_id': 'unit-r2', 'meta': {'curriculum': '과거과목', 'term': 'MID', 'test_level': 0, 'source_id': 'past-source'}}
    result = records.record_meta(snap, catalog)
    assert result == {'type': 'UNIT', 'curriculum': '과거과목', 'test_name': NAME, 'unit_name': '다항식', 'test_level': 0, 'difficulty': '', 'term': '중간고사', 'round': '2', 'source_id': 'past-source'}
    assert records.parse_record_date('bad-date') is None
    assert records._normalize_wrong_numbers([' 2 ', '2', 0, -1, 'x']) == [2, 2]
    assert records._parse_answer_spec('1. A\n3. B', 4) == ['A', '', 'B', '']
    assert records._parse_answer_spec('1342', 4) == ['1', '3', '4', '2']
    assert records._parse_answer_spec('1, 3, 4, 2', 4) == ['1', '3', '4', '2']
    assert records._submitted_answers_from_record({'submittedAnswers': ['A', ' B ']}, 3) == ['A', 'B', '']
    assert records._get_answer_key_for_round({'answerKeys': {'2': [' A ', 'B']}}, 3, 2) == ['A', 'B', '']
    assert records._get_answer_key_for_round({'answers': '1 2'}, 3, 9) == ['1', '2', '']
    assert records._meta_matches_target({'test_name': NAME, 'term': 'MID'}, {'test_name': NAME, 'term': '중간고사'}) is True
    assert records._meta_matches_target({'test_name': NAME, 'round': '1'}, {'test_name': NAME, 'round': '2'}) is False
    assert [statistics._score_bucket(value) for value in [0, 49.99, 50, 59.99, 60, 69.99, 70, 79.99, 80, 89.99, 90, 100]] == ['0-49', '0-49', '50-59', '50-59', '60-69', '60-69', '70-79', '70-79', '80-89', '80-89', '90-100', '90-100']
    data = [{'sid': 'unknown', 'test_id': '', 'name': 'FINAL / 끝', 'correct': 1, 'total': 4, 'wrong': [1, 1], 'meta': {}, 'memo': '', 'created_at': '', 'day': dt.date(2026, 10, 1)}, {'sid': 'unknown', 'test_id': '', 'name': 'HELL / 끝', 'correct': 3, 'total': 4, 'wrong': [], 'meta': {}, 'memo': '', 'created_at': '', 'day': dt.date(2026, 10, 1)}]
    before = digest(data)
    projected = statistics.project_test_statistics(iter(data), {}, [], start=dt.date(2026, 10, 1), end=dt.date(2026, 10, 1), include_wrong=True)
    assert projected['by_test']['끝']['wrong_freq'] == {'1': 2}
    assert projected['by_test']['끝']['avg_pct'] == 50.0
    assert projected['by_test']['끝']['p90_pct'] == 25.0
    assert list(projected['summary']) == ['FINAL', 'HELL']
    assert [row['type'] for row in projected['final_rows']] == ['FINAL']
    assert [row['type'] for row in projected['hell_rows']] == ['HELL']
    assert digest(data) == before
    route = sys.modules['routes._test_projection_current']
    assert route._find_test_def_by_id(CONFIG, 'unit-r2') == CONFIG['categories']['UNIT']['tests'][0]
    assert route._get_answer_key_for_round(route._find_test_def_by_id(CONFIG, 'unit-r2'), 4, 2) == ['1', '3', '4', '2']
    return 21

def checked_bootstrap_assignment_bridge(source_root):
    from core import student_test_projection
    owner = source_root / 'routes/api_basic.py'
    tree = ast.parse(owner.read_text(encoding='utf-8-sig'))
    imported = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == 'core.student_test_projection':
            for name in node.names:
                imported[name.asname or name.name] = name.name
    actual_functions = functions(owner)
    bridge = actual_functions['_student_assigned_tests_for_date']
    calls = {imported.get(node.func.id) for node in ast.walk(bridge) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert {'project_student_assigned_tests', 'resolve_student_assigned_tests'}.issubset(calls), 'Hub must wire api_basic assigned_tests to the new pure project/resolve stages'
    factory = actual_functions['create_student_bootstrap_projection_dependencies']
    assert any((keyword.arg == 'assigned_tests' and isinstance(keyword.value, ast.Name) and (keyword.value.id == bridge.name) for node in ast.walk(factory) if isinstance(node, ast.Call) for keyword in node.keywords)), 'dependency factory must use the verified bridge'
    observations = []

    def config_source():
        observations.append('config')
        return CONFIG

    def map_source():
        observations.append('map')
        return LINK_MAP
    scope = {name: getattr(student_test_projection, original) for name, original in imported.items()}
    scope.update(_load_tests_config_for_answer_links=config_source, _load_test_answer_link_map=map_source)
    node = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), bridge], type_ignores=[])
    exec(compile(ast.fix_missing_locations(node), 'actual-bootstrap-assignment-bridge', 'exec'), scope)
    build = scope[bridge.name]
    progress, logs, expected = assignment_fixture()
    assert build(progress, logs, TODAY, '007', {}) == expected
    assert observations == ['config', 'map'] * 3, 'preserve the existing per-item config then map loader/cache calls'
    observations.clear()
    assert build({TODAY: {'7': {'__testsClearedAt': 'stamp'}}}, logs, TODAY, '7', logs) == []
    assert observations == [], 'cleared/inactive assignments must not load answer sources'
    return build

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repository-root', type=Path, default=ROOT)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--baseline-root', type=Path)
    parser.add_argument('--before', action='store_true')
    parser.add_argument('--require-bootstrap-wiring', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='test-projection-runtime-') as raw:
        root = Path(raw)
        sys.path.insert(0, str(args.repository_root))
        runtime(root)
        original = original_assignments(args.baseline_root or args.source_root) if args.before or args.baseline_root else None
        build = None
        filter_curriculum = None
        from core.network_access import strip_answer_link_fields
        restrict_node = functions((args.baseline_root or args.repository_root) / 'routes/api_basic.py')['_academy_restricted_assigned_tests']
        restrict_scope = {'strip_answer_link_fields': strip_answer_link_fields}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[restrict_node], type_ignores=[])), 'academy-restriction', 'exec'), restrict_scope)
        restrict = restrict_scope['_academy_restricted_assigned_tests']
        if original:
            build = original['_student_assigned_tests_for_date']
            filter_curriculum = original['_filter_assigned_tests_for_student_curriculum']
        if not args.before:
            for name in ('test_record_projection', 'test_statistics_projection', 'student_test_projection'):
                module_from(args.source_root / ('core/' + name + '.py'), 'core.' + name)
            from core.student_test_projection import project_student_assigned_tests, resolve_student_assigned_tests, filter_assigned_tests_for_student_curriculum
            build = lambda progress, logs, date, sid, fallback: resolve_student_assigned_tests(project_student_assigned_tests(progress, logs, date, sid, fallback), tests_config=CONFIG, answer_link_map=LINK_MAP)
            filter_curriculum = filter_assigned_tests_for_student_curriculum
            if args.require_bootstrap_wiring:
                build = checked_bootstrap_assignment_bridge(args.source_root)
        result = {'routes': routes(args.source_root, root, 'current'), 'assignments': assignments(build, filter_curriculum, restrict), 'bootstrap': bootstrap(args.source_root, build, filter_curriculum, restrict, 'current'), 'body_hashes': hashes(args.baseline_root or args.source_root) if args.before or args.baseline_root else PRE_EXTRACTION_BODY_SHA256}
        for key, expected in PRE_EXTRACTION_PAYLOAD_SHA256.items():
            if key == 'routes':
                assert {name: result[key][name] for name in expected} == expected
            else:
                assert result[key] == expected
        if not args.before:
            result['unchangedPureBodies'] = verify_pure_boundaries(args.source_root)
            result['pureLiteralMatrix'] = pure_literal_matrix()
        if args.baseline_root and (not args.before):
            old = original['_student_assigned_tests_for_date']
            old_filter = original['_filter_assigned_tests_for_student_curriculum']
            assert result['routes'] == routes(args.baseline_root, root, 'before')
            assert result['assignments'] == assignments(old, old_filter, restrict)
            assert result['bootstrap'] == bootstrap(args.baseline_root, old, old_filter, restrict, 'before')
            current = hashes(args.source_root)
            before = hashes(args.baseline_root)
            for name in ('post_tests_config', 'patch_tests_config_test', 'get_tests_config', '_tests_config_lock', '_handle_quick_printer_export'):
                assert current['routes/api_tests.py'][name] == before['routes/api_tests.py'][name], name + ' protected function changed'
        if args.report:
            assert args.report.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
            args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        summary = {'ok': True, 'phase': 'before' if args.before else 'after', **{k: result[k] for k in ('routes', 'assignments', 'bootstrap')}}
        if not args.before:
            summary.update(unchangedPureBodies=result['unchangedPureBodies'], protectedRouteBodies=len(PRE_EXTRACTION_ROUTE_BODY_SHA256), pureLiteralMatrix=result['pureLiteralMatrix'], bootstrapWiringChecked=args.require_bootstrap_wiring)
        print(json.dumps(summary, ensure_ascii=True))
    return 0
if __name__ == '__main__':
    raise SystemExit(main())
