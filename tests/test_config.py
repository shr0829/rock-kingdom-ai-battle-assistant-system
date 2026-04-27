import tempfile
import unittest
from pathlib import Path

from ailock.config import SettingsStore


class ConfigTests(unittest.TestCase):
    def test_project_config_is_loaded_before_user_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.toml"
            settings_path = root / "settings.json"
            config_path.write_text(
                """
model_provider = "OpenAI"
model = "gpt-5.5"
review_model = "gpt-5.5"
model_reasoning_effort = "xhigh"
disable_response_storage = true

[model_providers.OpenAI]
name = "OpenAI"
base_url = "https://api.asxs.top/v1"
wire_api = "responses"
requires_openai_auth = true
""",
                encoding="utf-8",
            )

            settings = SettingsStore(settings_path, config_path).load()

            self.assertEqual(settings.model, "gpt-5.5")
            self.assertEqual(settings.review_model, "gpt-5.5")
            self.assertEqual(settings.base_url, "https://api.asxs.top/v1")
            self.assertEqual(settings.wire_api, "responses")
            self.assertTrue(settings.disable_response_storage)


if __name__ == "__main__":
    unittest.main()
