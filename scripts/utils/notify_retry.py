import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential, RetryCallState

from conf.logger_config import get_logger
from utils import notify

logger = get_logger(__name__)


def log_retry(retry_state: RetryCallState):
    logger.warning(
        f"发送钉钉消息失败: {retry_state.outcome.exception()}, 即将开始第{retry_state.attempt_number}次重试，最多尝试请求5次！")


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((requests.exceptions.ConnectionError, requests.exceptions.Timeout)),
    after=log_retry,
    reraise=True
)
def send_notification_with_retry(title, content):
    """带重试机制的通知发送函数"""
    notify.send(title, content)
