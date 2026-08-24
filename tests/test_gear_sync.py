import builtins
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import gear_sync


class GearSyncRoutingTests(unittest.TestCase):
    def test_all_supported_directions_route_to_the_existing_entry_modules(self):
        expected_routes = {
            ("COROS", "GARMIN_GLOBAL"): "coros_to_garmin_global",
            ("GARMIN_GLOBAL", "COROS"): "garmin_global_to_coros",
            ("COROS", "GARMIN_CN"): "coros_to_garmin_cn",
            ("GARMIN_CN", "COROS"): "garmin_cn_to_coros",
            ("GARMIN_GLOBAL", "GARMIN_CN"): "garmin_global_to_garmin_cn",
            ("GARMIN_CN", "GARMIN_GLOBAL"): "garmin_cn_to_garmin_global",
        }
        self.assertEqual(expected_routes, gear_sync.SYNC_MAP)

        real_import = builtins.__import__
        for (source, target), module_name in expected_routes.items():
            with self.subTest(source=source, target=target):
                module_main = Mock()
                fake_module = SimpleNamespace(main=module_main)

                def import_for_route(name, *args, **kwargs):
                    if name == module_name:
                        return fake_module
                    return real_import(name, *args, **kwargs)

                with patch.dict(
                    gear_sync.SYNC_CONFIG,
                    {"SOURCE": source.lower(), "TARGET": target.lower()},
                    clear=True,
                ), patch("builtins.__import__", side_effect=import_for_route):
                    gear_sync.main()

                module_main.assert_called_once_with()

    def test_missing_source_or_target_does_not_start_a_sync_module(self):
        with patch.dict(
            gear_sync.SYNC_CONFIG, {"SOURCE": "", "TARGET": "GARMIN_CN"}, clear=True
        ), patch("builtins.__import__") as import_mock:
            gear_sync.main()
        import_mock.assert_not_called()

        with patch.dict(
            gear_sync.SYNC_CONFIG, {"SOURCE": "COROS", "TARGET": ""}, clear=True
        ), patch("builtins.__import__") as import_mock:
            gear_sync.main()
        import_mock.assert_not_called()

    def test_unsupported_direction_does_not_import_a_sync_module(self):
        with patch.dict(
            gear_sync.SYNC_CONFIG,
            {"SOURCE": "COROS", "TARGET": "COROS"},
            clear=True,
        ), patch("builtins.__import__") as import_mock:
            gear_sync.main()
        import_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
