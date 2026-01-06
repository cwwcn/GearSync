import time
import httpx
import random
import asyncio
import os
import sys
import ddddocr

# 获取项目根目录路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)
# 修改导入路径，引用scripts目录下的notify模块
from utils import notify

CURRENT_DIR = os.path.split(os.path.abspath(__file__))[0]  # 当前目录
config_path = CURRENT_DIR.rsplit('/', 1)[0]  # 上三级目录
sys.path.append(config_path)

from conf.config import DB_DIR, RQ_CONFIG
from db.sqlite_db import SqliteDB
from utils.aestools import AESCipher
from rq.rq_connect import RQConnect
from db.rq_user_db import RQUserDB
from conf.logger_config import get_logger

logger = get_logger(__name__)

ocr = ddddocr.DdddOcr(beta=True, show_ad=False)

TIME_OUT = httpx.Timeout(1000.0, connect=1000.0)


class RqSign:
    def __init__(self, userId, token):
        self.req = httpx.AsyncClient(timeout=TIME_OUT)
        ## 签到请求头
        self.headers = {
            "Host": "rq.runningquotient.cn",
            "Origin": "https://rq.runningquotient.cn",
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
            # "Referer": f"https://rq.runningquotient.cn/Minisite/SignIn/index?userId={userId}&token={token}",
            "Referer": "https://rq.runningquotient.cn/Minisite/SignIn/index",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
        }
        ## RQ用户ID
        self.userId = userId
        ## RQ用户token
        self.token = token

    async def sigin(self):
        ## 随机数
        randomNum = random.uniform(0, 2)
        ## 签到Url
        siginUrl = f"https://rq.runningquotient.cn/MiniApi/SignIn/sign_in/rand/{randomNum}"
        ## PHPSESSID 目前不作存储不清楚RQ原理这块是否会过期故每次请求签到都获取新的PHPSESSID，防止RQ判断用户会脚本执行签到
        PHPSESSID = await self.getSiginPHPSESSID()
        ## 设置请求头Cookie
        self.headers['Cookie'] = f"PHPSESSID={PHPSESSID}"
        threshold = 10
        signVerifyCodeStatus = False
        i = 1
        ## 10次阈值，超过10次都登录不了不执行等下一轮再执行了
        while not signVerifyCodeStatus and i <= threshold:
            try:
                signVerifyCode = await self.getSignVerifyCode(PHPSESSID)

                ## 执行签到
                response = await self.req.post(
                    siginUrl,
                    headers=self.headers,
                    data={'codes': signVerifyCode}
                )
                result = response.json()
                logger.info(result)
                status = result['status']
                ## 判断是否签到成功
                if status == 1:
                    notify.send("RQ自动签到", f"RQ账号 {RQ_CONFIG['RQ_EMAIL']} 签到成功！！")
                    return
                ## 判断验证码是否错误
                elif status == 10011:
                    pass
                ## 判断是否已经签到了
                elif status == 10009:
                    notify.send("RQ自动签到：", f"RQ账号 {RQ_CONFIG['RQ_EMAIL']} 今日已签到成功，无需再次签到！！")
                    return
                i += 1
                time.sleep(1)

            except Exception as err:
                raise err

    async def getSignVerifyCode(self, PHPSESSID):
        ## 验证码URL
        signVerifyCodeUrl = f"https://rq.runningquotient.cn/Minisite/SignIn/sign_verify_code"
        ## PHPSESSID 目前不作存储不清楚RQ原理这块是否会过期故每次请求签到都获取新的PHPSESSID，防止RQ判断用户会脚本执行签到
        ## 设置请求头Cookie
        self.headers['Cookie'] = f"PHPSESSID={PHPSESSID}"
        ## 执行签到
        response = await self.req.get(
            signVerifyCodeUrl,
            headers=self.headers
        )

        res = ocr.classification(response.content)
        return res

    ## 调用获取请求头Referer里面的Cookie
    async def getSiginPHPSESSID(self):
        try:
            response = await self.req.get(
                f"https://rq.runningquotient.cn/Minisite/SignIn/index?userId={self.userId}&token={self.token}",
            )
            return response.cookies['PHPSESSID']
        except Exception as err:
            raise err


def isKeyValid(aesChiper, text):
    try:
        aesChiper.decrypt(text)
        return True
    except Exception as e:
        return False


async def rq_sigin(email, password, AES_KEY, rqdbpath):
    aesChiper = AESCipher(AES_KEY)
    rq_connect = RQConnect(email, password, rqdbpath)
    encrypt_email = aesChiper.encrypt(email)

    # 初始化数据库管理器
    rq_user_db = RQUserDB(rqdbpath)

    # 用于检查现有用户状态（token有效性等）
    with SqliteDB(rqdbpath) as db:
        ## 查询数据库是否存在已保存的账号信息
        query_set = rq_user_db.get_user_by_email(encrypt_email)
        ## 查询返回条数
        query_size = len(query_set)
        ## 判断是否唯一
        if query_size == 1:
            ## 加密user_id
            encrypt_user_id = query_set[0][2]
            ## 加密access_token
            encrypt_access_token = query_set[0][3]

            ## 判断AES KEY 能否解密当前加密数据
            isValid = isKeyValid(aesChiper, encrypt_user_id)

            ## 能解密则执行如下
            if isValid:
                ## 判断存储的token是否过期
                isExpired = await rq_connect.isExpiredToken(aesChiper, encrypt_user_id, encrypt_access_token)
                if not isExpired:
                    rqs = RqSign(
                        aesChiper.decrypt(encrypt_user_id),
                        aesChiper.decrypt(encrypt_access_token)
                    )
                    ## 登录一次更新一次时间保证action不掉线
                await rqs.sigin()
                rq_user_db.update_user_login_time(encrypt_email)
                return
        ## 如果数据库中存储的账号条数大于一条默认全部删除登录后再插入一条保持数据的唯一
        elif query_size > 1:
            for row in query_set:
                rq_user_db.delete_user_by_id(row[0])
            # 继续执行到第二个with
        else:
            # query_size == 0，首次运行
            # 继续执行到第二个with
            pass

    # 用于执行新用户登录或重新登录的逻辑
    with SqliteDB(rqdbpath) as db:
        isSuccessLogin = await rq_connect.login(aesChiper)

        if isSuccessLogin:
            query_set = rq_user_db.get_user_by_email(encrypt_email)
            ## 加密user_id
            encrypt_user_id = query_set[0][2]
            ## 加密access_token
            encrypt_access_token = query_set[0][3]
            rqs = RqSign(
                aesChiper.decrypt(encrypt_user_id),
                aesChiper.decrypt(encrypt_access_token)
            )
            await rqs.sigin()
        else:
            logger.info("帐号密码有误，请检查帐号密码信息！！！")


## 初始化建表
def initRQDB(rqdbpath):
    rq_user_db = RQUserDB(rqdbpath)
    rq_user_db.init_database()

def main():
    # 检查必需的配置参数
    required_configs = {
        "AESKEY": "AESKEY is required for RQ sign-in. Please set AESKEY parameter before running the program.",
        "RQ_EMAIL": "RQ password is required for RQ sign-in. Please set RQ_EMAIL value before running the program.",
        "RQ_PASSWORD": "RQ email is required for RQ sign-in. Please set RQ_PASSWORD value before running the program."
    }

    for config_key, error_message in required_configs.items():
        if not RQ_CONFIG.get(config_key):
            logger.info(error_message)
            return

    aes_key_length = len(RQ_CONFIG["AESKEY"])
    if aes_key_length > 32:
        logger.info(
            f"Invalid AES key length: {aes_key_length} characters. The maximum length of the AESKEY cannot exceed 32 characters, but preferably 16 or 24 or 32 characters. please adjust to a valid length.")
        return
    db_name = 'rq.db'

    ## 判断存储数据文件夹是否存在
    if not os.path.exists(DB_DIR):
        os.mkdir(DB_DIR)

    rqdbpath = os.path.join(DB_DIR, db_name)

    ## 判断RQ数据库是否存在
    if not os.path.exists(rqdbpath):
        ## 初始化建表
        initRQDB(rqdbpath)

    loop = asyncio.get_event_loop()
    future = asyncio.ensure_future(
        rq_sigin(RQ_CONFIG['RQ_EMAIL'], RQ_CONFIG['RQ_PASSWORD'], RQ_CONFIG["AESKEY"], rqdbpath)
    )
    loop.run_until_complete(future)


if __name__ == "__main__":
    main()
