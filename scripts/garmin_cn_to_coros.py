# garmin_cn_to_coros.py
from gear_sync import getDbClient, logger
from conf.config import SYNC_CONFIG
from garmin.garmin_cn_client import GarminCNClient
from coros.coros_client import CorosClient


def main():
    # 检查必需的配置参数
    required_configs = {
        "COROS_EMAIL": "Coros email is not configured. Please set COROS_EMAIL value before running the program.",
        "COROS_PASSWORD": "Coros password is not configured. Please set COROS_PASSWORD value before running the program.",
        "GARMIN_CN_EMAIL": "Garmin China email is not configured. Please set GARMIN_CN_EMAIL value before running the program.",
        "GARMIN_CN_PASSWORD": "Garmin China password is not configured. Please set GARMIN_CN_PASSWORD value before running the program."
    }

    for config_key, error_message in required_configs.items():
        if not SYNC_CONFIG.get(config_key):
            logger.info(error_message)
            return

    logger.warning("Starting to sync activity data from Garmin China to Coros...")

    db = getDbClient()

    # 获取高驰客户端
    COROS_EMAIL = SYNC_CONFIG["COROS_EMAIL"]
    COROS_PASSWORD = SYNC_CONFIG["COROS_PASSWORD"]
    corosClient = CorosClient(COROS_EMAIL, COROS_PASSWORD)
    logger.warning("Coros account is not logging in or the token has expired. So start logging into Coros now!")
    corosClient.login()
    logger.warning(f"Coros account {corosClient.email} logged in successfully!")

    # 获取佳明中国区客户端
    GARMIN_CN_EMAIL = SYNC_CONFIG["GARMIN_CN_EMAIL"]
    GARMIN_CN_PASSWORD = SYNC_CONFIG["GARMIN_CN_PASSWORD"]
    garminCNClient = GarminCNClient(GARMIN_CN_EMAIL, GARMIN_CN_PASSWORD)

    garminCNClient.upload_to_coros(corosClient, db, 'GARMIN_CN', 'COROS')


if __name__ == "__main__":
    main()
