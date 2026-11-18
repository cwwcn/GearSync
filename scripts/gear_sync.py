from conf.config import SYNC_CONFIG
from conf.logger_config import get_logger

logger = get_logger(__name__)

SYNC_MAP = {
    ('COROS', 'GARMIN_GLOBAL'): 'coros_to_garmin_global',
    ('GARMIN_GLOBAL', 'COROS'): 'garmin_global_to_coros',
    ('COROS', 'GARMIN_CN'): 'coros_to_garmin_cn',
    ('GARMIN_CN', 'COROS'): 'garmin_cn_to_coros',
    ('GARMIN_GLOBAL', 'GARMIN_CN'): 'garmin_global_to_garmin_cn',
    ('GARMIN_CN', 'GARMIN_GLOBAL'): 'garmin_cn_to_garmin_global'
}


def main():
    source = SYNC_CONFIG.get('SOURCE', '').strip().upper()
    target = SYNC_CONFIG.get('TARGET', '').strip().upper()
    if not source or not target or (source, target) not in SYNC_MAP:
        logger.error('Set SOURCE and TARGET to a supported synchronization direction.')
        return 2
    return __import__(SYNC_MAP[source, target]).main()


if __name__ == "__main__":
    raise SystemExit(main())
