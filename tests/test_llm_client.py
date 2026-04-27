import json
import unittest

from ailock.llm_client import MultimodalClient
from ailock.models import AppSettings


class MultimodalClientTests(unittest.TestCase):
    def test_parse_structured_output_reads_output_text(self) -> None:
        payload = {"output_text": json.dumps({"recommended_action": "换宠"})}

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


if __name__ == "__main__":
    unittest.main()
