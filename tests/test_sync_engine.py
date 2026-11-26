import io
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import sync_engine
from activity_files import ActivityCache, decode_activity, fit_crc
from db.activity_db import ActivityDB
from db.sync_state import SyncState
from sync_engine import OVERLAP_MS, RECONCILE_DELAYS, RunResult, parse_cutoff, scan, sync_activities
from sync_types import Activity, ObjectUpload, Receipt, Rejected, SyncError


NOW = 1800000000
STAMP = NOW * 1000 - 10000


def fit(content=b'example payload'):
    body = b'\x0c\x10\x00\x00' + len(content).to_bytes(4, 'little') + b'.FIT' + content
    return body + fit_crc(body).to_bytes(2, 'little')


def archive(**members):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as zipped:
        for name, data in members.items():
            zipped.writestr(name, data)
    return output.getvalue()


def list_adapter(*pages):
    return Mock(side_effect=lambda page, size: pages[page] if page < len(pages) else [])


class SyncEngineTests(unittest.TestCase):
    def setUp(self):
        sleep_patch = patch('sync_engine.time.sleep')
        self.sleep = sleep_patch.start()
        self.addCleanup(sleep_patch.stop)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.db = self.root / 'activities.db'
        self.activity = Activity('1001', STAMP)
        self.source = SimpleNamespace(list_page=list_adapter([self.activity]), download_activity=Mock(return_value=fit()))
        self.target = SimpleNamespace(list_page=list_adapter(), download_activity=Mock(return_value=fit()),
                                      upload_object=Mock(return_value=ObjectUpload('key', 'bucket', 'aliyun', 'md5', 100)),
                                      submit_import=Mock(return_value=Receipt(remote_id='2001')),
                                      lookup_import=Mock(return_value=''), upload_activity=Mock(return_value=Receipt()))
        self.state = self.open_state()

    def open_state(self, platform='GARMIN_CN', account='source-1', target='COROS'):
        return SyncState(self.db, platform, account, target, 'target-1')

    def run_sync(self, *, coros=True, only_id='', cutoff=0):
        return sync_activities(self.source, self.target, coros, self.state, self.root / 'cache', cutoff,
                               only_id=only_id, now=NOW)

    def test_coros_oss_failure_remains_pending_and_does_not_block_next_item(self):
        next_item = Activity('1002', STAMP + 1)
        self.source.list_page = list_adapter([next_item, self.activity])
        self.target.upload_object.side_effect = [TimeoutError(), self.target.upload_object.return_value]
        for platform in ('GARMIN_CN', 'GARMIN_GLOBAL'):
            with self.subTest(platform=platform):
                self.state = self.open_state(platform)
                self.target.upload_object.side_effect = [TimeoutError(), self.target.upload_object.return_value]
                self.target.submit_import.reset_mock()
                self.assertEqual(RunResult(done=1, failed=1), self.run_sync())
                self.assertEqual('pending', self.state.transfer('1001')['phase'])
                self.assertEqual('done', self.state.transfer('1002')['phase'])
                self.target.submit_import.assert_called_once()

    def test_network_timeout_after_remote_acceptance_reconciles_without_replay(self):
        self.target.submit_import.side_effect = SyncError('Network timeout after commit')
        self.assertEqual(RunResult(failed=1), self.run_sync())
        self.assertEqual('submitting', self.state.transfer(self.activity.id)['phase'])
        self.target.list_page = list_adapter([Activity('2001', STAMP, '1')])
        self.state = self.open_state()
        self.assertEqual(RunResult(done=1), self.run_sync())
        self.assertEqual('2001', self.state.transfer(self.activity.id)['remote_id'])
        self.target.submit_import.assert_called_once()
        self.target.upload_object.assert_called_once()

    def test_accepted_persists_task_id_and_queries_it_first_after_restart(self):
        self.target.submit_import.return_value = Receipt('301')
        self.assertEqual(RunResult(waiting=1), self.run_sync())
        row = self.state.transfer(self.activity.id)
        self.assertEqual(('accepted', '301', 'key'), (row['phase'], row['task_id'], row['object_key']))
        self.assertEqual(len(RECONCILE_DELAYS), self.target.lookup_import.call_count)
        self.assertEqual([call(delay) for delay in RECONCILE_DELAYS if delay], self.sleep.call_args_list)
        self.target.lookup_import.reset_mock()
        self.target.list_page.reset_mock()
        self.state = self.open_state()
        self.target.lookup_import.return_value = '2001'
        self.assertEqual(RunResult(done=1), self.run_sync())
        self.target.lookup_import.assert_called_once_with('301')
        self.target.list_page.assert_not_called()
        self.target.submit_import.assert_called_once()

    def test_accepted_without_task_id_confirms_in_the_same_run_for_both_targets(self):
        for coros in (True, False):
            with self.subTest(coros=coros):
                self.sleep.reset_mock()
                self.state = self.open_state(target='COROS' if coros else 'GARMIN_GLOBAL')
                self.target.submit_import.return_value = Receipt()
                self.target.upload_activity.return_value = Receipt()
                self.target.list_page = list_adapter([Activity('2001', STAMP)])
                self.assertEqual(RunResult(done=1), self.run_sync(coros=coros))
                row = self.state.transfer(self.activity.id)
                self.assertEqual(('done', '2001'), (row['phase'], row['remote_id']))
                self.assertEqual(RunResult(), self.run_sync(coros=coros))
                self.sleep.assert_called_once_with(5)
        self.target.submit_import.assert_called_once()
        self.target.upload_activity.assert_called_once()

    def test_delayed_target_visibility_is_confirmed_without_a_second_run_or_post(self):
        self.target.submit_import.return_value = Receipt()
        queries = 0

        def delayed_page(page, size):
            nonlocal queries
            if page:
                return []
            queries += 1
            return [Activity('2001', STAMP)] if queries >= 3 else []

        self.target.list_page.side_effect = delayed_page
        self.assertEqual(RunResult(done=1), self.run_sync())
        self.assertEqual([call(5)] * 3, self.sleep.call_args_list)
        self.assertEqual('2001', self.state.transfer(self.activity.id)['remote_id'])
        self.target.submit_import.assert_called_once()
        self.target.upload_object.assert_called_once()

    def test_task_receipt_confirms_on_retry_without_a_second_import(self):
        self.target.submit_import.return_value = Receipt('301')
        self.target.lookup_import.side_effect = ['', '2001']
        self.assertEqual(RunResult(done=1), self.run_sync())
        self.assertEqual([call('301'), call('301')], self.target.lookup_import.call_args_list)
        self.assertEqual([call(5)] * 2, self.sleep.call_args_list)
        self.target.list_page.assert_called_once()
        self.target.submit_import.assert_called_once()

    def test_submit_timeout_can_be_confirmed_in_the_same_run_without_reposting(self):
        self.target.submit_import.side_effect = SyncError('Network timeout after commit')
        self.target.list_page = list_adapter([Activity('2001', STAMP)])
        self.assertEqual(RunResult(done=1), self.run_sync())
        self.assertEqual('done', self.state.transfer(self.activity.id)['phase'])
        self.target.submit_import.assert_called_once()
        self.sleep.assert_called_once_with(5)

    def test_first_confirmation_waits_five_seconds_before_querying(self):
        self.target.submit_import.return_value = Receipt('301')

        def lookup_after_wait(task_id):
            self.sleep.assert_called_once_with(5)
            return '2001'

        self.target.lookup_import.side_effect = lookup_after_wait
        self.assertEqual(RunResult(done=1), self.run_sync())
        self.target.lookup_import.assert_called_once_with('301')
        self.target.submit_import.assert_called_once()
        self.sleep.assert_called_once_with(5)

    def test_completed_receipt_does_not_wait_or_query(self):
        self.assertEqual(RunResult(done=1), self.run_sync())
        self.sleep.assert_not_called()
        self.target.lookup_import.assert_not_called()
        self.target.list_page.assert_not_called()
        self.target.submit_import.assert_called_once()

    def test_target_read_failure_retries_without_reposting_and_allows_next_item(self):
        next_item = Activity('1002', STAMP + 1)
        self.source.list_page = list_adapter([next_item, self.activity])
        self.target.submit_import.side_effect = [Receipt('301'), Receipt(remote_id='2002')]
        self.target.lookup_import.side_effect = SyncError('HTTP 502')
        self.target.list_page.side_effect = SyncError('HTTP 502')
        self.assertEqual(RunResult(done=1, waiting=1), self.run_sync())
        self.assertEqual('accepted', self.state.transfer(self.activity.id)['phase'])
        self.assertEqual('done', self.state.transfer(next_item.id)['phase'])
        self.assertEqual(len(RECONCILE_DELAYS), self.target.lookup_import.call_count)
        self.assertEqual(2, self.target.submit_import.call_count)

    def test_interrupted_polling_keeps_receipt_for_restart_without_reposting(self):
        self.target.submit_import.return_value = Receipt('301')
        self.sleep.side_effect = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.run_sync()
        row = self.state.transfer(self.activity.id)
        self.assertEqual(('accepted', '301'), (row['phase'], row['task_id']))
        self.sleep.side_effect = None
        self.target.lookup_import.return_value = '2001'
        self.assertEqual(RunResult(done=1), self.run_sync())
        self.target.submit_import.assert_called_once()

    def test_confirmation_write_failure_preserves_target_id_for_restart(self):
        self.target.submit_import.return_value = Receipt('301')
        self.target.lookup_import.return_value = '2001'
        record = self.state.record

        def failing_record(activity_id, phase, **kwargs):
            if phase == 'done':
                raise SyncError('fixture database write failed')
            return record(activity_id, phase, **kwargs)

        with patch.object(self.state, 'record', side_effect=failing_record):
            self.assertEqual(RunResult(failed=1), self.run_sync())
        row = self.state.transfer(self.activity.id)
        self.assertEqual(('accepted', '2001'), (row['phase'], row['remote_id']))
        self.target.lookup_import.reset_mock()
        self.assertEqual(RunResult(done=1), self.run_sync())
        self.target.lookup_import.assert_not_called()
        self.target.submit_import.assert_called_once()

    def test_database_write_failure_after_remote_completion_does_not_replay(self):
        record = self.state.record

        def failing_record(activity_id, phase, **kwargs):
            if phase == 'done':
                raise SyncError('fixture database write failed')
            return record(activity_id, phase, **kwargs)

        with patch.object(self.state, 'record', side_effect=failing_record):
            self.assertEqual(RunResult(failed=1), self.run_sync())
        self.assertEqual(('accepted', '2001'), (
            self.state.transfer(self.activity.id)['phase'], self.state.transfer(self.activity.id)['remote_id'],
        ))
        self.state = self.open_state()
        self.assertEqual(RunResult(done=1), self.run_sync())
        self.target.list_page.assert_not_called()
        self.target.submit_import.assert_called_once()

    def test_completed_run_does_not_send_again(self):
        self.assertEqual(RunResult(done=1), self.run_sync())
        self.assertEqual(RunResult(), self.run_sync())
        self.target.submit_import.assert_called_once()

    def test_resume_after_completed_storage_does_not_reupload_the_object(self):
        record = self.state.record

        def stop_before_import(activity_id, phase, **kwargs):
            if phase == 'submitting':
                raise KeyboardInterrupt()
            record(activity_id, phase, **kwargs)

        source_zip = archive(**{'activity.fit': fit()})
        self.source.download_activity.return_value = source_zip
        with patch.object(self.state, 'record', side_effect=stop_before_import), self.assertRaises(KeyboardInterrupt):
            self.run_sync()
        row = self.state.transfer(self.activity.id)
        self.assertEqual('storage_ready', row['phase'])
        self.assertNotEqual(row['original_hash'], row['file_hash'])
        self.target.submit_import.assert_not_called()
        self.state = self.open_state()
        self.assertEqual(RunResult(done=1), self.run_sync())
        self.target.upload_object.assert_called_once()

    def test_unmatched_or_ambiguous_activity_never_replays(self):
        self.target.upload_activity.return_value = Receipt('301')
        self.assertEqual(RunResult(waiting=1), self.run_sync(coros=False))
        self.target.list_page = list_adapter([Activity('2002', STAMP), Activity('2001', STAMP)])
        self.assertEqual(RunResult(waiting=1), self.run_sync(coros=False))
        self.target.upload_activity.assert_called_once()
        self.target.download_activity.return_value = fit(b'different content')
        self.assertEqual(RunResult(waiting=1), self.run_sync(coros=False))

    def test_conclusive_rejection_can_retry_but_unknown_result_cannot(self):
        self.target.submit_import.side_effect = [Rejected('HTTP 401'), Receipt(remote_id='20')]
        self.assertEqual(RunResult(failed=1), self.run_sync())
        self.assertEqual('pending', self.state.transfer(self.activity.id)['phase'])
        self.assertEqual(RunResult(done=1), self.run_sync())

    def test_incremental_scan_preserves_old_backlog_and_ignores_out_of_window_files(self):
        older = Activity('200', STAMP - OVERLAP_MS - 1)
        backlog = Activity('333', STAMP - OVERLAP_MS * 2)
        self.state.discover([backlog], cutoff=0, watermark=STAMP, full_scan_at=NOW - 100)
        self.source.list_page = list_adapter([self.activity], [older], [Activity('201', older.start_ms - 1)])
        self.assertEqual(RunResult(done=2), self.run_sync())
        self.assertIsNone(self.state.transfer(older.id))
        self.assertEqual(['333', '1001'], [call.args[0].id for call in self.source.download_activity.call_args_list])

    def test_failed_discovery_does_not_advance_checkpoint_or_drop_queue(self):
        self.state.discover([self.activity], cutoff=0, watermark=STAMP, full_scan_at=NOW - 100)
        self.source.list_page.side_effect = SyncError('HTTP 401')
        self.assertEqual(RunResult(done=1, failed=1), self.run_sync())
        self.assertEqual(NOW - 100, self.state.checkpoint()['full_scan_at'])

    def test_overlapping_scan_keeps_discovered_items_without_overwriting_new_checkpoint(self):
        previous = self.state.checkpoint()
        self.open_state().discover([self.activity], cutoff=0, watermark=STAMP, full_scan_at=NOW,
                                   checkpoint=previous)
        older = Activity('1002', STAMP - 1)
        self.state.discover([older], cutoff=1, watermark=older.start_ms, full_scan_at=NOW - 10,
                            checkpoint=previous)
        checkpoint = self.state.checkpoint()
        self.assertEqual((0, STAMP, NOW), (checkpoint['cutoff'], checkpoint['watermark'], checkpoint['full_scan_at']))
        self.assertEqual('pending', self.state.transfer(older.id)['phase'])

    def test_single_item_does_not_process_unrelated_pending_rows(self):
        backlog = Activity('333', STAMP - OVERLAP_MS * 2)
        self.state.discover([backlog])
        self.assertEqual(RunResult(done=1), self.run_sync(only_id=self.activity.id))
        self.assertIsNone(self.state.checkpoint()['watermark'])
        self.assertEqual('pending', self.state.transfer(backlog.id)['phase'])

    def test_legacy_done_is_kept_and_legacy_uncertain_not_replayed_or_copied_to_other_accounts(self):
        legacy = ActivityDB(str(self.db))
        legacy.initDB()
        for identity in ('1001', '1002'):
            legacy.saveActivity(identity, 'GARMIN_CN', 'COROS')
        legacy.updateSyncStatus('1001', 'GARMIN_CN', 'COROS')
        legacy.updateExceptionSyncStatus('1002', 'GARMIN_CN', 'COROS')
        self.state = self.open_state()
        self.assertEqual('done', self.state.transfer('1001')['phase'])
        self.assertEqual('legacy_review', self.state.transfer('1002')['phase'])
        self.assertEqual(RunResult(waiting=1), self.run_sync())
        self.target.submit_import.assert_not_called()
        self.assertIsNone(self.open_state(account='different').transfer('1001'))
        with sqlite3.connect(self.db) as connection:
            self.assertEqual([(1,), (2,)], connection.execute('SELECT is_sync FROM activity_table ORDER BY id').fetchall())


class SyncGuardTests(unittest.TestCase):
    def test_time_zone_is_explicit_at_midnight(self):
        self.assertEqual(8 * 60 * 60 * 1000, parse_cutoff('20261118', 'UTC') - parse_cutoff('20261118'))

    def test_activity_claims_allow_distinct_activities_and_exclude_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            state = SyncState(Path(directory) / 'activitySync.db', 'GARMIN_CN', 'one', 'COROS', 'two')
            with state.claim('1001') as first_claim:
                self.assertTrue(first_claim)
                with state.claim('1001') as duplicate_claim:
                    self.assertFalse(duplicate_claim)
                with state.claim('1002') as independent_claim:
                    self.assertTrue(independent_claim)

    def test_activity_claim_is_exclusive_across_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'activitySync.db'
            state = SyncState(database, 'GARMIN_CN', 'one', 'COROS', 'two')
            script = '''
import sys
from db.sync_state import SyncState
state = SyncState(sys.argv[1], 'GARMIN_CN', 'one', 'COROS', 'two')
with state.claim('1001') as claimed:
    print(int(claimed))
'''
            environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'scripts'))
            with state.claim('1001') as first_claim:
                self.assertTrue(first_claim)
                result = subprocess.run([sys.executable, '-c', script, str(database)], check=True,
                                        capture_output=True, text=True, env=environment, timeout=5)
            self.assertEqual('0', result.stdout.strip())

    def test_six_directions_each_run_two_activities_concurrently(self):
        from gear_sync import SYNC_MAP

        worker = '''
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

directory, source, target = sys.argv[1:]
sys.argv[1:] = []
import sync_cli
from sync_types import Activity, ObjectUpload, Receipt
from tests.test_sync_engine import STAMP, fit

root = Path(directory)
activities = [Activity('1002', STAMP + 1, '1'), Activity('1001', STAMP, '1')]

def reach(stage, identity):
    markers = root / stage
    with (markers / identity).open('x'):
        pass
    deadline = time.monotonic() + 15
    while len(list(markers.iterdir())) < 12:
        if time.monotonic() >= deadline:
            raise AssertionError(f'All twelve CLI runs must reach {stage} concurrently')
        time.sleep(0.02)

def list_page(page, size):
    if page:
        return []
    reach('scans', str(os.getpid()))
    return activities

def submit(activity_id):
    reach('submissions', f'{source}-{target}-{activity_id}')
    return Receipt(remote_id=f'2{activity_id}')

source_client = SimpleNamespace(account_id=lambda: source, list_page=list_page,
                                download_activity=lambda activity: fit())
target_client = SimpleNamespace(account_id=lambda: target,
                                upload_activity=lambda path: submit(path.stem),
                                upload_object=lambda path: ObjectUpload(path.stem, 'bucket', 'aliyun', 'md5', 100),
                                submit_import=lambda uploaded, activity: submit(activity.id))
with patch('socket.socket.connect', side_effect=AssertionError('offline test')), patch.object(
    sync_cli, 'DB_DIR', directory,
), patch.dict(sync_cli.FACTORIES, {source: lambda logger: source_client, target: lambda logger: target_client},
              clear=True), patch.dict(sync_cli.SYNC_CONFIG, {}, clear=True), patch.dict(
    sync_cli.NOTIFY_CONFIG, {}, clear=True,
):
    raise SystemExit(sync_cli.run_direction(source, target))
'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'scans').mkdir()
            (root / 'submissions').mkdir()
            project = Path(__file__).resolve().parents[1]
            environment = dict(os.environ, PYTHONPATH=str(project / 'scripts'))

            def run(source, target):
                return subprocess.run([sys.executable, '-c', worker, directory, source, target],
                                      cwd=project, env=environment, capture_output=True, text=True, timeout=25)

            with ThreadPoolExecutor(max_workers=12) as pool:
                futures = [pool.submit(run, source, target) for source, target in SYNC_MAP for _ in range(2)]
                results = [future.result() for future in futures]
            for result in results:
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertIn('确认完成 1 条，待核对 0 条，失败 0 条', result.stdout + result.stderr)

            with sqlite3.connect(root / 'activitySync.db') as database:
                confirmed = database.execute('''
                    SELECT COUNT(*) FROM sync_transfers WHERE phase='done' GROUP BY scope
                ''').fetchall()
                self.assertEqual([(2,)] * 6, confirmed)

    def test_duplicate_runs_only_claim_an_activity_once(self):
        with tempfile.TemporaryDirectory() as directory:
            state = SyncState(Path(directory) / 'activitySync.db', 'GARMIN_CN', 'one', 'COROS', 'two')
            activity = Activity('1001', STAMP)
            state.discover([activity])
            entered = Event()
            release = Event()

            def process(*args):
                entered.set()
                release.wait(timeout=5)
                return 'done'

            source = SimpleNamespace()
            target = SimpleNamespace()
            with patch.object(sync_engine, '_process', side_effect=process) as process_mock:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    first = pool.submit(sync_activities, source, target, False, state,
                                        Path(directory) / 'cache', 0, only_id=activity.id, now=NOW)
                    self.assertTrue(entered.wait(timeout=3))
                    second = pool.submit(sync_activities, source, target, False, state,
                                         Path(directory) / 'cache', 0, only_id=activity.id, now=NOW)
                    self.assertEqual(RunResult(), second.result(timeout=3))
                    release.set()
                    self.assertEqual(RunResult(done=1), first.result(timeout=3))
                process_mock.assert_called_once()

    def test_repeated_page_is_not_treated_as_completed_scan(self):
        source = SimpleNamespace(list_page=list_adapter([Activity('1', STAMP)], [Activity('1', STAMP)]))
        with self.assertRaisesRegex(SyncError, 'repeated a page'):
            list(scan(source, 0))

    def test_fit_is_not_mutated_and_archive_member_is_not_guessed(self):
        original_fit = fit()
        payload = archive(**{'README.txt': b'metadata', 'sub/123.FIT': original_fit})
        activity_file = decode_activity(payload)
        self.assertEqual(original_fit, activity_file.fit)
        self.assertEqual(payload, activity_file.coros_archive('123'))
        self.assertEqual(original_fit, decode_activity(decode_activity(original_fit).coros_archive('123')).fit)
        with self.assertRaisesRegex(SyncError, 'exactly one'):
            decode_activity(archive(**{'a.fit': original_fit, 'b.fit': original_fit}))
        with self.assertRaisesRegex(SyncError, 'unsafe member'):
            decode_activity(archive(**{'../a.fit': original_fit}))
        with self.assertRaisesRegex(SyncError, 'checksum'):
            decode_activity(original_fit[:-1] + bytes([original_fit[-1] ^ 1]))
        with self.assertRaisesRegex(SyncError, 'FIT header'):
            decode_activity(b'<html>error page</html>')

    def test_cleanup_failure_does_not_override_successful_atomic_write(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = ActivityCache(directory)
            with patch.object(Path, 'unlink', side_effect=PermissionError):
                result = cache.write(Activity('123', STAMP), 'fit', fit())
            self.assertEqual(fit(), result.read_bytes())
