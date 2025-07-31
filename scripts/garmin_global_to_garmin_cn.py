# garmin_global_to_garmin_cn.py
from gear_sync import getDbClient, logger
from conf.config import SYNC_CONFIG
from garmin.garmin_global_client import GarminGlobalClient
from garmin.garmin_cn_client import GarminCNClient


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

    logger.warning("Starting to sync activity data from Garmin Global to Garmin China...")

    db = getDbClient()

    # 获取佳明中国区客户端
    GARMIN_CN_EMAIL = SYNC_CONFIG["GARMIN_CN_EMAIL"]
    GARMIN_CN_PASSWORD = SYNC_CONFIG["GARMIN_CN_PASSWORD"]
    garminCNClient = GarminCNClient(GARMIN_CN_EMAIL, GARMIN_CN_PASSWORD)

    # 获取佳明国际区客户端
    GARMIN_GLOBAL_EMAIL = SYNC_CONFIG["GARMIN_GLOBAL_EMAIL"]
    GARMIN_GLOBAL_PASSWORD = SYNC_CONFIG["GARMIN_GLOBAL_PASSWORD"]
    garminGlobalClient = GarminGlobalClient(GARMIN_GLOBAL_EMAIL, GARMIN_GLOBAL_PASSWORD)

    garminGlobalClient.uploadToGarminCN(garminCNClient, db, 'GARMIN_GLOBAL', 'GARMIN_CN')


if __name__ == "__main__":
    main()
