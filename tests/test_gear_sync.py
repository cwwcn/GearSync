import builtins
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

import gear_sync
import sync_cli
from coros.coros_client import CorosClient
from db.sync_state import SyncState
from garmin_cn_to_coros import main as sync_to_coros
from sync_types import Activity, ObjectUpload
from tests.test_sync_engine import fit, list_adapter


class GearSyncRoutingTests(unittest.TestCase):
    def setUp(self):
        sleep_patch = patch('sync_engine.time.sleep')
        sleep_patch.start()
        self.addCleanup(sleep_patch.stop)

    def test_all_supported_directions_route_to_the_existing_entry_modules(self):
        expected_routes = {
            ("COROS", "GARMIN_GLOBAL"): "coros_to_garmin_global",
            ("GARMIN_GLOBAL", "COROS"): "garmin_global_to_coros",
            ("COROS", "GARMIN_CN"): "coros_to_garmin_cn",
            ("GARMIN_CN", "COROS"): "garmin_cn_to_coros",
            ("GARMIN_GLOBAL", "GARMIN_CN"): "garmin_global_to_garmin_cn",
            ("GARMIN_CN", "GARMIN_GLOBAL"): "garmin_cn_to_garmin_global",
        }
        self.assertEqual(expected_routes, gear_sync.SYNC_MAP)

        real_import = builtins.__import__
        for (source, target), module_name in expected_routes.items():
            with self.subTest(source=source, target=target):
                module_main = Mock()
                fake_module = SimpleNamespace(main=module_main)

                def import_for_route(name, *args, **kwargs):
                    if name == module_name:
                        return fake_module
                    return real_import(name, *args, **kwargs)

                with patch.dict(
                    gear_sync.SYNC_CONFIG,
                    {"SOURCE": source.lower(), "TARGET": target.lower()},
                    clear=True,
                ), patch("builtins.__import__", side_effect=import_for_route):
                    module_main.return_value = 1
                    self.assertEqual(1, gear_sync.main())

                module_main.assert_called_once_with()

    def test_missing_source_or_target_does_not_start_a_sync_module(self):
        with patch.dict(
            gear_sync.SYNC_CONFIG, {"SOURCE": "", "TARGET": "GARMIN_CN"}, clear=True
        ), patch("builtins.__import__") as import_mock:
            self.assertEqual(2, gear_sync.main())
        import_mock.assert_not_called()

        with patch.dict(
            gear_sync.SYNC_CONFIG, {"SOURCE": "COROS", "TARGET": ""}, clear=True
        ), patch("builtins.__import__") as import_mock:
            self.assertEqual(2, gear_sync.main())
        import_mock.assert_not_called()

    def test_unsupported_direction_does_not_import_a_sync_module(self):
        with patch.dict(
            gear_sync.SYNC_CONFIG,
            {"SOURCE": "COROS", "TARGET": "COROS"},
            clear=True,
        ), patch("builtins.__import__") as import_mock:
            self.assertEqual(2, gear_sync.main())
        import_mock.assert_not_called()

    def test_fixed_entrypoints_propagate_exit_status_in_process(self):
        script_dir = Path(gear_sync.__file__).parent
        source = '''
import runpy
import sys
from types import ModuleType
entry = sys.argv[1]
runner = ModuleType('sync_cli')
runner.run_direction = lambda source, target: int(sys.argv[2])
sys.modules['sync_cli'] = runner
runpy.run_path(entry, run_name='__main__')
'''
        for module_name in ('garmin_cn_to_coros', 'garmin_global_to_coros'):
            for status in (0, 1, 2):
                with self.subTest(module=module_name, status=status):
                    result = subprocess.run([sys.executable, '-c', source, str(script_dir / f'{module_name}.py'),
                                             str(status)], check=False, timeout=5, capture_output=True)
                    self.assertEqual(status, result.returncode, result.stderr.decode())

    def test_fixed_coros_route_does_not_repeat_post_when_previous_response_was_html(self):
        activity = Activity('21', 1700000000000)
        source = SimpleNamespace(account_id=lambda: 'cn-account', list_page=list_adapter([activity]),
                                 download_activity=Mock(return_value=fit()))
        coros = CorosClient('fixture@example.test', 'fixture-password')
        coros.accessToken = 'dummy-session'
        coros.userId = 'coros-account'
        coros.regionId = 2
        coros.teamapi = 'https://teamcnapi.coros.com'
        coros.req = Mock()
        page = {'result': '0000', 'data': {'dataList': []}}
        coros.req.request.side_effect = lambda method, url, **kwargs: (
            SimpleNamespace(status=502, data=b'<html>gateway</html>') if method == 'POST'
            else SimpleNamespace(status=200, data=json.dumps(page).encode())
        )
        coros.upload_object = Mock(return_value=ObjectUpload('fit_zip/test/key.zip', 'bucket', 'aliyun', 'md5', 123))
        with tempfile.TemporaryDirectory() as directory, patch.object(sync_cli, 'DB_DIR', directory), patch.dict(
            sync_cli.FACTORIES, {'GARMIN_CN': lambda logger: source, 'COROS': lambda logger: coros}, clear=True,
        ), patch.dict(sync_cli.SYNC_CONFIG, {}, clear=True), patch.dict(sync_cli.NOTIFY_CONFIG, {}, clear=True):
            self.assertEqual(1, sync_to_coros())
            self.assertEqual(1, sync_to_coros())
            state = SyncState(Path(directory) / 'activitySync.db', 'GARMIN_CN', 'cn-account', 'COROS', '2:coros-account')
            self.assertEqual('submitting', state.transfer('21')['phase'])
        coros.upload_object.assert_called_once()
        methods = [call.args[0] for call in coros.req.request.call_args_list]
        self.assertEqual('POST', methods[0])
        self.assertEqual(1, methods.count('POST'))
        self.assertTrue(all(method == 'GET' for method in methods[1:]))

    def test_single_activity_coros_route_reconciles_visible_target_and_then_skips_it(self):
        activity = Activity('21', 1700000000000)
        source_fit = fit()
        source = SimpleNamespace(account_id=lambda: 'cn-account', list_page=list_adapter([activity]),
                                 download_activity=Mock(return_value=source_fit))
        coros = CorosClient('fixture@example.test', 'unused')
        coros.accessToken, coros.userId, coros.regionId = 'fixture-token', 'coros-account', 2
        coros.teamapi = 'https://teamcnapi.coros.com'
        coros.req = Mock()
        coros.upload_object = Mock(return_value=ObjectUpload('fit_zip/test/key.zip', 'bucket', 'aliyun', 'md5', 123))
        files = []

        def request(method, url, **kwargs):
            parsed = urlsplit(url)
            route = (method, parsed.path)
            if route == ('POST', '/activity/fit/import'):
                files.append({'labelId': '51', 'sportType': 100, 'startTime': activity.start_ms // 1000})
                payload = {'status': 2}
            elif route == ('GET', '/activity/query'):
                payload = {'dataList': files if 'pageNumber=1&' in parsed.query else []}
            elif route == ('POST', '/activity/detail/download'):
                payload = {'fileUrl': 'https://storage.example.test/fixture.fit'}
            elif route == ('GET', '/fixture.fit'):
                result = Mock(status=200)
                result.read.return_value = source_fit
                return result
            else:
                self.fail(f'Unexpected offline fixture request: {route}')
            return SimpleNamespace(status=200, data=json.dumps({'result': '0000', 'data': payload}).encode())

        coros.req.request.side_effect = request
        with tempfile.TemporaryDirectory() as directory, patch.object(sync_cli, 'DB_DIR', directory), patch.dict(
            sync_cli.FACTORIES, {'GARMIN_CN': lambda logger: source, 'COROS': lambda logger: coros}, clear=True,
        ), patch.dict(sync_cli.SYNC_CONFIG, {'SYNC_ACTIVITY_ID': '21'}, clear=True):
            self.assertEqual(0, sync_to_coros())
            state = SyncState(Path(directory) / 'activitySync.db', 'GARMIN_CN', 'cn-account', 'COROS', '2:coros-account')
            self.assertEqual('', state.transfer('21')['task_id'])
            self.assertEqual('done', state.transfer('21')['phase'])
            self.assertEqual('51', state.transfer('21')['remote_id'])

            requests_before_rerun = coros.req.request.call_count
            self.assertEqual(0, sync_to_coros())
            self.assertEqual(requests_before_rerun, coros.req.request.call_count)

        self.assertEqual(['51'], [item['labelId'] for item in files])
        coros.upload_object.assert_called_once()
        source.download_activity.assert_called_once_with(activity)


if __name__ == "__main__":
    unittest.main()
