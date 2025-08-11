# garmin_global_to_coros.py
from gear_sync import getDbClient, logger
from conf.config import SYNC_CONFIG
from garmin.garmin_global_client import GarminGlobalClient
from coros.coros_client import CorosClient
from datetime import datetime

from utils import notify


def main():
    # 检查必需的配置参数
    required_configs = {
        "COROS_EMAIL": "Coros email is not configured. Please set COROS_EMAIL value before running the program.",
        "COROS_PASSWORD": "Coros password is not configured. Please set COROS_PASSWORD value before running the program.",
        "GARMIN_GLOBAL_EMAIL": "Garmin Global email is not configured. Please set GARMIN_GLOBAL_EMAIL value before running the program.",
        "GARMIN_GLOBAL_PASSWORD": "Garmin Global password is not configured. Please set GARMIN_GLOBAL_PASSWORD value before running the program."
    }

    for config_key, error_message in required_configs.items():
        if not SYNC_CONFIG.get(config_key):
            logger.info(error_message)
            return

    logger.warning("Starting to sync activity data from Garmin Global to Coros...")

    db = getDbClient()

    # 获取高驰客户端
    COROS_EMAIL = SYNC_CONFIG["COROS_EMAIL"]
    COROS_PASSWORD = SYNC_CONFIG["COROS_PASSWORD"]
    corosClient = CorosClient(COROS_EMAIL, COROS_PASSWORD)
    logger.warning("Coros account is not logging in or the token has expired. So start logging into Coros now!")
    corosClient.login()
    logger.warning(f"Coros account {corosClient.email} logged in successfully!")

    # 获取佳明国际区客户端
    GARMIN_GLOBAL_EMAIL = SYNC_CONFIG["GARMIN_GLOBAL_EMAIL"]
    GARMIN_GLOBAL_PASSWORD = SYNC_CONFIG["GARMIN_GLOBAL_PASSWORD"]
    garminGlobalClient = GarminGlobalClient(GARMIN_GLOBAL_EMAIL, GARMIN_GLOBAL_PASSWORD)

    sync_result = garminGlobalClient.upload_to_coros(corosClient, db, 'GARMIN_GLOBAL', 'COROS')
    # 返回同步统计信息
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    notify.send("佳明国际区同步数据到高驰：", f"{current_time}，{sync_result['message']}")


if __name__ == "__main__":
    main()
