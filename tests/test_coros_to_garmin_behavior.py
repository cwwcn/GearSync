import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import urllib3

from coros.coros_client import CorosClient
from sync_types import Activity, ObjectUpload, Receipt, Rejected, SyncError


def response(status, body):
    return SimpleNamespace(status=status, data=body if isinstance(body, bytes) else json.dumps(body).encode())


class CorosTransportTests(unittest.TestCase):
    def setUp(self):
        self.client = CorosClient('fixture@example.test', 'dummy')
        self.client.accessToken = 'fixture-token'
        self.client.userId = 'fixture-id'
        self.client.regionId = 2
        self.client.teamapi = 'https://teamcnapi.coros.com'
        self.client.req = Mock()
        self.activity = Activity('21', 1700000000000, '100')
        self.upload = ObjectUpload('fit_zip/fixture-id/checksum.zip', 'credential-bucket', 'aliyun', 'checksum', 123)

    def test_list_expired_credentials_are_not_reported_as_empty(self):
        self.client.login = Mock()
        self.client.req.request.return_value = response(401, {'result': 'invalid'})
        with self.assertRaisesRegex(SyncError, 'HTTP 401'):
            self.client.list_page(0, 100)
        self.client.login.assert_called_once()
        self.assertEqual(2, self.client.req.request.call_count)

    def test_import_html_502_is_unconfirmed_without_automatic_replay(self):
        self.client.req.request.return_value = response(502, b'<html>gateway</html>')
        with self.assertRaisesRegex(SyncError, 'HTTP 502') as context:
            self.client.submit_import(self.upload, self.activity)
        self.assertNotIsInstance(context.exception, Rejected)
        self.client.req.request.assert_called_once()
        self.assertFalse(self.client.req.request.call_args.kwargs['retries'])

    def test_import_uses_storage_receipt_and_preserves_task_id(self):
        self.client.req.request.return_value = response(200, {'result': '0000', 'data': {'status': 2, 'taskId': 12}})
        self.assertEqual(Receipt('12'), self.client.submit_import(self.upload, self.activity))
        args = self.client.req.request.call_args.kwargs
        self.assertEqual('credential-bucket', json.loads(args['fields']['jsonParameter'])['bucket'])

    def test_task_status_requires_matching_task_and_target_id(self):
        self.client.req.request.return_value = response(200, {'result': '0000', 'data': {
            'status': 2, 'taskId': 12, 'labelId': '51', 'taskErrorList': [],
        }})
        self.assertEqual('51', self.client.lookup_import('12'))
        self.assertEqual('', self.client.lookup_import('99'))

    def test_read_links_are_resolved_on_demand_without_leaking_token_on_redirect(self):
        redirect = Mock(status=302, headers={'Location': 'https://blob.example.test/signed'})
        content = Mock(status=200)
        content.read.return_value = b'test-fit'
        self.client.req.request.side_effect = [
            response(200, {'result': '0000', 'data': {'fileUrl': self.client.teamapi + '/blob'}}), redirect, content,
        ]
        self.assertEqual(b'test-fit', self.client.download_activity(self.activity))
        calls = self.client.req.request.call_args_list
        self.assertEqual('fixture-token', calls[1].kwargs['headers']['accesstoken'])
        self.assertEqual({}, calls[2].kwargs['headers'])
        self.assertFalse(calls[2].kwargs['redirect'])
        redirect.release_conn.assert_called_once()
        content.release_conn.assert_called_once()

    def test_read_timeout_is_reported_as_failure(self):
        self.client.req.request.side_effect = urllib3.exceptions.ReadTimeoutError(None, None, 'timed out')
        with self.assertRaisesRegex(SyncError, 'network failure'):
            self.client.list_page(0, 100)
