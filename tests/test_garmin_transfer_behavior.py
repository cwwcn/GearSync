import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import garmin.garmin_cn_client as garmin_cn_module
import garmin.garmin_global_client as garmin_global_module
from garmin.garmin_cn_client import GarminCNClient
from garmin.garmin_global_client import GarminGlobalClient
from tests.support import FakeActivityDB, garmin_business_response


def build_fit_zip():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("101_ACTIVITY.fit", b"fit-data")
    return buffer.getvalue()


def build_logged_in_client(client_class):
    client = client_class.__new__(client_class)
    client.auth_method = "credentials"
    client.garthClient = SimpleNamespace(username="offline-test")
    client.getAllActivities = Mock(return_value=[{"activityId": 101}])
    client.downloadFitActivity = Mock(return_value=build_fit_zip())
    return client


class GarminToGarminBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.fit_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_garmin_cn_to_global_unzips_fit_and_accepts_http_202(self):
        source_client = build_logged_in_client(GarminCNClient)
        target_client = Mock()
        target_client.upload_activity.return_value = SimpleNamespace(
            status_code=202, text=""
        )
        db = FakeActivityDB([101])

        with patch.object(
            garmin_cn_module, "GARMIN_CN_FIT_DIR", str(self.fit_dir)
        ), patch.object(garmin_cn_module, "logger", Mock()):
            result = source_client.uploadToGarminGlobal(
                target_client, db, "GARMIN_CN", "GARMIN_GLOBAL"
            )

        extracted_fit = self.fit_dir / "101_ACTIVITY.fit"
        target_client.upload_activity.assert_called_once_with(str(extracted_fit))
        self.assertEqual(b"fit-data", extracted_fit.read_bytes())
        self.assertFalse((self.fit_dir / "101.zip").exists())
        self.assertEqual([(101, "GARMIN_CN", "GARMIN_GLOBAL")], db.synced)
        self.assertEqual((1, 1, 0), (result["total"], result["success"], result["failed"]))

    def test_garmin_global_to_cn_accepts_the_existing_business_code_202(self):
        source_client = build_logged_in_client(GarminGlobalClient)
        target_client = Mock()
        target_client.upload_activity.return_value = garmin_business_response(
            202, "already imported"
        )
        db = FakeActivityDB([101])

        with patch.object(
            garmin_global_module, "GARMIN_GLOBAL_FIT_DIR", str(self.fit_dir)
        ), patch.object(garmin_global_module, "logger", Mock()):
            result = source_client.uploadToGarminCN(
                target_client, db, "GARMIN_GLOBAL", "GARMIN_CN"
            )

        self.assertEqual([(101, "GARMIN_GLOBAL", "GARMIN_CN")], db.synced)
        self.assertEqual((1, 1, 0), (result["total"], result["success"], result["failed"]))


class GarminToCorosBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.fit_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_china_coros_region_uses_aliyun_oss_and_registers_the_same_object(self):
        source_client = build_logged_in_client(GarminCNClient)
        coros_client = Mock()
        coros_client.regionId = 2
        coros_client.userId = "coros-user"
        coros_client.uploadActivity.return_value = True
        db = FakeActivityDB([101])
        oss_client = Mock()

        with patch.object(
            garmin_cn_module, "GARMIN_CN_FIT_DIR", str(self.fit_dir)
        ), patch.object(
            garmin_cn_module, "AliOssClient", return_value=oss_client
        ) as ali_oss_class, patch.object(
            garmin_cn_module, "AwsOssClient"
        ) as aws_oss_class, patch.object(
            garmin_cn_module, "calculate_md5_file", return_value="fit-md5"
        ), patch.object(garmin_cn_module, "logger", Mock()):
            result = source_client.upload_to_coros(
                coros_client, db, "GARMIN_CN", "COROS"
            )

        zip_path = self.fit_dir / "101.zip"
        ali_oss_class.assert_called_once_with()
        aws_oss_class.assert_not_called()
        oss_client.multipart_upload.assert_called_once_with(
            str(zip_path), "coros-user/fit-md5.zip"
        )
        coros_client.uploadActivity.assert_called_once_with(
            "fit_zip/coros-user/fit-md5.zip",
            "fit-md5",
            "101.zip",
            len(build_fit_zip()),
        )
        self.assertFalse(zip_path.exists())
        self.assertEqual(b"fit-data", (self.fit_dir / "101_ACTIVITY.fit").read_bytes())
        self.assertEqual([(101, "GARMIN_CN", "COROS")], db.synced)
        self.assertEqual((1, 1, 0), (result["total"], result["success"], result["failed"]))


if __name__ == "__main__":
    unittest.main()
