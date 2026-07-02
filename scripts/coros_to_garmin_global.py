# coros_to_garmin_global.py
from gear_sync import getDbClient, logger
from client_factory import create_coros_client, create_garmin_global_client
from datetime import datetime
from utils.notify_retry import send_notification_with_retry


def main():
    db = getDbClient()
    corosClient = create_coros_client(logger)
    if corosClient is None:
        return
    garminGlobalClient = create_garmin_global_client(logger)
    if garminGlobalClient is None:
        return

    sync_result = corosClient.uploadToGarmin(garminGlobalClient, db, 'COROS', 'GARMIN_GLOBAL')
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 使用带重试机制的通知发送
    try:
        send_notification_with_retry("高驰同步数据到佳明国际区：", f"{current_time}，{sync_result['message']}")
    except Exception as e:
        logger.warning(f"发送钉钉通知失败（即使重试5次后）: {e}")


if __name__ == "__main__":
    main()
