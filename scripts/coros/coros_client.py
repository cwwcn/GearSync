import hashlib
import json
from pathlib import Path
from urllib.parse import quote, urlencode, urljoin, urlsplit

import certifi
import urllib3

from activity_files import MAX_BYTES
from oss.ali_oss_client import AliOssClient
from oss.aws_oss_client import AwsOssClient
from oss.sts_token_error import StsTokenError
from sync_types import Activity, ObjectUpload, Receipt, Rejected, SyncError, remote_id
from utils.coros_oss_credients_utils import decode
from utils.md5_utils import calculate_md5_file

from .region_config import REGIONCONFIG


TIMEOUT = urllib3.Timeout(connect=10, read=30)
READ_RETRIES = urllib3.Retry(total=2, backoff_factor=0.5, status_forcelist=(408, 429, 500, 502, 503, 504),
                             backoff_max=5, respect_retry_after_header=False, raise_on_status=False)
COROS_CN = REGIONCONFIG[2]


class CorosLoginError(SyncError):
    pass


class CorosClient:
    def __init__(self, email, password):
        self.email = email
        self.password = password
        self.req = urllib3.PoolManager(cert_reqs='CERT_REQUIRED', ca_certs=certifi.where())
        self.accessToken = None
        self.userId = None
        self.regionId = None
        self.teamapi = None

    @staticmethod
    def _headers(region):
        return {
            'Accept': 'application/json, text/plain, */*',
            'User-Agent': 'Mozilla/5.0',
            'referer': region['hostname'] + '/',
            'origin': region['hostname'],
        }

    def getHeaders(self):
        return dict(self._headers(REGIONCONFIG[self.regionId]), accesstoken=self.accessToken)

    @staticmethod
    def _json(response, operation):
        try:
            payload = json.loads(response.data)
        except (ValueError, UnicodeError) as error:
            raise SyncError(f'{operation}: invalid JSON (HTTP {response.status})') from error
        if not isinstance(payload, dict):
            raise SyncError(f'{operation}: invalid JSON object')
        return payload

    def _request(self, operation, method, url, *, read=False, **kwargs):
        try:
            return self.req.request(method, url, timeout=TIMEOUT, redirect=False,
                                    retries=READ_RETRIES if read and method == 'GET' else False, **kwargs)
        except urllib3.exceptions.HTTPError as error:
            raise SyncError(f'{operation}: network failure') from error

    def login(self):
        body = json.dumps({'account': self.email, 'pwd': hashlib.md5(self.password.encode()).hexdigest(),
                           'accountType': 2})
        headers = dict(self._headers(COROS_CN), **{'Content-Type': 'application/json;charset=UTF-8'})
        response = self._request('COROS login', 'POST', COROS_CN['teamapi'] + '/account/login',
                                 headers=headers, body=body)
        if response.status != 200:
            raise CorosLoginError(f'COROS login: HTTP {response.status}')
        payload = self._json(response, 'COROS login')
        data = payload.get('data')
        if payload.get('result') != '0000' or not isinstance(data, dict):
            raise CorosLoginError('COROS login rejected')
        identity = remote_id(data.get('userId'))
        token = data.get('accessToken')
        region_value = remote_id(data.get('regionId'))
        region_id = int(region_value) if region_value.isdecimal() else None
        if not identity or not isinstance(token, str) or not token or region_id not in REGIONCONFIG:
            raise CorosLoginError('COROS login returned invalid account or region data')
        if self.userId is not None and (identity != self.userId or region_id != self.regionId):
            raise CorosLoginError('COROS account or region changed during synchronization')
        self.accessToken = token
        self.userId = identity
        self.regionId = region_id
        self.teamapi = REGIONCONFIG[region_id]['teamapi']

    def ensure_session(self):
        if self.accessToken is None:
            self.login()

    def account_id(self):
        self.ensure_session()
        return f'{self.regionId}:{self.userId}'

    def _api_read(self, operation, method, path, **kwargs):
        self.ensure_session()
        for attempt in range(2):
            response = self._request(operation, method, self.teamapi + path, read=True,
                                     headers=self.getHeaders(), **kwargs)
            if response.status == 401 and attempt == 0:
                self.login()
                continue
            if response.status != 200:
                raise SyncError(f'{operation}: HTTP {response.status}')
            payload = self._json(response, operation)
            if payload.get('result') != '0000' or not isinstance(payload.get('data'), dict):
                raise SyncError(f'{operation}: unexpected business response')
            return payload['data']

    def getOssCredentials(self):
        self.ensure_session()
        region = REGIONCONFIG[self.regionId]
        for attempt in range(2):
            headers = self.getHeaders()
            headers['Cookie'] = f"{region['TOKEN']}={quote(self.accessToken, safe='')}"
            try:
                response = self.req.request('GET', f"{region['hostname']}/api/proxy/oss/sts",
                                            headers=headers, timeout=30, redirect=False, retries=READ_RETRIES)
            except urllib3.exceptions.HTTPError as error:
                raise StsTokenError('COROS OSS STS request failed due to a network error.') from error
            if response.status != 401 or attempt == 1:
                break
            try:
                self.login()
            except SyncError as error:
                raise StsTokenError('COROS OSS STS request failed (HTTP 401); reauthentication failed.') from error

        content_type = response.headers.get('Content-Type', 'unknown').split(';', 1)[0]
        if content_type not in ('application/json', 'text/html', 'text/plain'):
            content_type = 'unknown'
        if response.status != 200:
            raise StsTokenError(f'COROS OSS STS request failed (HTTP {response.status}, Content-Type {content_type}).')
        try:
            payload = self._json(response, 'COROS OSS STS')
        except SyncError as error:
            raise StsTokenError(str(error)) from error
        if payload.get('code') != 200:
            raise StsTokenError('COROS OSS STS did not return business code 200.')
        try:
            encoded = payload['data']['credentials']
            if not isinstance(encoded, str):
                raise ValueError('Invalid encoded OSS credentials')
            credentials = decode(encoded)
            fields = {'aliyun': ('AccessKeySecret', 'SecurityToken'), 'aws': ('SecretAccessKey', 'SessionToken')}
            required_keys = ('AccessKeyId', 'Bucket', 'Region') + fields[payload['data']['service']]
            if not isinstance(credentials, dict) or any(
                not isinstance(credentials.get(key), str) or not credentials[key] for key in required_keys
            ):
                raise ValueError('Missing OSS credential fields')
            return {key: credentials[key] for key in required_keys}
        except (KeyError, TypeError, ValueError, UnicodeError) as error:
            raise StsTokenError('COROS OSS STS returned invalid credentials.') from error

    @staticmethod
    def _activity(item):
        if not isinstance(item, dict):
            raise SyncError('COROS activity metadata is invalid')
        identity = remote_id(item.get('labelId'))
        sport = remote_id(item.get('sportType'))
        timestamp = remote_id(item.get('startTime'))
        if not identity or not sport or not timestamp.isdecimal() or int(timestamp) <= 0:
            raise SyncError('COROS activity metadata is invalid')
        timestamp = int(timestamp)
        return Activity(identity, timestamp * 1000 if timestamp < 10**11 else timestamp, sport)

    def list_page(self, page, size):
        params = urlencode({'size': size, 'pageNumber': page + 1, 'modeList': ''})
        data = self._api_read('COROS activity list', 'GET', f'/activity/query?{params}')
        items = data.get('dataList')
        if not isinstance(items, list):
            raise SyncError('COROS activity list has no activity array')
        return [self._activity(item) for item in items]

    def download_activity(self, activity):
        params = urlencode({'labelId': activity.id, 'sportType': activity.sport, 'fileType': 4})
        data = self._api_read('COROS download link', 'POST', f'/activity/detail/download?{params}', fields={})
        url = data.get('fileUrl')
        if not isinstance(url, str):
            raise SyncError('COROS did not return a download link')
        for attempt in range(4):
            parsed = urlsplit(url)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None:
                raise SyncError('COROS returned an invalid download URL')
            headers = self.getHeaders() if parsed.netloc == urlsplit(self.teamapi).netloc else {}
            response = self._request('COROS download', 'GET', url, read=True, headers=headers, preload_content=False)
            try:
                if response.status in (301, 302, 303, 307, 308) and response.headers.get('Location'):
                    url = urljoin(url, response.headers['Location'])
                    continue
                if response.status != 200:
                    raise SyncError(f'COROS download: HTTP {response.status}')
                return response.read(MAX_BYTES + 1)
            except urllib3.exceptions.HTTPError as error:
                raise SyncError('COROS download: read failed') from error
            finally:
                response.close()
                response.release_conn()
        raise SyncError('COROS download exceeded the redirect limit')

    def upload_object(self, path):
        self.ensure_session()
        path = Path(path)
        checksum = calculate_md5_file(path)
        credentials = self.getOssCredentials()
        is_aws = 'SessionToken' in credentials
        service = 'aws' if is_aws else 'aliyun'
        uploader = (AwsOssClient if is_aws else AliOssClient)(credentials)
        try:
            key = uploader.multipart_upload(path, f'{self.userId}/{checksum}.zip')
        except Exception as error:
            raise SyncError(f'COROS {service} object upload failed ({type(error).__name__})') from error
        if key != f'fit_zip/{self.userId}/{checksum}.zip':
            raise SyncError(f'COROS {service} did not confirm the expected object key')
        return ObjectUpload(key, credentials['Bucket'], service, checksum, path.stat().st_size)

    def submit_import(self, uploaded, activity):
        data = {'source': 1, 'timezone': 32, 'bucket': uploaded.bucket, 'md5': uploaded.md5,
                'size': uploaded.size, 'object': uploaded.key, 'serviceName': uploaded.service,
                'oriFileName': f'{activity.id}.zip'}
        for attempt in range(2):
            response = self._request('COROS import', 'POST', self.teamapi + '/activity/fit/import',
                                     fields={'jsonParameter': json.dumps(data)}, headers=self.getHeaders())
            if response.status != 401 or attempt == 1:
                break
            try:
                self.login()
            except SyncError as error:
                raise Rejected('COROS import: HTTP 401; reauthentication failed') from error
        if response.status not in (200, 201, 202):
            error_type = Rejected if response.status in (401, 403, 413, 415, 422, 429) else SyncError
            raise error_type(f'COROS import: HTTP {response.status}')
        payload = self._json(response, 'COROS import')
        result = payload.get('data')
        if payload.get('result') != '0000' or not isinstance(result, dict):
            raise SyncError('COROS import returned an unconfirmed business result')
        task = remote_id(result.get('taskId'))
        completed = result.get('status') in (2, '2') and not result.get('taskErrorList')
        identity = remote_id(result.get('labelId')) if completed else ''
        return Receipt(task, identity)

    def lookup_import(self, task_id):
        params = urlencode({'taskId': task_id})
        data = self._api_read('COROS import lookup', 'GET',
                              f'/activity/fit/exportSportImportTaskErrorList?{params}')
        if remote_id(data.get('taskId')) != task_id:
            return ''
        if data.get('taskErrorList'):
            raise SyncError('COROS import task reports errors')
        if data.get('status') not in (2, '2'):
            return ''
        return remote_id(data.get('labelId'))
