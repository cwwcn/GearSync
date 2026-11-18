from pathlib import Path

from client_factory import create_coros_client, create_garmin_cn_client, create_garmin_global_client
from conf.config import DB_DIR, NOTIFY_CONFIG, SYNC_CONFIG
from conf.logger_config import get_logger
from db.sync_state import SyncState
from sync_engine import _error_detail, parse_cutoff, run_lock, sync_activities
from sync_types import SyncError, remote_id
from utils.notify_retry import send_notification_with_retry


logger = get_logger(__name__)
FACTORIES = {'COROS': create_coros_client, 'GARMIN_CN': create_garmin_cn_client,
             'GARMIN_GLOBAL': create_garmin_global_client}


def run_direction(source, target):
    title = f'{source} → {target}'
    only_id = SYNC_CONFIG.get('SYNC_ACTIVITY_ID', '').strip()
    if only_id and not remote_id(only_id):
        logger.error('SYNC_ACTIVITY_ID is invalid.')
        return 2
    try:
        cutoff = parse_cutoff(SYNC_CONFIG.get('SYNC_ACTIVITY_START_TIME', ''),
                              SYNC_CONFIG.get('SYNC_TIMEZONE', '') or 'Asia/Shanghai')
    except SyncError as error:
        logger.error('%s', error)
        return 2
    try:
        with run_lock(DB_DIR):
            source_client = FACTORIES[source](logger)
            target_client = FACTORIES[target](logger)
            if source_client is None or target_client is None:
                return 2
            directory = Path(DB_DIR)
            state = SyncState(directory / 'activitySync.db', source, source_client.account_id(),
                              target, target_client.account_id())
            result = sync_activities(source_client, target_client, target == 'COROS', state,
                                     directory / 'activity-cache', cutoff, only_id=only_id)
    except Exception as error:
        logger.error('%s: %s', title, _error_detail(error))
        return 1
    logger.info('%s：%s', title, result.message)
    if not only_id and NOTIFY_CONFIG.get('DD_BOT_TOKEN') and (result.done or result.waiting or result.failed):
        try:
            send_notification_with_retry(title, result.message)
        except Exception as error:
            logger.warning('Sync result recorded; notification failed (%s)', type(error).__name__)
    return result.exit_code
