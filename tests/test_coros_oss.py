import base64
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import urllib3

from coros.coros_client import CorosClient
from coros.region_config import REGIONCONFIG
from oss.ali_oss_client import AliOssClient
from oss.aws_oss_client import AwsOssClient
from oss.sts_token_error import StsTokenError


def make_credentials(service="aliyun"):
    credentials = {
        "AccessKeyId": "test-key-id",
        "Bucket": "coros-oss" if service == "aliyun" else "eu-coros",
        "Region": "oss-cn-beijing" if service == "aliyun" else "eu-central-1",
    }
    if service == "aliyun":
        credentials.update(AccessKeySecret="test-secret", SecurityToken="test-token")
    else:
        credentials.update(SecretAccessKey="test-secret", SessionToken="test-token")
    return credentials


def make_response(credentials, service="aliyun"):
    encoded = base64.b64encode(json.dumps(credentials).encode()).decode()
    return SimpleNamespace(
        status=200,
        headers={"Content-Type": "application/json"},
        data=json.dumps({
            "code": 200,
            "data": {"credentials": "9y78gpoERW4lBNYL" + encoded, "service": service, "v": 2},
        }).encode(),
    )


class CorosOssCredentialsTests(unittest.TestCase):
    def setUp(self):
        self.client = CorosClient("runner@example.test", "test-password")
        self.client.accessToken = "test-login-token"
        self.client.req = Mock()

    def test_uses_regional_training_hub_and_authenticated_cookie(self):
        for region_id, service in ((1, "aws"), (2, "aliyun"), (3, "aws")):
            with self.subTest(region_id=region_id):
                self.client.regionId = region_id
                credentials = make_credentials(service)
                self.client.req.request.reset_mock()
                self.client.req.request.return_value = make_response(credentials, service)

                self.assertEqual(credentials, self.client.getOssCredentials())

                request_args = self.client.req.request.call_args
                self.assertEqual(
                    ('GET', REGIONCONFIG[region_id]['hostname'] + '/api/proxy/oss/sts'),
                    request_args.args,
                )
                self.assertEqual(
                    'CPL-coros-token=test-login-token', request_args.kwargs['headers']['Cookie']
                )
                self.assertFalse(request_args.kwargs['redirect'])
                self.assertEqual(30, request_args.kwargs['timeout'])

    def test_http_errors_report_status_without_exposing_response_body(self):
        self.client.regionId = 2
        for status in (401, 404, 503):
            with self.subTest(status=status):
                self.client.req.request.return_value = SimpleNamespace(
                    status=status,
                    headers={"Content-Type": "text/html"},
                    data=b"<html>test-login-token test-secret</html>",
                )
                with patch.object(self.client, 'login'), self.assertRaises(StsTokenError) as error:
                    self.client.getOssCredentials()
                self.assertIn(f"HTTP {status}", str(error.exception))
                self.assertIn("text/html", str(error.exception))
                self.assertNotIn("test-login-token", str(error.exception))
                self.assertNotIn("test-secret", str(error.exception))

    def test_empty_html_and_invalid_credential_responses_raise_sts_errors(self):
        self.client.regionId = 2
        malformed = make_credentials()
        malformed.pop("SecurityToken")
        bodies = [
            b"", b"<html>error</html>", b"null", b"[]",
            b'{"code":500}', b'{"code":200,"data":null}',
            b'{"code":200,"data":{"credentials":null,"service":"aliyun"}}',
            b'{"code":200,"data":{"credentials":"invalid","service":"aliyun"}}',
            make_response(malformed).data,
            make_response([]).data,
        ]
        for body in bodies:
            with self.subTest(body=body):
                self.client.req.request.return_value = SimpleNamespace(
                    status=200, headers={"Content-Type": "text/html"}, data=body
                )
                with self.assertRaises(StsTokenError):
                    self.client.getOssCredentials()

    def test_network_failure_raises_sts_error(self):
        self.client.regionId = 2
        self.client.req.request.side_effect = urllib3.exceptions.HTTPError("network unavailable")
        with self.assertRaisesRegex(StsTokenError, "network error"):
            self.client.getOssCredentials()


class OssInitializationTests(unittest.TestCase):
    def test_aliyun_uses_decoded_sts_credentials_and_region(self):
        credentials = make_credentials()
        with patch("oss.ali_oss_client.oss2.StsAuth") as auth, patch(
            "oss.ali_oss_client.oss2.Bucket"
        ) as bucket:
            client = AliOssClient(credentials)
        auth.assert_called_once_with("test-key-id", "test-secret", "test-token")
        bucket.assert_called_once_with(auth.return_value, "https://oss-cn-beijing.aliyuncs.com", "coros-oss")
        self.assertIs(client.client, bucket.return_value)

    def test_aws_uses_decoded_sts_credentials_and_region(self):
        credentials = make_credentials("aws")
        with patch("oss.aws_oss_client.boto3.client") as s3:
            client = AwsOssClient(credentials)
        s3.assert_called_once_with(
            "s3", aws_access_key_id="test-key-id", aws_secret_access_key="test-secret",
            aws_session_token="test-token", region_name="eu-central-1",
            endpoint_url="https://s3.eu-central-1.amazonaws.com",
        )
        self.assertIs(client.client, s3.return_value)

    def test_aws_upload_error_is_propagated(self):
        with patch('oss.aws_oss_client.boto3.client') as s3:
            s3.return_value.upload_file.side_effect = TimeoutError('fixture')
            with self.assertRaises(TimeoutError):
                AwsOssClient(make_credentials('aws')).multipart_upload('source', 'fixture.zip')

    def test_ali_abort_preserves_the_original_failure(self):
        with tempfile.TemporaryDirectory() as directory, patch('oss.ali_oss_client.oss2.Bucket') as bucket:
            path = Path(directory) / 'payload.zip'
            path.write_bytes(b'dummy payload')
            sdk = bucket.return_value
            sdk.init_multipart_upload.return_value = SimpleNamespace(status=200, upload_id='one')
            sdk.upload_part.side_effect = TimeoutError('part timed out')
            sdk.abort_multipart_upload.side_effect = OSError('cleanup failed')
            with self.assertRaisesRegex(TimeoutError, 'part timed out'):
                AliOssClient(make_credentials()).multipart_upload(path, 'fixture.zip')
            sdk.abort_multipart_upload.assert_called_once_with('fit_zip/fixture.zip', 'one')
            sdk.complete_multipart_upload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
