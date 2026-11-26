import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from activity_files import ActivityCache, decode_activity
from conf.logger_config import get_logger
from oss.sts_token_error import StsTokenError
from sync_types import Activity, ObjectUpload, Rejected, SyncError


logger = get_logger(__name__)
DAY_MS = 86_400_000
OVERLAP_MS = 7 * DAY_MS
FULL_SCAN_INTERVAL = 30 * 86_400
PAGE_SIZE = 100
MAX_SCAN_PAGES = 100
MATCH_WINDOW_MS = 3000
RECONCILE_DELAYS = (5,) * 6


@dataclass
class RunResult:
    done: int = 0
    waiting: int = 0
    failed: int = 0

    @property
    def exit_code(self):
        return int(bool(self.waiting or self.failed))

    @property
    def message(self):
        return f'确认完成 {self.done} 条，待核对 {self.waiting} 条，失败 {self.failed} 条。'


def parse_cutoff(value, timezone='Asia/Shanghai'):
    value = value.strip()
    if not value:
        return 0
    try:
        if len(value) not in (8, 14) or not value.isascii() or not value.isdecimal():
            raise ValueError('Invalid timestamp format')
        stamp = datetime.strptime(value, '%Y%m%d' if len(value) == 8 else '%Y%m%d%H%M%S')
        return int(stamp.replace(tzinfo=ZoneInfo(timezone)).timestamp() * 1000)
    except (ValueError, KeyError) as error:
        raise SyncError('Invalid sync start time or time zone') from error


def scan(client, lower_bound, *, max_pages=MAX_SCAN_PAGES):
    seen_ids = set()
    seen_pages = set()
    previous_min = None
    ordered = True
    old_pages = 0
    for page_index in range(max_pages):
        page = client.list_page(page_index, PAGE_SIZE)
        if not page:
            return
        ids = tuple(activity.id for activity in page)
        if ids in seen_pages:
            raise SyncError('Activity pagination repeated a page')
        seen_pages.add(ids)
        times = [activity.start_ms for activity in page]
        ordered = ordered and times == sorted(times, reverse=True) and (previous_min is None or max(times) <= previous_min)
        previous_min = min(times)
        for activity in page:
            if activity.id not in seen_ids:
                seen_ids.add(activity.id)
                if activity.start_ms >= lower_bound:
                    yield activity
        old_pages = old_pages + 1 if ordered and max(times) < lower_bound else 0
        if old_pages == 2:
            return
    raise SyncError('Activity scan reached the page limit without a stable end')


def discover(source, state, cutoff, now):
    checkpoint = state.checkpoint()
    watermark = checkpoint['watermark'] or 0
    full = (checkpoint['cutoff'] != cutoff or not checkpoint['full_scan_at']
            or now - checkpoint['full_scan_at'] >= FULL_SCAN_INTERVAL)
    lower_bound = cutoff if full else max(cutoff, watermark - OVERLAP_MS)
    newest = 0 if full else watermark
    batch = []
    for activity in scan(source, lower_bound):
        batch.append(activity)
        if activity.start_ms <= now * 1000:
            newest = max(newest, activity.start_ms)
        if len(batch) >= PAGE_SIZE:
            state.discover(batch)
            batch = []
    state.discover(batch, cutoff=cutoff, watermark=newest, full_scan_at=now if full else None,
                   checkpoint=checkpoint)


def _activity_file(source, cache, activity, saved_hash):
    try:
        payload = cache.read(activity)
    except SyncError:
        payload = None
    if payload is None or (saved_hash and payload.digest != saved_hash):
        payload = decode_activity(source.download_activity(activity))
        if saved_hash and payload.digest != saved_hash:
            raise SyncError('Source FIT differs from the recorded import attempt')
        cache.write(activity, 'original', payload.original)
    return payload


def match_target(target, activity, digest):
    matches = []
    candidates = 0
    try:
        for entry in scan(target, activity.start_ms - MATCH_WINDOW_MS, max_pages=10):
            if abs(entry.start_ms - activity.start_ms) > MATCH_WINDOW_MS:
                continue
            candidates += 1
            if candidates > 5:
                return ''
            if decode_activity(target.download_activity(entry)).digest == digest:
                matches.append(entry.id)
                if len(matches) > 1:
                    return ''
    except SyncError:
        return ''
    return matches[0] if matches else ''


def _reconcile(row, activity, source, target, cache):
    if row['remote_id']:
        return row['remote_id'], ''
    lookup_warning = ''
    if row['task_id']:
        try:
            match = target.lookup_import(row['task_id'])
            if match:
                return match, ''
        except SyncError as error:
            lookup_warning = str(error)
    if not activity.start_ms:
        return '', 'Activity metadata was not found in the source scan'
    digest = row['file_hash'] or _activity_file(source, cache, activity, '').digest
    return match_target(target, activity, digest), lookup_warning


def _confirm_import(source, target, state, cache, row, activity, *, poll=True):
    delays = RECONCILE_DELAYS if poll and not row['remote_id'] else (0,)
    reason = ''
    for attempt, delay in enumerate(delays, 1):
        if delay:
            logger.info('Activity %s awaiting confirmation; checking in %s seconds (%s/%s)',
                        activity.id, delay, attempt, len(delays))
            time.sleep(delay)
        match = ''
        try:
            match, reason = _reconcile(row, activity, source, target, cache)
        except Exception as error:
            reason = _error_detail(error)
        if match:
            try:
                state.record(activity.id, 'done', remote_id=match)
            except SyncError as error:
                logger.error('Activity %s matched target %s but could not record completion: %s',
                             activity.id, match, error)
                try:
                    state.record(activity.id, row['phase'], remote_id=match, error=str(error))
                except SyncError as database_error:
                    logger.error('Activity %s: %s', activity.id, database_error)
                return 'failed'
            logger.info('Activity %s confirmed at target as %s', activity.id, match)
            return 'done'
    reason = reason or 'No conclusive target match; import was not replayed'
    try:
        state.record(activity.id, row['phase'], error=reason)
    except SyncError as error:
        logger.error('Activity %s: %s', activity.id, error)
        return 'failed'
    logger.warning('Activity %s remains unconfirmed after checking in this run: %s; next run will reconcile it',
                   activity.id, reason)
    return 'waiting'


def _process(source, target, target_is_coros, state, cache, row):
    activity = Activity(row['activity_id'], row['start_ms'], row['sport'])
    phase = row['phase']
    if phase in ('submitting', 'accepted', 'legacy_review'):
        return _confirm_import(source, target, state, cache, row, activity, poll=phase != 'legacy_review')

    stage = 'download/validation'
    receipt = None
    try:
        payload = _activity_file(source, cache, activity, row['file_hash'])
        stage = 'local staging'
        if target_is_coros:
            if phase == 'storage_ready':
                uploaded = ObjectUpload(row['object_key'], row['object_bucket'], row['object_service'],
                                        row['object_md5'], row['object_size'])
            else:
                archive_path = cache.write(activity, 'zip', payload.coros_archive(activity.id))
                stage = 'OSS upload'
                uploaded = target.upload_object(archive_path)
                state.record(activity.id, 'storage_ready', file_hash=payload.digest,
                             original_hash=payload.original_digest, uploaded=uploaded)
                phase = 'storage_ready'
        else:
            fit_path = cache.write(activity, 'fit', payload.fit)
        stage = 'persist submit intent'
        state.record(activity.id, 'submitting', file_hash=payload.digest,
                     original_hash=row['original_hash'] or payload.original_digest)
        phase = 'submitting'
        stage = 'submit import'
        receipt = target.submit_import(uploaded, activity) if target_is_coros else target.upload_activity(fit_path)
        stage = 'persist import result'
        if receipt.remote_id:
            state.record(activity.id, 'done', task_id=receipt.task_id, remote_id=receipt.remote_id)
            logger.info('Activity %s confirmed at target as %s', activity.id, receipt.remote_id)
            return 'done'
        state.record(activity.id, 'accepted', task_id=receipt.task_id, error='Import accepted; target ID not confirmed')
        phase = 'accepted'
        stage = 'confirm import'
        logger.info('Activity %s accepted; checking the target in this run', activity.id)
        return _confirm_import(source, target, state, cache, state.transfer(activity.id), activity)
    except Exception as error:
        if phase == 'submitting' and stage == 'submit import' and isinstance(error, Rejected):
            phase = 'pending'
        if receipt is not None:
            phase = 'accepted'
        message = f'{stage}: {_error_detail(error)}'
        logger.warning('Activity %s: %s', activity.id, message)
        try:
            state.record(activity.id, phase, error=message, task_id=receipt.task_id if receipt else None,
                         remote_id=receipt.remote_id if receipt else None)
        except SyncError as database_error:
            logger.error('Activity %s: %s', activity.id, database_error)
            return 'failed'
        if phase == 'submitting' and stage == 'submit import':
            try:
                outcome = _confirm_import(source, target, state, cache, state.transfer(activity.id), activity)
            except SyncError as database_error:
                logger.error('Activity %s: %s', activity.id, database_error)
                return 'failed'
            if outcome == 'done':
                return outcome
        return 'failed'


def _error_detail(error):
    return str(error) if isinstance(error, (SyncError, StsTokenError)) else type(error).__name__


def sync_activities(source, target, target_is_coros, state, cache_root, cutoff, *, only_id='', now=None):
    cache = ActivityCache(Path(cache_root) / state.scope)
    result = RunResult()
    if only_id:
        existing = state.transfer(only_id)
        if existing is None or (existing['phase'] == 'legacy_review' and not existing['start_ms']):
            direct = getattr(source, 'get_activity', None)
            activity = direct(only_id) if direct else next((item for item in scan(source, 0) if item.id == only_id), None)
            if activity is None:
                raise SyncError('Requested source activity was not found')
            state.discover([activity])
    else:
        try:
            discover(source, state, cutoff, int(time.time()) if now is None else now)
        except SyncError as error:
            logger.error('Activity discovery failed: %s; processing the existing queue', error)
            result.failed += 1
    for row in state.outstanding(only_id):
        with state.claim(row['activity_id']) as claimed:
            if not claimed:
                logger.info('Activity %s is already being handled by another sync run; skipping',
                            row['activity_id'])
                continue
            current = state.transfer(row['activity_id'])
            if current is None or current['phase'] == 'done':
                continue
            outcome = _process(source, target, target_is_coros, state, cache, current)
        setattr(result, outcome, getattr(result, outcome) + 1)
    return result
