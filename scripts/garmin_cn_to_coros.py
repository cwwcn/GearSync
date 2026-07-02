# garmin_cn_to_coros.py
from gear_sync import getDbClient, logger
from client_factory import create_coros_client, create_garmin_cn_client
from datetime import datetime
from utils.notify_retry import send_notification_with_retry


def main():
    garminCNClient = create_garmin_cn_client(logger)
    if garminCNClient is None:
        return

    logger.warning("Starting to sync activity data from Garmin China to Coros...")
    db = getDbClient()

    corosClient = create_coros_client(logger)
    if corosClient is None:
        return

    sync_result = garminCNClient.upload_to_coros(corosClient, db, 'GARMIN_CN', 'COROS')

    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 使用带重试机制的通知发送
    try:
        send_notification_with_retry("佳明中国区同步数据到高驰：", f"{current_time}，{sync_result['message']}")
    except Exception as e:
        logger.warning(f"发送钉钉通知失败（即使重试5次后）: {e}")


if __name__ == "__main__":
    main()
