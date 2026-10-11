import asyncio
import os
import sys

import httpx

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CURRENT_DIR)

from utils import notify
from conf.config import DB_DIR, RQ_CONFIG
from utils.aestools import AESCipher
from rq.rq_connect import RQConnect
from db.rq_user_db import RQUserDB
from conf.logger_config import get_logger

logger = get_logger(__name__)
ocr = None

TIME_OUT = httpx.Timeout(30.0, connect=10.0)
RQ_WEB_ORIGIN = "https://www.rq.run"
SIGN_PAGE_URL = f"{RQ_WEB_ORIGIN}/user/SignIn/"
SIGN_CODE_URL = f"{RQ_WEB_ORIGIN}/User/SignIn/sign_verify_code"
SIGN_SUBMIT_URL = f"{RQ_WEB_ORIGIN}/User/SignIn/sign_in"


class RQSignError(RuntimeError):
    """A sign-in failure that can be reported without exposing credentials."""


class RQSessionExpired(RQSignError):
    """The website rejected the cached app token."""


class RqSign:
    def __init__(self, userId, token):
        self.headers = {
            "Origin": RQ_WEB_ORIGIN,
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
            "Referer": SIGN_PAGE_URL,
        }
        # The token handoff sets RQWEBSESSID on an intermediate redirect.
        self.req = httpx.AsyncClient(
            timeout=TIME_OUT, follow_redirects=True, headers=self.headers
        )
        self.userId = userId
        self.token = token

    async def sigin(self):
        try:
            await self.prepare_session()
            for attempt in range(10):
                code = await self.getSignVerifyCode()
                response = await self.req.post(
                    SIGN_SUBMIT_URL, data={"codes": code},
                    headers={"X-Requested-With": "XMLHttpRequest"},
                )
                self.check_response(response, "提交签到")
                try:
                    result = response.json()
                    status = result.get("status") if isinstance(result, dict) else None
                    if isinstance(status, str) and status.isdigit():
                        status = int(status)
                    if type(status) is not int:
                        raise ValueError("missing integer status")
                except ValueError:
                    raise RQSignError("RQ 签到接口未返回有效的状态码，请检查接口是否变更。") from None
                if status in (1, 10009):
                    message = "签到成功" if status == 1 else "今日已签到成功，无需再次签到"
                    logger.info("RQ %s。", message)
                    try:
                        notify.send("RQ自动签到", f"RQ账号 {RQ_CONFIG['RQ_EMAIL']} {message}！！")
                    except Exception as err:
                        logger.warning("RQ 签到结果已确认，但通知发送失败（%s）。", type(err).__name__)
                    return status
                if status != 10011:
                    raise RQSignError(f"RQ 签到失败，服务端状态码：{status}。")
                if attempt < 9:
                    await asyncio.sleep(1)
            raise RQSignError("RQ 验证码连续识别失败 10 次，本次签到未完成。")
        except httpx.HTTPError as err:
            raise RQSignError(f"RQ 签到请求失败（{type(err).__name__}），请检查网络或稍后重试。") from None
        finally:
            await self.req.aclose()

    @staticmethod
    def check_response(response, action):
        if response.url.path.lower().startswith("/home/login") or response.status_code == 401:
            raise RQSessionExpired("RQ 网页登录已失效，需要重新登录。")
        if response.status_code != 200:
            raise RQSignError(f"RQ {action}失败，HTTP 状态码：{response.status_code}。")

    async def getSignVerifyCode(self):
        response = await self.req.get(SIGN_CODE_URL)
        self.check_response(response, "获取验证码")
        if not response.headers.get("content-type", "").lower().startswith("image/"):
            raise RQSignError("RQ 验证码接口没有返回图片，请检查登录状态或接口是否变更。")
        global ocr
        if ocr is None:
            import ddddocr
            ocr = ddddocr.DdddOcr(beta=True, show_ad=False)
        return ocr.classification(response.content)

    async def prepare_session(self):
        response = await self.req.get(
            SIGN_PAGE_URL, params={"userId": self.userId, "token": self.token}
        )
        self.check_response(response, "打开签到页")
        if "RQWEBSESSID" not in self.req.cookies:
            raise RQSignError("RQ 签到页未建立网页会话，请检查接口是否变更。")


def isKeyValid(aesChiper, text):
    try:
        aesChiper.decrypt(text)
        return True
    except Exception:
        return False


async def rq_sigin(email, password, AES_KEY, rqdbpath):
    aesChiper = AESCipher(AES_KEY)
    encrypt_email = aesChiper.encrypt(email)
    rq_user_db = RQUserDB(rqdbpath)
    rq_connect = RQConnect(email, password, rqdbpath)
    try:
        query_set = rq_user_db.get_user_by_email(encrypt_email)
        if len(query_set) == 1:
            encrypt_user_id, encrypt_access_token = query_set[0][2:4]
            if (isKeyValid(aesChiper, encrypt_user_id)
                    and isKeyValid(aesChiper, encrypt_access_token)
                    and not await rq_connect.isExpiredToken(aesChiper, encrypt_user_id, encrypt_access_token)):
                rqs = RqSign(aesChiper.decrypt(encrypt_user_id), aesChiper.decrypt(encrypt_access_token))
                try:
                    status = await rqs.sigin()
                except RQSessionExpired:
                    # The app API can accept a token that the website rejects.
                    logger.info("RQ 网页会话已失效，重新登录后重试一次。")
                else:
                    rq_user_db.update_user_login_time(encrypt_email)
                    return status

        if not await rq_connect.login(aesChiper):
            raise RQSignError("RQ 登录失败，请检查账号密码及服务状态。")
        query_set = rq_user_db.get_user_by_email(encrypt_email)
        if len(query_set) != 1:
            raise RQSignError("RQ 登录后未找到唯一的令牌记录。")
        encrypt_user_id, encrypt_access_token = query_set[0][2:4]
        rqs = RqSign(aesChiper.decrypt(encrypt_user_id), aesChiper.decrypt(encrypt_access_token))
        return await rqs.sigin()
    except httpx.HTTPError as err:
        raise RQSignError(f"RQ 登录请求失败（{type(err).__name__}），请检查网络或稍后重试。") from None
    finally:
        await rq_connect.req.aclose()


def initRQDB(rqdbpath):
    RQUserDB(rqdbpath).init_database()


def main():
    for key in ("AESKEY", "RQ_EMAIL", "RQ_PASSWORD"):
        if not RQ_CONFIG.get(key):
            logger.error("%s is required for RQ sign-in.", key)
            return 1
    if len(RQ_CONFIG["AESKEY"]) > 32:
        logger.error("AESKEY must not exceed 32 characters.")
        return 1

    os.makedirs(DB_DIR, exist_ok=True)
    rqdbpath = os.path.join(DB_DIR, "rq.db")
    initRQDB(rqdbpath)
    try:
        asyncio.run(rq_sigin(RQ_CONFIG["RQ_EMAIL"], RQ_CONFIG["RQ_PASSWORD"], RQ_CONFIG["AESKEY"], rqdbpath))
    except RQSignError as err:
        logger.error("%s", err)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
