from datetime import datetime, timezone
from pathlib import Path

import garth
import requests
from garth.exc import GarthHTTPError

from .garmin_url_dict import GARMIN_URL_DICT
from sync_types import Activity, Receipt, Rejected, SyncError, remote_id


def import_receipt(response, *, lookup=False):
    status = response.status_code
    operation = 'Garmin import lookup' if lookup else 'Garmin import'
    if status not in (200, 201, 202, 400, 409):
        error_type = Rejected if not lookup and status in (401, 403, 413, 415, 422, 429) else SyncError
        raise error_type(f'{operation}: HTTP {status}')
    try:
        payload = response.json()
    except (ValueError, UnicodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    detail = payload.get('detailedImportResult', payload)
    if not isinstance(detail, dict):
        return Receipt()
    task_id = remote_id(detail.get('uploadId') or payload.get('uploadId'))
    successes = detail.get('successes')
    failures = detail.get('failures')
    if status in (200, 201, 202) and isinstance(successes, list) and len(successes) == 1 and not failures:
        success = successes[0]
        if isinstance(success, dict):
            return Receipt(task_id, remote_id(success.get('internalId')))
    if status in (400, 409) and not successes and isinstance(failures, list) and len(failures) == 1:
        failure = failures[0]
        if isinstance(failure, dict) and isinstance(failure.get('messages'), list) and any(
            isinstance(message, dict) and (
                message.get('code') in (202, '202') or 'duplicate' in str(message.get('content', '')).lower()
            ) for message in failure['messages']
        ):
            return Receipt(task_id, remote_id(failure.get('internalId')))
    if status == 400:
        raise SyncError(f'{operation}: HTTP 400; import outcome not confirmed')
    return Receipt(task_id)


class GarminClient:
    def __init__(self, email_or_secret, password=None):
        self.account = email_or_secret
        self.password = password
        self.garthClient = garth.Client(domain=self.domain)
        self.upload_session = requests.Session()
        self.headers = {'Origin': f'https://connect.{self.domain}', 'Nk': 'NT'}

    def ensure_session(self, *, force=False):
        client = self.garthClient
        try:
            if client.oauth1_token is None:
                if self.password is None:
                    client.loads(self.account)
                else:
                    client.login(self.account, self.password)
            if client.domain != self.domain:
                raise SyncError('Garmin token belongs to a different region')
            if force or client.oauth2_token is None or client.oauth2_token.expired:
                client.refresh_oauth2()
        except SyncError:
            raise
        except GarthHTTPError as error:
            response = error.error.response
            if response is not None and response.status_code == 401 and self.password is not None:
                try:
                    client.login(self.account, self.password)
                except Exception as login_error:
                    raise SyncError(f'Garmin {self.domain} reauthentication failed') from login_error
            else:
                code = f' (HTTP {response.status_code})' if response is not None else ''
                raise SyncError(f'Garmin {self.domain} authentication failed{code}') from error
        except Exception as error:
            raise SyncError(f'Garmin {self.domain} authentication failed') from error

    def _read(self, operation, call):
        self.ensure_session()
        for attempt in range(2):
            try:
                return call()
            except GarthHTTPError as error:
                response = error.error.response
                code = response.status_code if response is not None else None
                if code == 401 and attempt == 0:
                    self.ensure_session(force=True)
                    continue
                raise SyncError(f'{operation}: HTTP {code}' if code else f'{operation}: network failure') from error
            except (requests.RequestException, ValueError) as error:
                raise SyncError(f'{operation}: invalid response or network failure') from error

    def account_id(self):
        profile = self._read('Garmin profile', lambda: self.garthClient.profile)
        if not isinstance(profile, dict):
            raise SyncError('Garmin profile response is invalid')
        identity = remote_id(profile.get('profileId') or profile.get('id') or profile.get('userName'))
        if not identity:
            raise SyncError('Garmin profile has no stable identity')
        return f'{self.domain}:{identity}'

    @staticmethod
    def _activity(item):
        if not isinstance(item, dict):
            raise SyncError('Garmin activity list contains invalid metadata')
        identity = remote_id(item.get('activityId'))
        timestamp = item.get('beginTimestamp')
        if not identity or type(timestamp) is not int or timestamp <= 0:
            raise SyncError('Garmin activity list contains invalid metadata')
        return Activity(identity, timestamp)

    def list_page(self, page, size):
        payload = self._read('Garmin activity list', lambda: self.garthClient.connectapi(
            GARMIN_URL_DICT['garmin_connect_activities'], params={'start': page * size, 'limit': size},
        ))
        if not isinstance(payload, list):
            raise SyncError('Garmin activity list has no activity array')
        return [self._activity(item) for item in payload]

    def get_activity(self, activity_id):
        payload = self._read('Garmin activity detail', lambda: self.garthClient.connectapi(
            f'/activity-service/activity/{activity_id}',
        ))
        if isinstance(payload, dict) and 'beginTimestamp' not in payload:
            summary = payload.get('summaryDTO', {})
            if isinstance(summary, dict) and isinstance(summary.get('startTimeGMT'), str):
                try:
                    stamp = datetime.fromisoformat(summary['startTimeGMT'].replace('Z', '+00:00'))
                except ValueError as error:
                    raise SyncError('Garmin activity detail time is invalid') from error
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                payload = dict(payload, beginTimestamp=int(stamp.timestamp() * 1000))
        activity = self._activity(payload)
        if activity.id != activity_id:
            raise SyncError('Garmin activity details do not match the requested ID')
        return activity

    def download_activity(self, activity):
        path = f"{GARMIN_URL_DICT['garmin_connect_fit_download']}/{activity.id}"
        return self._read('Garmin download', lambda: self.garthClient.download(path))

    def upload_activity(self, activity_path):
        try:
            self.ensure_session()
        except SyncError as error:
            raise Rejected(str(error)) from error
        path = Path(activity_path)
        url = f"https://connectapi.{self.domain}{GARMIN_URL_DICT['garmin_connect_upload']}"
        try:
            for attempt in range(2):
                headers = dict(self.headers, Authorization=str(self.garthClient.oauth2_token))
                try:
                    stream = path.open('rb')
                except OSError as error:
                    raise Rejected('Garmin import could not open the staged file') from error
                with stream:
                    response = self.upload_session.post(
                        url, headers=headers, files={'file': (path.name, stream, 'application/octet-stream')},
                        timeout=(10, 90), allow_redirects=False,
                    )
                if response.status_code != 401 or attempt == 1:
                    return import_receipt(response)
                try:
                    self.ensure_session(force=True)
                except SyncError as error:
                    raise Rejected('Garmin import: HTTP 401; session refresh failed') from error
        except requests.RequestException as error:
            raise SyncError('Garmin import network failure; result unknown') from error

    def lookup_import(self, task_id):
        path = f"{GARMIN_URL_DICT['garmin_connect_upload']}/{task_id}"
        response = self._read('Garmin import lookup', lambda: self.garthClient.get('connectapi', path, api=True))
        receipt = import_receipt(response, lookup=True)
        return receipt.remote_id if receipt.task_id == task_id else ''


class GarminCNClient(GarminClient):
    domain = 'garmin.cn'


class GarminGlobalClient(GarminClient):
    domain = 'garmin.com'
