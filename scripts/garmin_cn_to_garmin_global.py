# garmin_cn_to_garmin_global.py
from gear_sync import getDbClient, logger
from conf.config import SYNC_CONFIG
from garmin.garmin_cn_client import GarminCNClient
from garmin.garmin_global_client import GarminGlobalClient
from utils import notify
from datetime import datetime

def main():
    # 检查必需的配置参数
    required_configs = {
        "GARMIN_CN_EMAIL": "Garmin China email is not configured. Please set GARMIN_CN_EMAIL value before running the program.",
        "GARMIN_CN_PASSWORD": "Garmin China password is not configured. Please set GARMIN_CN_PASSWORD value before running the program.",
        "GARMIN_GLOBAL_EMAIL": "Garmin Global email is not configured. Please set GARMIN_GLOBAL_EMAIL value before running the program.",
        "GARMIN_GLOBAL_PASSWORD": "Garmin Global password is not configured. Please set GARMIN_GLOBAL_PASSWORD value before running the program."
    }

    for config_key, error_message in required_configs.items():
        if not SYNC_CONFIG.get(config_key):
            logger.info(error_message)
            return

    logger.warning("Starting to sync activity data from Garmin China to Garmin Global...")

    db = getDbClient()

    # 获取佳明中国区客户端
    GARMIN_CN_EMAIL = SYNC_CONFIG["GARMIN_CN_EMAIL"]
    GARMIN_CN_PASSWORD = SYNC_CONFIG["GARMIN_CN_PASSWORD"]
    garminCNClient = GarminCNClient(GARMIN_CN_EMAIL, GARMIN_CN_PASSWORD)

    # 获取佳明国际区客户端
    GARMIN_GLOBAL_EMAIL = SYNC_CONFIG["GARMIN_GLOBAL_EMAIL"]
    GARMIN_GLOBAL_PASSWORD = SYNC_CONFIG["GARMIN_GLOBAL_PASSWORD"]
    garminGlobalClient = GarminGlobalClient(GARMIN_GLOBAL_EMAIL, GARMIN_GLOBAL_PASSWORD)

    sync_result = garminCNClient.uploadToGarminGlobal(garminGlobalClient, db, 'GARMIN_CN', 'GARMIN_GLOBAL')
    # 返回同步统计信息
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    notify.send("佳明中国区同步数据到佳明国际区：", f"{current_time}，{sync_result['message']}")


if __name__ == "__main__":
    main()
