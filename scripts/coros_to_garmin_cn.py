# coros_to_garmin_cn.py
from gear_sync import getDbClient, logger
from client_factory import create_coros_client, create_garmin_cn_client
from datetime import datetime
from utils.notify_retry import send_notification_with_retry


def main():
    db = getDbClient()
    corosClient = create_coros_client(logger)
    if corosClient is None:
        return
    garminCNClient = create_garmin_cn_client(logger)
    if garminCNClient is None:
        return

    sync_result = corosClient.uploadToGarmin(garminCNClient, db, 'COROS', 'GARMIN_CN')
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 使用带重试机制的通知发送
    try:
        send_notification_with_retry("高驰同步数据到佳明中国区：", f"{current_time}，{sync_result['message']}")
    except Exception as e:
        logger.error(f"发送钉钉通知最终失败（即使重试5次后）: {e}")


if __name__ == "__main__":
    main()
