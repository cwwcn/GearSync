import sqlite3
import tempfile
import unittest
from pathlib import Path

from db.activity_db import ActivityDB


class ActivityDBTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "activity-test.db"
        self.db = ActivityDB(str(self.db_path))
        self.db.initDB()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_same_activity_is_deduplicated_per_sync_direction(self):
        self.db.saveActivity(101, "COROS", "GARMIN_CN")
        self.db.saveActivity(101, "COROS", "GARMIN_CN")
        self.db.saveActivity(101, "COROS", "GARMIN_GLOBAL")

        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT activity_source, activity_target, activity_id
                FROM activity_table
                ORDER BY activity_target
                """
            ).fetchall()

        self.assertEqual(
            [
                ("COROS", "GARMIN_CN", 101),
                ("COROS", "GARMIN_GLOBAL", 101),
            ],
            rows,
        )

    def test_only_status_zero_is_returned_as_pending(self):
        self.db.saveActivity(101, "COROS", "GARMIN_CN")
        self.db.saveActivity(102, "COROS", "GARMIN_CN")
        self.db.saveActivity(103, "COROS", "GARMIN_CN")

        self.db.updateSyncStatus(101, "COROS", "GARMIN_CN")
        self.db.updateExceptionSyncStatus(102, "COROS", "GARMIN_CN")

        self.assertEqual(
            [103], self.db.getUnSyncActivity("COROS", "GARMIN_CN")
        )

    def test_no_pending_activity_returns_none(self):
        self.db.saveActivity(101, "GARMIN_CN", "COROS")
        self.db.updateSyncStatus(101, "GARMIN_CN", "COROS")

        self.assertIsNone(self.db.getUnSyncActivity("GARMIN_CN", "COROS"))


if __name__ == "__main__":
    unittest.main()
