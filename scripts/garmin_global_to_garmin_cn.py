# garmin_global_to_garmin_cn.py
from gear_sync import getDbClient, logger
from client_factory import create_garmin_cn_client, create_garmin_global_client
from datetime import datetime
from utils.notify_retry import send_notification_with_retry


def main():
    garminGlobalClient = create_garmin_global_client(logger)
    if garminGlobalClient is None:
        return

    garminCNClient = create_garmin_cn_client(logger)
    if garminCNClient is None:
        return

    logger.warning("Starting to sync activity data from Garmin Global to Garmin China...")

    db = getDbClient()

    sync_result = garminGlobalClient.uploadToGarminCN(garminCNClient, db, 'GARMIN_GLOBAL', 'GARMIN_CN')
    # 返回同步统计信息
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    # 使用带重试机制的通知发送
    try:
        send_notification_with_retry("佳明国际区同步数据到佳明中国区：", f"{current_time}，{sync_result['message']}")
    except Exception as e:
        logger.warning(f"发送钉钉通知失败（即使重试5次后）: {e}")


if __name__ == "__main__":
    main()
