import json
import unittest

from ailock.llm_client import MultimodalClient
from ailock.models import AppSettings


class MultimodalClientTests(unittest.TestCase):
    def test_parse_structured_output_reads_output_text(self) -> None:
        payload = {"output_text": json.dumps({"recommended_action": "换宠"})}

        parsed = MultimodalClient._parse_structured_output(payload)

        self.assertEqual(parsed["recommended_action"], "换宠")

    def test_parse_structured_output_reads_chat_choice_json(self) -> None:
        payload = {"choices": [{"message": {"content": "```json\n{\"recommended_action\":\"换宠\"}\n```"}}]}

        parsed = MultimodalClient._parse_structured_output(payload)

        self.assertEqual(parsed["recommended_action"], "换宠")

    def test_data_url_generation_uses_base64_prefix(self) -> None:
        client = MultimodalClient(AppSettings(api_key="test"))

        data_url = client._to_data_url(b"abc", "image/png")

        self.assertTrue(data_url.startswith("data:image/png;base64,"))

    def test_headers_include_browser_user_agent_for_cloudflare_gateway(self) -> None:
        client = MultimodalClient(AppSettings(api_key="secret"))

        headers = client._build_headers()

        self.assertIn("Mozilla/5.0", headers["User-Agent"])
        self.assertEqual(headers["Authorization"], "Bearer secret")

    def test_cloudflare_502_image_error_is_actionable(self) -> None:
        client = MultimodalClient(AppSettings(api_key="secret"))
        message = client._format_http_error(
            502,
            json.dumps({"cloudflare_error": True, "retry_after": 60}),
            {"input": [{"content": [{"type": "input_image", "image_url": "data:image/png;base64,abc"}]}]},
        )

        self.assertIn("图片输入", message)
        self.assertIn("config.toml", message)

    def test_image_strategies_include_yuketang_compatible_fallbacks(self) -> None:
        labels = [strategy["label"] for strategy in MultimodalClient._image_request_strategies()]

        self.assertEqual(
            labels,
            [
                "responses-input-image-string",
                "responses-input-image-object",
                "chat-image-url-object",
                "chat-image-url-string",
            ],
        )


if __name__ == "__main__":
    unittest.main()
