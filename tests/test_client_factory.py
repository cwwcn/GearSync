import unittest
from unittest.mock import Mock, patch

import client_factory


class ClientFactoryTests(unittest.TestCase):
    def setUp(self):
        self.logger = Mock()

    def test_coros_requires_credentials_and_logs_in_immediately(self):
        coros_client = Mock()
        coros_client.email = "runner@example.test"
        with patch.dict(
            client_factory.SYNC_CONFIG,
            {"COROS_EMAIL": "runner@example.test", "COROS_PASSWORD": "password"},
            clear=True,
        ), patch.object(
            client_factory, "CorosClient", return_value=coros_client
        ) as client_class:
            result = client_factory.create_coros_client(self.logger)

        self.assertIs(result, coros_client)
        client_class.assert_called_once_with("runner@example.test", "password")
        coros_client.login.assert_called_once_with()

    def test_coros_is_not_created_when_a_required_credential_is_missing(self):
        with patch.dict(
            client_factory.SYNC_CONFIG,
            {"COROS_EMAIL": "runner@example.test", "COROS_PASSWORD": ""},
            clear=True,
        ), patch.object(client_factory, "CorosClient") as client_class:
            result = client_factory.create_coros_client(self.logger)

        self.assertIsNone(result)
        client_class.assert_not_called()

    def test_garmin_cn_prefers_the_configured_token(self):
        garmin_client = Mock()
        with patch.dict(
            client_factory.SYNC_CONFIG,
            {
                "GARMIN_CN_SECRET": "token",
                "GARMIN_CN_EMAIL": "runner@example.test",
                "GARMIN_CN_PASSWORD": "password",
            },
            clear=True,
        ), patch.object(
            client_factory, "GarminCNClient", return_value=garmin_client
        ) as client_class:
            result = client_factory.create_garmin_cn_client(self.logger)

        self.assertIs(result, garmin_client)
        client_class.assert_called_once_with("token")

    def test_garmin_global_falls_back_to_email_and_password(self):
        garmin_client = Mock()
        with patch.dict(
            client_factory.SYNC_CONFIG,
            {
                "GARMIN_GLOBAL_SECRET": "",
                "GARMIN_GLOBAL_EMAIL": "runner@example.test",
                "GARMIN_GLOBAL_PASSWORD": "password",
            },
            clear=True,
        ), patch.object(
            client_factory, "GarminGlobalClient", return_value=garmin_client
        ) as client_class:
            result = client_factory.create_garmin_global_client(self.logger)

        self.assertIs(result, garmin_client)
        client_class.assert_called_once_with("runner@example.test", "password")

    def test_garmin_is_not_created_without_a_complete_login_method(self):
        with patch.dict(
            client_factory.SYNC_CONFIG,
            {
                "GARMIN_CN_SECRET": "",
                "GARMIN_CN_EMAIL": "runner@example.test",
                "GARMIN_CN_PASSWORD": "",
            },
            clear=True,
        ), patch.object(client_factory, "GarminCNClient") as client_class:
            result = client_factory.create_garmin_cn_client(self.logger)

        self.assertIsNone(result)
        client_class.assert_not_called()


if __name__ == "__main__":
    unittest.main()
