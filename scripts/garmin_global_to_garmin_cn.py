# garmin_global_to_garmin_cn.py
from gear_sync import getDbClient, logger
from conf.config import SYNC_CONFIG
from garmin.garmin_global_client import GarminGlobalClient
from garmin.garmin_cn_client import GarminCNClient
from datetime import datetime
from utils import notify
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, RetryCallState
import requests


def log_retry(retry_state: RetryCallState):
    logger.warning(
        f"发送钉钉消息失败: {retry_state.outcome.exception()}, 即将开始第{retry_state.attempt_number}次重试，最多尝试请求5次！")


# 定义重试装饰器
@retry(
    # 最多重试5次
    stop=stop_after_attempt(5),
    # 指数退避策略
    wait=wait_exponential(multiplier=1, min=2, max=10),
    # 针对连接错误和连接超时进行重试
    retry=retry_if_exception_type((requests.exceptions.ConnectionError, requests.exceptions.Timeout)),
    # 记录重试次数
    after=log_retry,
    # 重新抛出最后一次异常
    reraise=True
)
def send_notification_with_retry(title, content):
    """带重试机制的通知发送函数"""
    notify.send(title, content)


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
