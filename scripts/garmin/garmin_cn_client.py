import os
import json
import zipfile
import binascii
from enum import Enum, auto
import re
import time
from datetime import datetime
import garth as garth_module
import requests
from oss.ali_oss_client import AliOssClient
from oss.aws_oss_client import AwsOssClient
from utils.md5_utils import calculate_md5_file
from .garmin_url_dict import GARMIN_URL_DICT
from conf.config import SYNC_CONFIG, GARMIN_CN_FIT_DIR
from conf.logger_config import get_logger

logger = get_logger(__name__)


class GarminUploadException(Exception):
    """自定义上传异常类"""

    def __init__(self, message, activity_path=None, original_exception=None):
        super().__init__(message)
        self.activity_path = activity_path
        self.original_exception = original_exception


class GarminCNClient:
    def __init__(self, email_or_secret, password=None):
        if '@' in email_or_secret and password is not None:
            # 邮箱密码方式
            self.auth_method = 'credentials'
            self.email = email_or_secret
            self.password = password
        else:
            # OAuth token 方式
            self.auth_method = 'token'
            self.secret_string = email_or_secret

        # 初始化 garth 客户端
        self.garthClient = garth_module.Client()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome//138.0.0.0 Safari/537.36",
            "Origin": "https://connect.garmin.cn",
            "Nk": "NT"
        }

    ## 登录装饰器
    def login(func):
        def ware(self, *args, **kwargs):
            try:
                if self.auth_method == 'token':
                    # OAuth token 方式
                    try:
                        self.garthClient.username
                    except Exception:
                        logger.warning(
                            "Garmin_CN is not logging in or the token has expired. So start loading token now!")
                        self.garthClient.configure(domain="garmin.cn")
                        self.garthClient.loads(self.secret_string)
                        if self.garthClient.oauth2_token.expired:
                            self.garthClient.refresh_oauth2()
                        logger.warning(f"Garmin_CN account {self.garthClient.username} token loaded successfully!")
                        time.sleep(1)
                        del self.garthClient.sess.headers['User-Agent']
                else:
                    # 邮箱密码方式
                    try:
                        self.garthClient.username
                    except Exception:
                        logger.warning("Garmin_CN is not logging in. So start logging in now!")
                        self.garthClient.configure(domain="garmin.cn")
                        self.garthClient.login(self.email, self.password)
                        logger.warning(f"Garmin_CN account {self.email} logged in successfully!")
                        time.sleep(1)
                        del self.garthClient.sess.headers['User-Agent']
                return func(self, *args, **kwargs)
            except (binascii.Error, AssertionError) as e:
                if self.auth_method == 'token':
                    logger.warning(f"OAuth token authentication failed: {str(e)},Please check if GARMIN_CN_SECRET is correctly configured in your config file.You can regenerate the token using get_garmin_secret.py script.")
                    raise Exception("Invalid OAuth token. Please reconfigure GARMIN_CN_SECRET.")
                else:
                    raise e
        return ware

    @login
    def download(self, path, **kwargs):
        return self.garthClient.download(path, **kwargs)

    @login
    def connectapi(self, path, **kwargs):
        return self.garthClient.connectapi(path, **kwargs)

    ## 获取运动
    def getActivities(self, start: int, limit: int):
        params = {"start": str(start), "limit": str(limit)}
        activities = self.connectapi(path=GARMIN_URL_DICT["garmin_connect_activities"], params=params)
        return activities

    ## 获取所有运动
    def getAllActivities(self):
        all_activities = []
        start = 0
        # 起始同步时间
        sync_start_time_strRaw = SYNC_CONFIG["SYNC_ACTIVITY_START_TIME"].strip()
        if sync_start_time_strRaw:
            # 如果长度为8（格式为YYYYMMDD），则自动添加"000101"表示00:01:01
            if len(sync_start_time_strRaw) == 8:
                sync_start_time_strRaw += "000001"
            sync_start_time_ts = int(datetime.strptime(sync_start_time_strRaw, "%Y%m%d%H%M%S").timestamp() * 1000)
        else:
            sync_start_time_ts = 0
        while True:
            # 当start超过10000时接口请求返回http 400
            # if start >= 10000:
            #     return all_activities
            activityInfoList = self.getActivities(start=start, limit=100)
            activityList = []
            for activityInfo in activityInfoList:
                beginTimestamp = activityInfo["beginTimestamp"]
                if beginTimestamp < sync_start_time_ts:
                    if len(activityList) > 0:
                        all_activities.extend(activityList)
                    return all_activities
                activityList.append(activityInfo)
            if len(activityList) > 0:
                all_activities.extend(activityList)
            else:
                return all_activities
            start += 100

    ## 下载原始格式的运动
    def downloadFitActivity(self, activity):
        download_fit_activity_url_prefix = GARMIN_URL_DICT["garmin_connect_fit_download"]
        download_fit_activity_url = f"{download_fit_activity_url_prefix}/{activity}"
        response = self.download(download_fit_activity_url)
        # 再次确保目录存在，没有就生成一个
        os.makedirs(GARMIN_CN_FIT_DIR, exist_ok=True)

        return response

    ## 下载tcx格式的运动
    def downloadTcxActivity(self, activity):
        download_fit_activity_url_prefix = GARMIN_URL_DICT["garmin_connect_tcx_download"]
        download_fit_activity_url = f"{download_fit_activity_url_prefix}/{activity}"
        response = self.download(download_fit_activity_url)
        return response

    @login
    def upload_activity(self, activity_path: str):
        """Upload activity in fit format from file."""
        # This code is borrowed from python-garminconnect-enhanced ;-)
        file_base_name = os.path.basename(activity_path)
        file_extension = file_base_name.split(".")[-1]
        allowed_file_extension = (
                file_extension.upper() in ActivityUploadFormat.__members__
        )

        if allowed_file_extension:
            try:
                with open(activity_path, 'rb') as file:
                    file_data = file.read()
                    fields = {
                        'file': (file_base_name, file_data, 'text/plain')
                    }

                    url_path = GARMIN_URL_DICT["garmin_connect_upload"]
                    upload_url = f"https://connectapi.{self.garthClient.domain}{url_path}"
                    self.headers['Authorization'] = str(self.garthClient.oauth2_token)
                return requests.post(upload_url, headers=self.headers, files=fields, timeout=90)
            except FileNotFoundError as e:
                logger.error(f"File not found during upload: {activity_path}")
                raise GarminUploadException(
                    f"Activity file not found: {activity_path}",
                    activity_path=activity_path
                ) from e
            except requests.RequestException as e:
                logger.error(f"Network error during upload: {str(e)}")
                raise GarminUploadException(
                    f"Network error during upload: {str(e)}",
                    activity_path=activity_path
                ) from e
            except Exception as e:
                logger.error(f"Unexpected error during upload: {str(e)}")
                raise GarminUploadException(
                    f"Unexpected error uploading activity: {str(e)}",
                    activity_path=activity_path
                ) from e
        else:
            # pass
            raise GarminUploadException(
                f"Unsupported file format: {file_extension}",
                activity_path=activity_path
            )

    @login
    def upload_activity_via_file(self, file, file_base_name):
        files = {
            "file": (file_base_name, file),
        }
        url = GARMIN_URL_DICT["garmin_connect_upload"]
        return self.garthClient.post("connectapi", url, files=files, api=True)

    # 添加辅助方法来生成序数
    @staticmethod
    def _get_ordinal(n):
        if 10 <= n % 100 <= 20:
            suffix = 'th'
        else:
            suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
        return f"{n}{suffix}"

    @login
    def upload_to_coros(self, corosClient, db, source, target):
        all_activities = self.getAllActivities()
        if all_activities is None or len(all_activities) == 0:
            logger.warning("has no garmin activities.")
            exit()
        logger.warning(f"has {len(all_activities)} all activities.")
        for activity in all_activities:
            activity_id = activity["activityId"]
            db.saveActivity(activity_id, source, target)

        un_sync_id_list = db.getUnSyncActivity(source, target)
        if un_sync_id_list is None or len(un_sync_id_list) == 0:
            logger.warning("has no unsync garmin activities.")
            exit()
        logger.warning(f"has {len(un_sync_id_list)} un sync garmin activities.")
        # 更改为大佬的oss方式
        # --------------------------------------------------------------------------------------------------------------
        file_path_list = []
        for un_sync_id in un_sync_id_list:
            # 把之前解压zip得到fit上传的代码暂时剪走了，后期知道oss怎么回事了再写
            try:
                file = self.downloadFitActivity(un_sync_id)
                file_path = os.path.join(GARMIN_CN_FIT_DIR, f"{un_sync_id}.zip")
                with open(file_path, "wb") as fb:
                    fb.write(file)

                un_sync_info = {
                    "un_sync_id": un_sync_id,
                    "file_path": file_path
                }
                # 存起来
                file_path_list.append(un_sync_info)
            except Exception as err:
                logger.warning(err)

        # 初始化计数器
        total_sync_count = len(un_sync_id_list)
        success_count = 0

        for index, un_sync_info in enumerate(file_path_list, start=1):
            try:
                # 添加动态序数日志
                ordinal = self._get_ordinal(index)
                logger.info(
                    f"------------------------- Start uploading the {ordinal} garmin_cn activity data to coros. ------------------------")
                client = None
                ## 中国区使用阿里云OSS
                if corosClient.regionId == 2:
                    client = AliOssClient()
                elif corosClient.regionId == 1 or corosClient.regionId == 3:
                    client = AwsOssClient()
                file_path = un_sync_info["file_path"]
                un_sync_id = un_sync_info["un_sync_id"]
                # 上传oss
                client.multipart_upload(file_path, f"{corosClient.userId}/{calculate_md5_file(file_path)}.zip")
                size = os.path.getsize(file_path)
                # 使用oss上传
                upload_result = corosClient.uploadActivity(
                    f"fit_zip/{corosClient.userId}/{calculate_md5_file(file_path)}.zip", calculate_md5_file(file_path),
                    f"{un_sync_id}.zip", size)
                if upload_result == '0000':
                    self.update_db_status(db, un_sync_id, source, target)
                    logger.warning(f"sync garmin activity: {un_sync_id} to coros success.")
                    # 现在是zip上传完后就删除掉zip包
                    # 解压zip包
                    file = self.downloadFitActivity(un_sync_id)
                    zip_file_path = os.path.join(GARMIN_CN_FIT_DIR, f"{un_sync_id}.zip")
                    with open(zip_file_path, "wb") as fb:
                        fb.write(file)
                    # 解压zip文件，确定一个zip里边只有一个文件，所以只处理一个文件
                    with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
                        file_list = zip_ref.namelist()
                        if file_list:  # 确保列表不为空
                            # 只解压第一个文件，因为我知道一个zip包里只有一个文件，绝对不可能多
                            filename = file_list[0]
                            zip_ref.extract(filename, GARMIN_CN_FIT_DIR)
                            os.path.join(GARMIN_CN_FIT_DIR, filename)
                    # 删除zip包
                    os.remove(zip_file_path)
                    success_count += 1  # 增加成功计数
                else:
                    logger.warning(f"Upload garmin_cn {un_sync_id} to coros error inside, status {upload_result}")
            except Exception as err:
                print(err)
                # db.updateExceptionSyncStatus(un_sync_info["un_sync_id"], source, target)
                logger.warning(f'sync garmin ${un_sync_info["un_sync_id"]} exception.')

        # 计算失败条数
        failed_count = total_sync_count - success_count
        # 返回同步统计信息
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

    @login
    def uploadToGarminGlobal(self, garminGlobalClient, db, source, target):
        all_activities = self.getAllActivities()
        if all_activities is None or len(all_activities) == 0:
            logger.warning("has no garmin_cn activities.")
            exit()
        logger.warning(f"has {len(all_activities)} all activities.")
        for activity in all_activities:
            activity_id = activity['activityId']
            db.saveActivity(activity_id, source, target)
        un_sync_id_list = db.getUnSyncActivity(source, target)
        if un_sync_id_list is None or len(un_sync_id_list) == 0:
            logger.warning("has no un garmin_cn coros activities.")
            exit()
        logger.warning(f"has {len(un_sync_id_list)} un sync garmin_cn activities.")

        # 初始化计数器
        total_sync_count = len(un_sync_id_list)
        success_count = 0

        # 在循环开始前添加索引跟踪
        for index, un_sync_id in enumerate(un_sync_id_list, start=1):
            try:
                file = self.downloadFitActivity(un_sync_id)
                zip_file_path = os.path.join(GARMIN_CN_FIT_DIR, f"{un_sync_id}.zip")
                with open(zip_file_path, "wb") as fb:
                    fb.write(file)
                # 解压zip文件，确定一个zip里边只有一个文件，所以只处理一个文件
                extracted_file_path = None
                with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
                    file_list = zip_ref.namelist()
                    if file_list:  # 确保列表不为空
                        # 只解压第一个文件
                        filename = file_list[0]
                        zip_ref.extract(filename, GARMIN_CN_FIT_DIR)
                        extracted_file_path = os.path.join(GARMIN_CN_FIT_DIR, filename)
                # 删除zip文件
                os.remove(zip_file_path)
                # 使用解压后的文件进行上传
                if extracted_file_path:
                    try:
                        upload_result = garminGlobalClient.upload_activity(extracted_file_path)
                        # 添加动态序数日志
                        ordinal = self._get_ordinal(index)
                        logger.info(
                            f"---------------------- Start uploading the {ordinal} garmin_cn activity data to garmin_global. ----------------------")
                        if upload_result.status_code == 202:
                            logger.info(f"Upload garmin_cn activity {un_sync_id} to garmin_global success.")
                            self.update_db_status(db, un_sync_id, source, target)
                            success_count += 1
                        else:
                            responseData = json.loads(upload_result.text)
                            messages = responseData['detailedImportResult']['failures'][0]['messages']
                            code = messages[0]['code']
                            content = messages[0]['content']
                            logger.warning(
                                f"Upload garmin_cn {un_sync_id} to garmin_global fake fail: (the status_code is {code}, the content is {content})")
                            if '202' == str(code):
                                logger.info(f"Upload garmin_cn activity {un_sync_id} to garmin_global success.")
                                self.update_db_status(db, un_sync_id, source, target)
                                success_count += 1
                    except Exception as err:
                        # db.updateExceptionSyncStatus(un_sync_id, source, target)
                        logger.warning(f"Upload garmin_cn {un_sync_id} to garmin_global error inside: {err}")
                else:
                    logger.warning(f"No file found in zip for activity {un_sync_id}")
            except Exception as err:
                logger.warning(f"download garmin_cn {un_sync_id} activity fail: {err}")
        # 计算失败条数
        failed_count = total_sync_count - success_count
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

    @staticmethod
    def update_db_status(db, un_sync_id, source, target):
        try:
            db.updateSyncStatus(un_sync_id, source, target)
        except Exception as err:
            print(err)
            db.updateExceptionSyncStatus(un_sync_id, source, target)
            logger.warning(f"sync garmin_global ${un_sync_id} exception.")

    @login
    def download_to_local(self):
        all_activities = self.getAllActivities()
        if all_activities == None or len(all_activities) == 0:
            logger.warning("has no garmin activities.")
            exit()

        ts_str = re.sub(r'(\.\d*)?', '', str(time.time())) + '000'
        user_download_path = os.path.join(GARMIN_CN_FIT_DIR, f"fit_{ts_str}_download")
        print('download to', user_download_path)
        if not os.path.exists(user_download_path):
            os.makedirs(user_download_path)

        user_file_data_path = os.path.join(user_download_path, 'files')
        if not os.path.exists(user_file_data_path):
            os.makedirs(user_file_data_path)

        for activity in all_activities:
            activity_id = activity["activityId"]
            self.download_tcx_local(activity_id, user_download_path, user_file_data_path)

    def download_fit_local(self, activity_id):
        try:
            # 解压zip包
            file = self.downloadFitActivity(activity_id)
            zip_file_path = os.path.join(GARMIN_CN_FIT_DIR, f"{activity_id}.zip")
            with open(zip_file_path, "wb") as fb:
                fb.write(file)
            # 解压zip文件，确定一个zip里边只有一个文件，所以只处理一个文件
            with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
                file_list = zip_ref.namelist()
                if file_list:  # 确保列表不为空
                    # 只解压第一个文件，因为我知道一个zip包里只有一个文件，绝对不可能多
                    filename = file_list[0]
                    zip_ref.extract(filename, GARMIN_CN_FIT_DIR)
                    os.path.join(GARMIN_CN_FIT_DIR, filename)
            # 删除zip包
            os.remove(zip_file_path)
        except Exception as err:
            print(err)

    def download_tcx_local(self, activity_id, user_download_path, user_file_data_path):
        try:
            file = self.downloadTcxActivity(activity_id)
            file_path = os.path.join(user_file_data_path, f"{activity_id}.tcx")
            with open(file_path, "wb") as fb:
                fb.write(file)
                logger.warning(f"loaded garmin {activity_id} {user_file_data_path}")
        except Exception as err:
            print(err)


class ActivityUploadFormat(Enum):
    FIT = auto()
    GPX = auto()
    TCX = auto()


class GarminNoLoginException(Exception):
    """Raised when rate limit is exceeded."""

    def __init__(self, status):
        """Initialize."""
        super(GarminNoLoginException, self).__init__(status)
        self.status = status
