# garmin_cn_to_coros.py
from gear_sync import getDbClient, logger
from conf.config import SYNC_CONFIG
from garmin.garmin_cn_client import GarminCNClient
from coros.coros_client import CorosClient
from utils import notify
from datetime import datetime
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
    # 检查必需的配置参数 - 首先检查高驰账户配置
    coros_required_configs = {
        "COROS_EMAIL": "Coros email is not configured. Please set COROS_EMAIL value before running the program.",
        "COROS_PASSWORD": "Coros password is not configured. Please set COROS_PASSWORD value before running the program."
    }

    for config_key, error_message in coros_required_configs.items():
        if not SYNC_CONFIG.get(config_key):
            logger.info(error_message)
            return

    # 检查 Garmin 中国区配置 - 优先使用 token，回退到邮箱密码
    garmin_cn_secret = SYNC_CONFIG.get("GARMIN_CN_SECRET")
    if garmin_cn_secret:
        # 使用 OAuth token 方式
        logger.info("GARMIN_CN_SECRET is configured, using OAuth token method for login!")
        garminCNClient = GarminCNClient(garmin_cn_secret)
    else:
        # 检查邮箱密码配置
        garmin_required_configs = {
            "GARMIN_CN_EMAIL": "Garmin China email is not configured. Please set GARMIN_CN_EMAIL value before running the program.",
            "GARMIN_CN_PASSWORD": "Garmin China password is not configured. Please set GARMIN_CN_PASSWORD value before running the program."
        }

        for config_key, error_message in garmin_required_configs.items():
            if not SYNC_CONFIG.get(config_key):
                logger.info(error_message)
                return
        logger.info("GARMIN_CN_SECRET is not configured, so 'Email-Password' method will be used for login!")
        GARMIN_CN_EMAIL = SYNC_CONFIG["GARMIN_CN_EMAIL"]
        GARMIN_CN_PASSWORD = SYNC_CONFIG["GARMIN_CN_PASSWORD"]
        garminCNClient = GarminCNClient(GARMIN_CN_EMAIL, GARMIN_CN_PASSWORD)

    logger.warning("Starting to sync activity data from Garmin China to Coros...")
    db = getDbClient()

    # 获取高驰客户端
    COROS_EMAIL = SYNC_CONFIG["COROS_EMAIL"]
    COROS_PASSWORD = SYNC_CONFIG["COROS_PASSWORD"]
    corosClient = CorosClient(COROS_EMAIL, COROS_PASSWORD)
    logger.warning("Coros account is not logging in or the token has expired. So start logging into Coros now!")
    corosClient.login()
    logger.warning(f"Coros account {corosClient.email} logged in successfully!")


    sync_result = garminCNClient.upload_to_coros(corosClient, db, 'GARMIN_CN', 'COROS')

    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 使用带重试机制的通知发送
    try:
        send_notification_with_retry("佳明中国区同步数据到高驰：", f"{current_time}，{sync_result['message']}")
    except Exception as e:
        logger.warning(f"发送钉钉通知失败（即使重试5次后）: {e}")


if __name__ == "__main__":
    main()
