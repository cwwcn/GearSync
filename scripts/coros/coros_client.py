import os
from datetime import datetime
import urllib3
import json
import hashlib
import certifi

from conf.config import SYNC_CONFIG, COROS_FIT_DIR
from .region_config import REGIONCONFIG
from .sts_config import STS_CONFIG_COROS
from conf.logger_config import get_logger

logger = get_logger(__name__)


class CorosClient:

    def __init__(self, email, password) -> None:

        self.email = email
        self.password = password
        self.req = urllib3.PoolManager(cert_reqs='CERT_REQUIRED', ca_certs=certifi.where())
        self.accessToken = None
        self.userId = None
        self.regionId = None
        self.teamapi = None

    ## 登录接口
    def login(self):

        login_url = "https://teamcnapi.coros.com/account/login"

        login_data = {
            "account": self.email,
            "pwd": hashlib.md5(self.password.encode()).hexdigest(),  ##MD5加密密码
            "accountType": 2,
        }
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=UTF-8",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.39 Safari/537.36",
            "referer": "https://trainingcn.coros.com/",
            "origin": "https://trainingcn.coros.com/",
        }

        login_body = json.dumps(login_data)
        response = self.req.request('POST', login_url, body=login_body, headers=headers)

        login_response = json.loads(response.data)
        login_result = login_response["result"]
        if login_result != "0000":
            raise CorosLoginError("高驰登录异常，异常原因为：" + login_response["message"])

        accessToken = login_response["data"]["accessToken"]
        userId = login_response["data"]["userId"]
        regionId = login_response["data"]["regionId"]
        self.accessToken = accessToken
        self.userId = userId
        self.regionId = regionId
        self.teamapi = REGIONCONFIG[self.regionId]['teamapi']

    # 上传运动。这个是大佬使用oss方式上传的方法，因为官网就是这样，那就用这样的方式吧，稳妥一些
    def uploadActivity(self, oss_object, md5, fileName, size):
        ## 判断Token 是否为空
        if self.accessToken is None:
            self.login()

        upload_url = "https://teamcnapi.coros.com/activity/fit/import"

        headers = {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.39 Safari/537.36",
            "referer": "https://trainingcn.coros.com/",
            "origin": "https://trainingcn.coros.com/",
            "accesstoken": self.accessToken,
        }
        try:
            bucket = STS_CONFIG_COROS[self.regionId]["bucket"]
            serviceName = STS_CONFIG_COROS[self.regionId]["service"]
            data = {"source": 1, "timezone": 32, "bucket": f"{bucket}", "md5": f"{md5}", "size": size,
                    "object": f"{oss_object}", "serviceName": f"{serviceName}", "oriFileName": f"{fileName}"}
            json_data = json.dumps(data)
            json_str = str(json_data)
            # 调试打印出来上传时候的json
            logger.info(json_str)
            response = self.req.request(
                method='POST',
                url=upload_url,
                fields={"jsonParameter": json_str},
                headers=headers
            )
            upload_response = json.loads(response.data)
            upload_result = upload_response["result"]
            return upload_result
        except Exception as err:
            logger.warning()
            exit()

    ## 登录装饰器
    def loginCheck(func):
        def ware(self, *args, **kwargs):
            ## 判断Token 是否为空
            if self.accessToken == None:
                self.login()

            return func(self, *args, **kwargs)

        return ware

    def getHeaders(self):
        headers = {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.39 Safari/537.36",
            "referer": "https://trainingcn.coros.com/",
            "origin": "https://trainingcn.coros.com/",
            "accesstoken": self.accessToken,
        }
        return headers

    ## 获取下载链接
    @loginCheck
    def getDownloadUrl(self, labelId, sportType, fileType=4):
        down_url = f'https://teamcnapi.coros.com/activity/detail/download?labelId={labelId}&sportType={sportType}&fileType=4'
        try:
            response = self.req.request(
                method='POST',
                url=down_url,
                fields={},
                headers=self.getHeaders()
            )
            down_response = json.loads(response.data)
            return down_response["data"]["fileUrl"]
        except Exception as err:
            exit()

    ## 下载
    @loginCheck
    def download(self, url):
        try:
            response = self.req.request(
                method='GET',
                url=url,
                fields={},
                headers=self.getHeaders()
            )
            return response
        except Exception as err:
            exit()

    ## 获取运动
    @loginCheck
    def getActivities(self, pageNumber: int, pageSize: int):

        listUrl = f'https://teamcnapi.coros.com/activity/query?size={str(pageSize)}&pageNumber={str(pageNumber)}&modeList='

        try:
            response = self.req.request(
                method='GET',
                url=listUrl,
                fields={},
                headers=self.getHeaders()
            )
            responseData = json.loads(response.data)
            data = responseData.get('data', {})
            dataList = data.get('dataList', [])
            return dataList
        except Exception as err:
            exit()

    ## 获取所有运动
    def getAllActivities(self):
        all_urlList = []
        pageNumber = 1
        # 起始同步时间 比对的是时间戳
        sync_start_time_strRaw = SYNC_CONFIG["SYNC_ACTIVITY_START_TIME"].strip()
        if sync_start_time_strRaw:
            # 如果长度为8（格式为YYYYMMDD），则自动添加"000101"表示00:01:01
            if len(sync_start_time_strRaw) == 8:
                sync_start_time_strRaw += "000001"
            sync_start_time_ts = int(datetime.strptime(sync_start_time_strRaw, "%Y%m%d%H%M%S").timestamp() * 1000)
        else:
            sync_start_time_ts = 0
        while True:
            # logger.warning(f"get coros activities of pageNumber {pageNumber}.")
            activityInfoList = self.getActivities(pageNumber=pageNumber, pageSize=100)
            urlList = []
            for activityInfo in activityInfoList:
                labelId = activityInfo["labelId"]
                sportType = activityInfo["sportType"]
                startTime = int(f"{activityInfo['startTime']}000")
                # 同步起始时间之前的历史纪录不再查询及同步
                if startTime < sync_start_time_ts:
                    if len(urlList) > 0:
                        all_urlList.extend(urlList)
                    return all_urlList

                activityDownloadUrl = self.getDownloadUrl(labelId, sportType)
                if (activityDownloadUrl):
                    urlList.append((labelId, activityDownloadUrl, startTime))  # 已元祖形式存储
            if len(urlList) > 0:
                all_urlList.extend(urlList)
            else:
                return all_urlList
            pageNumber += 1

    @staticmethod
    def find_url_from_id(list, id):
        for item in list:
            if item[0] == id:
                return item[1]
        return None

        # 添加辅助方法来生成序数

    @staticmethod
    def _get_ordinal(n):
        if 10 <= n % 100 <= 20:
            suffix = 'th'
        else:
            suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
        return f"{n}{suffix}"

    def uploadToGarmin(self, garminClient, db, source, target):
        all_activities = self.getAllActivities()
        if all_activities is None or len(all_activities) == 0:
            logger.warning("has no coros activities.")
            exit()
        logger.warning(f"has {len(all_activities)} all activities.")
        for activity in all_activities:
            activity_id = activity[0]
            db.saveActivity(activity_id, source, target)

        un_sync_id_list = db.getUnSyncActivity(source, target)
        if un_sync_id_list is None or len(un_sync_id_list) == 0:
            logger.warning("has no un sync coros activities.")
            exit()
        logger.warning(f"has {len(un_sync_id_list)} un sync coros activities.")

        # 初始化计数器
        total_sync_count = len(un_sync_id_list)
        success_count = 0

        # 在循环开始前添加索引跟踪
        for index, un_sync_id in enumerate(un_sync_id_list, start=1):
            try:
                download_url = self.find_url_from_id(all_activities, str(un_sync_id))
                if download_url is None:
                    # 未找到对应的下载链接也视为同步
                    logger.warning(f"coros ${un_sync_id} download url missing.")
                    continue

                fileResponse = self.download(download_url)
                file_path = os.path.join(COROS_FIT_DIR, f"{un_sync_id}.fit")
                with open(file_path, "wb") as fb:
                    fb.write(fileResponse.data)

                try:
                    upload_result = garminClient.upload_activity(file_path)
                    # 添加动态序数日志
                    ordinal = self._get_ordinal(index)
                    logger.info(
                        f"--------------------------- Start uploading the {ordinal} coros activity data to garmin. ---------------------------")
                    if upload_result.status_code == 202:
                        logger.info(f"Upload coros {un_sync_id} to garmin success.")
                        self.update_db_status(db, un_sync_id, source, target)
                        success_count += 1  # 增加成功计数
                    else:
                        responseData = json.loads(upload_result.text)
                        messages = responseData['detailedImportResult']['failures'][0]['messages']
                        code = messages[0]['code']
                        content = messages[0]['content']
                        logger.warning(
                            f"Upload coros {un_sync_id} to garmin fake fail: (the status_code is {code}, the content is {content})")
                        if '202' == str(code):
                            self.update_db_status(db, un_sync_id, source, target)
                            success_count += 1  # 增加成功计数
                except Exception as e:
                    logger.warning(f"Upload coros {un_sync_id} to garmin error inside: {e}")
            except Exception as err:
                logger.warning(f"download coros {un_sync_id} activity fail: {err}")

        # 计算失败条数
        failed_count = total_sync_count - success_count
        # 返回同步统计信息
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if failed_count > 0:
            notifyInfo = f"同步任务执行完成，本次共同步{total_sync_count}条数据，成功同步{success_count}条，{failed_count}条数据同步失败。"
        else:
            notifyInfo = f"同步任务执行完成，成功同步{total_sync_count}条数据。"

        return {
            "message": notifyInfo,
            "total": total_sync_count,
            "success": success_count,
            "failed": failed_count
        }

    # 更新数据库同步状态
    @staticmethod
    def update_db_status(db, un_sync_id, source, target):
        try:
            db.updateSyncStatus(un_sync_id, source, target)
            logger.info(f"sync coros activity {un_sync_id} upload to garmin success, and the db has been updated.")
        except Exception as err:
            print(err)
            db.updateExceptionSyncStatus(un_sync_id, source, target)
            logger.warning(f"sync coros ${un_sync_id} exception.")


class CorosLoginError(Exception):

    def __init__(self, status):
        """Initialize."""
        super(CorosLoginError, self).__init__(status)
        self.status = status


class CorosActivityUploadError(Exception):

    def __init__(self, status):
        """Initialize."""
        super(CorosActivityUploadError, self).__init__(status)
        self.status = status
