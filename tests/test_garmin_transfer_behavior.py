import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import requests

from garmin.garmin_client import GarminCNClient, GarminGlobalClient, import_receipt
from sync_types import Receipt, SyncError


def response(status, body=None):
    result = Mock(status_code=status)
    if body is None:
        result.json.side_effect = ValueError('empty')
    else:
        result.json.return_value = body
    return result


class GarminTransferTests(unittest.TestCase):
    def test_accepted_is_distinct_from_confirmed(self):
        self.assertEqual(Receipt(), import_receipt(response(202)))
        self.assertEqual(Receipt('13'), import_receipt(response(202, {'uploadId': 13})))
        self.assertEqual(Receipt('13', '42'), import_receipt(response(202, {'detailedImportResult': {
            'uploadId': 13, 'successes': [{'internalId': 42}], 'failures': [],
        }})))

    def test_duplicate_requires_a_correlated_internal_id(self):
        self.assertEqual(Receipt(), import_receipt(response(400, {'detailedImportResult': {
                'failures': [{'messages': [{'code': 202}]}],
        }})))
        self.assertEqual(Receipt(remote_id='42'), import_receipt(response(409, {'detailedImportResult': {
            'failures': [{'internalId': 42, 'messages': [{'code': 202}]}],
        }})))
        self.assertEqual(Receipt(), import_receipt(response(409, {'detailedImportResult': {
            'failures': [{'internalId': 42, 'messages': [{'code': 999}]}],
        }})))

    def test_upload_uses_fresh_credentials_in_both_regions_and_does_not_replay_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '321.fit'
            path.write_bytes(b'test multipart bytes')
            for adapter in (GarminCNClient, GarminGlobalClient):
                with self.subTest(adapter=adapter.__name__):
                    client = adapter('test-token')
                    self.assertEqual(client.domain, client.garthClient.domain)
                    garth_client = Mock(domain=client.domain, oauth1_token=object(),
                                        oauth2_token=SimpleNamespace(expired=True))
                    garth_client.refresh_oauth2.side_effect = lambda: setattr(
                        garth_client, 'oauth2_token', SimpleNamespace(expired=False)
                    )
                    client.garthClient = garth_client
                    client.upload_session = Mock()
                    client.upload_session.post.side_effect = requests.ReadTimeout('unknown result')
                    with self.assertRaisesRegex(SyncError, 'result unknown'):
                        client.upload_activity(path)
                    garth_client.refresh_oauth2.assert_called_once_with()
                    client.upload_session.post.assert_called_once()
                    request = client.upload_session.post.call_args
                    self.assertIn(client.domain, request.args[0])
                    self.assertFalse(request.kwargs['allow_redirects'])
                    self.assertEqual(str(garth_client.oauth2_token), request.kwargs['headers']['Authorization'])

    def test_conclusive_401_refreshes_and_retries_once(self):
        client = GarminCNClient('test-token')
        client.ensure_session = Mock()
        client.garthClient.oauth2_token = 'test-token'
        client.upload_session = Mock()
        client.upload_session.post.side_effect = [response(401), response(202)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '321.fit'
            path.touch()
            self.assertEqual(Receipt(), client.upload_activity(path))
        self.assertEqual(2, client.upload_session.post.call_count)
        client.ensure_session.assert_called_with(force=True)

    def test_wrong_region_token_is_rejected_before_network_use(self):
        client = GarminCNClient('test-token')
        client.garthClient = Mock(domain='garmin.com', oauth1_token=object())
        with self.assertRaisesRegex(SyncError, 'different region'):
            client.account_id()
        client.garthClient.refresh_oauth2.assert_not_called()

    def test_status_lookup_only_trusts_matching_task(self):
        client = GarminCNClient('token')
        client.ensure_session = Mock()
        client.garthClient = Mock()
        client.garthClient.get.return_value = response(200, {'uploadId': 555, 'successes': [{'internalId': 42}]})
        self.assertEqual('', client.lookup_import('12'))
        self.assertEqual('42', client.lookup_import('555'))
