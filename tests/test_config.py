import unittest
from unittest import mock

from ailock.config import SettingsStore


class ConfigTests(unittest.TestCase):
    def test_project_config_is_loaded_before_user_settings(self) -> None:
        settings_path = mock.Mock()
        settings_path.exists.return_value = False
        config_path = mock.Mock()
        config_path.exists.return_value = True

        project_config = {
            "model_provider": "OpenAI",
            "model": "gpt-5.5",
            "review_model": "gpt-5.5",
            "model_reasoning_effort": "xhigh",
            "disable_response_storage": True,
            "model_providers": {
                "OpenAI": {
                    "name": "OpenAI",
                    "base_url": "https://api.asxs.top/v1",
                    "wire_api": "responses",
                    "requires_openai_auth": True,
                }
            },
        }

        with mock.patch.object(SettingsStore, "_load_toml", return_value=project_config):
            settings = SettingsStore(settings_path, config_path).load()

        self.assertEqual(settings.model, "gpt-5.5")
        self.assertEqual(settings.review_model, "gpt-5.5")
        self.assertEqual(settings.base_url, "https://api.asxs.top/v1")
        self.assertEqual(settings.wire_api, "responses")
        self.assertTrue(settings.disable_response_storage)

    def test_codex_auth_key_is_used_when_local_settings_api_key_is_empty(self) -> None:
        settings_path = mock.Mock()
        settings_path.exists.return_value = True
        settings_path.read_text.return_value = '{"api_key": ""}'

        with mock.patch.object(SettingsStore, "_load_codex_auth_key", return_value="fallback-secret"):
            settings = SettingsStore(settings_path).load()

        self.assertEqual(settings.api_key, "fallback-secret")


if __name__ == "__main__":
    unittest.main()
