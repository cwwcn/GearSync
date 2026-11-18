import oss2
import os

from oss2 import SizedFileAdapter, determine_part_size
from oss2.models import PartInfo

from conf.logger_config import get_logger


logger = get_logger(__name__)

class AliOssClient:
    def __init__(self, credentials):
        self.bucket = credentials['Bucket']
        self.region = credentials['Region']
        self.security_token = credentials['SecurityToken']
        self.access_key_id = credentials['AccessKeyId']
        self.access_key_secret = credentials['AccessKeySecret']
        self.client = None
        self.initClient()

    def initClient(self):
        auth = oss2.StsAuth(self.access_key_id, self.access_key_secret, self.security_token)
        self.client = oss2.Bucket(auth, f"https://{self.region}.aliyuncs.com", self.bucket)

    def multipart_upload(self, filePath, fileName):
        key = f"fit_zip/{fileName}"
        total_size = os.path.getsize(filePath)
        part_size = determine_part_size(total_size, preferred_size=1024 * 1024)
        parts = []
        init_multipart_upload_result = self.client.init_multipart_upload(key)
        if init_multipart_upload_result.status != 200:
            raise AliOssError("初始化阿里云分片上传异常")
        upload_id = init_multipart_upload_result.upload_id
        try:
            with open(filePath, 'rb') as fileobj:
                offset = 0
                while offset < total_size:
                    part_number = len(parts) + 1
                    chunk_size = min(part_size, total_size - offset)
                    result = self.client.upload_part(key, upload_id, part_number, SizedFileAdapter(fileobj, chunk_size))
                    parts.append(PartInfo(part_number, result.etag))
                    offset += chunk_size
            result = self.client.complete_multipart_upload(key, upload_id, parts)
            if not 200 <= result.status < 300:
                raise AliOssError('OSS multipart completion failed')
        except Exception:
            try:
                self.client.abort_multipart_upload(key, upload_id)
            except Exception as cleanup_error:
                logger.warning('OSS could not abort an unfinished upload (%s)', type(cleanup_error).__name__)
            raise
        return key


class StsTokenError(Exception):

    def __init__(self, status):
        """Initialize."""
        super(StsTokenError, self).__init__(status)
        self.status = status


class AliOssError(Exception):
    def __init__(self, status):
        """Initialize."""
        super(AliOssError, self).__init__(status)
        self.status = status
