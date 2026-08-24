import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from coros.coros_client import CorosClient
from tests.support import FakeActivityDB, garmin_business_response


class CorosToGarminBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.fit_dir = Path(self.temp_dir.name)
        self.client = CorosClient.__new__(CorosClient)
        self.client.getAllActivities = Mock(
            return_value=[("101", "https://download.example.test/101.fit", 1)]
        )
        self.client.download = Mock(return_value=SimpleNamespace(data=b"fit-data"))

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_sync_with_response(self, response):
        db = FakeActivityDB([101])
        garmin_client = Mock()
        garmin_client.upload_activity.return_value = response

        with patch(
            "coros.coros_client.COROS_FIT_DIR", str(self.fit_dir)
        ), patch("coros.coros_client.logger", Mock()):
            result = self.client.uploadToGarmin(
                garmin_client, db, "COROS", "GARMIN_CN"
            )

        return result, db, garmin_client

    def test_http_202_marks_the_activity_as_synced(self):
        response = SimpleNamespace(status_code=202, text="")

        result, db, garmin_client = self.run_sync_with_response(response)

        self.assertEqual({"total": 1, "success": 1, "failed": 0}, {
            key: result[key] for key in ("total", "success", "failed")
        })
        self.assertEqual([(101, "COROS", "GARMIN_CN")], db.synced)
        garmin_client.upload_activity.assert_called_once_with(
            str(self.fit_dir / "101.fit")
        )
        self.assertEqual(b"fit-data", (self.fit_dir / "101.fit").read_bytes())

    def test_business_code_202_also_marks_a_non_202_http_response_as_synced(self):
        response = garmin_business_response(202, "already imported")

        result, db, _ = self.run_sync_with_response(response)

        self.assertEqual(1, result["success"])
        self.assertEqual(0, result["failed"])
        self.assertEqual([(101, "COROS", "GARMIN_CN")], db.synced)

    def test_other_business_codes_remain_failed_and_are_not_marked_synced(self):
        response = garmin_business_response(409, "import rejected")

        result, db, _ = self.run_sync_with_response(response)

        self.assertEqual(0, result["success"])
        self.assertEqual(1, result["failed"])
        self.assertEqual([], db.synced)


if __name__ == "__main__":
    unittest.main()
