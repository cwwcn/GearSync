import boto3

from boto3.s3.transfer import TransferConfig


class AwsOssClient:
    def __init__(self, credentials):
        self.bucket = credentials['Bucket']
        self.credentials = credentials
        self.client = None
        self.initClient()

    def initClient(self):
        self.client = boto3.client(
            "s3",
            aws_access_key_id=self.credentials["AccessKeyId"],
            aws_secret_access_key=self.credentials["SecretAccessKey"],
            aws_session_token=self.credentials["SessionToken"],
            region_name=self.credentials['Region'],
            endpoint_url=f"https://s3.{self.credentials['Region']}.amazonaws.com",
        )

    def multipart_upload(self, filePath, fileName):
        # 配置上传选项
        config = TransferConfig(
            multipart_threshold=1024 * 1024 * 5,  # 分片上传的阈值（5MB）
            max_concurrency=4,  # 并发数
            multipart_chunksize=1024 * 1024 * 5,  # 分片大小（5MB）
            use_threads=True  # 使用多线程
        )

        key = f"fit_zip/{fileName}"
        self.client.upload_file(filePath, Bucket=self.bucket, Key=key, Config=config)
        return key
