# coros_to_garmin_cn.py
from gear_sync import getDbClient, logger
from conf.config import SYNC_CONFIG
from garmin.garmin_cn_client import GarminCNClient
from coros.coros_client import CorosClient
from utils import notify
from datetime import datetime

def main():
    # 检查必需的配置参数
    required_configs = {
        "COROS_EMAIL": "Coros email is not configured. Please set COROS_EMAIL value before running the program.",
        "COROS_PASSWORD": "Coros password is not configured. Please set COROS_PASSWORD value before running the program.",
        "GARMIN_CN_EMAIL": "Garmin CN email is not configured. Please set GARMIN_CN_EMAIL value before running the program.",
        "GARMIN_CN_PASSWORD": "Garmin CN password is not configured. Please set GARMIN_CN_PASSWORD value before running the program."
    }

    for config_key, error_message in required_configs.items():
        if not SYNC_CONFIG.get(config_key):
            logger.info(error_message)
            return

    logger.warning("Starting to sync activity data from Coros to Garmin China...")

    db = getDbClient()

    # 获取佳明中国区客户端
    GARMIN_CN_EMAIL = SYNC_CONFIG["GARMIN_CN_EMAIL"]
    GARMIN_CN_PASSWORD = SYNC_CONFIG["GARMIN_CN_PASSWORD"]
    garminCNClient = GarminCNClient(GARMIN_CN_EMAIL, GARMIN_CN_PASSWORD)

    # 获取高驰客户端
    COROS_EMAIL = SYNC_CONFIG["COROS_EMAIL"]
    COROS_PASSWORD = SYNC_CONFIG["COROS_PASSWORD"]
    corosClient = CorosClient(COROS_EMAIL, COROS_PASSWORD)
    logger.info("Coros account is not logging in or the token has expired. So start logging into Coros now!")
    corosClient.login()
    logger.info(f"Coros account {corosClient.email} logged in successfully!")

    sync_result = corosClient.uploadToGarmin(garminCNClient, db, 'COROS', 'GARMIN_CN')
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    notify.send("高驰同步数据到佳明中国区：", f"{current_time}，{sync_result['message']}")

if __name__ == "__main__":
    main()
