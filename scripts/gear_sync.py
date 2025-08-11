# gear-sync.py
import os
import sys
from conf.config import SYNC_CONFIG, DB_DIR, GARMIN_GLOBAL_FIT_DIR, GARMIN_CN_FIT_DIR, COROS_FIT_DIR
from db.activity_db import ActivityDB
from conf.logger_config import get_logger

logger = get_logger(__name__)

CURRENT_DIR = os.path.split(os.path.abspath(__file__))[0]
garmin_path = CURRENT_DIR + os.path.sep + 'garmin'
coros_path = CURRENT_DIR + os.path.sep + 'coros'
sys.path.append(garmin_path)
sys.path.append(coros_path)


def init(activity_db):
    if not os.path.exists(os.path.join(DB_DIR, activity_db.db_name)):
        activity_db.initDB()
    if not os.path.exists(GARMIN_GLOBAL_FIT_DIR):
        os.mkdir(GARMIN_GLOBAL_FIT_DIR)
    if not os.path.exists(GARMIN_CN_FIT_DIR):
        os.mkdir(GARMIN_CN_FIT_DIR)
    if not os.path.exists(COROS_FIT_DIR):
        os.mkdir(COROS_FIT_DIR)


def getDbClient():
    db_name = 'activitySync.db'
    activity_db = ActivityDB(db_name)
    init(activity_db)
    return activity_db


# 映射源和目标到对应的模块
SYNC_MAP = {
    ('COROS', 'GARMIN_GLOBAL'): 'coros_to_garmin_global',
    ('GARMIN_GLOBAL', 'COROS'): 'garmin_global_to_coros',
    ('COROS', 'GARMIN_CN'): 'coros_to_garmin_cn',
    ('GARMIN_CN', 'COROS'): 'garmin_cn_to_coros',
    ('GARMIN_GLOBAL', 'GARMIN_CN'): 'garmin_global_to_garmin_cn',
    ('GARMIN_CN', 'GARMIN_GLOBAL'): 'garmin_cn_to_garmin_global'
}


# 如果你只启动一个，也可以配置SOURCE和TARGET后，从这里启动
def main():
    # 检查SOURCE和TARGET配置
    if not SYNC_CONFIG.get("SOURCE"):
        logger.error("SOURCE parameter is not configured. Please set SOURCE value before running the program.")
        return

    if not SYNC_CONFIG.get("TARGET"):
        logger.error("TARGET parameter is not configured. Please set TARGET value before running the program.")
        return

    source = SYNC_CONFIG["SOURCE"].upper()
    target = SYNC_CONFIG["TARGET"].upper()

    sync_key = (source, target)
    if sync_key in SYNC_MAP:
        module_name = SYNC_MAP[sync_key]
        # 动态导入并执行对应的模块
        module = __import__(module_name)
        module.main()
    else:
        logger.error(f"Temporarily not supported sync direction: {source} to {target}")


if __name__ == "__main__":
    main()
