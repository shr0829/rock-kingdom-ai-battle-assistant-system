import json
import unittest
from pathlib import Path
from unittest import mock

from ailock.llm_client import MultimodalClient
from ailock.models import AppSettings, BattleState


class MultimodalClientTests(unittest.TestCase):
    def test_parse_text_output_reads_chat_choice_text(self) -> None:
        payload = {"choices": [{"message": {"content": "看到了双方宠物，建议先换宠。"}}]}

        parsed = MultimodalClient._parse_text_output(payload)

        self.assertEqual(parsed, "看到了双方宠物，建议先换宠。")

    def test_parse_battle_state_text_reads_prompt_shaped_output(self) -> None:
        client = MultimodalClient(AppSettings(api_key="secret"))
        payload = """
我方精灵: 烈火战神
对方精灵: 圣光迪莫
我方血量: 约70%
可见技能: 烈焰冲锋 | 火焰护盾 | 爆炎拳
已观察伤害: 我方上一击打掉对方约15%
速度判断: 对方先手
状态效果: 烧伤 | 护盾
场地信息: 无明显天气，场地正常
战术总结: 对方先手压制，我方需要评估是否换宠或保命
检索关键词: 烈火战神 | 圣光迪莫 | 对方先手 | 烧伤
不确定点: 对方第四技能未知
置信度: 我方精灵=0.95; 对方精灵=0.90; 速度判断=0.70
"""

        battle_state = client._parse_battle_state_text(payload)

        self.assertEqual(battle_state.player_pet, "烈火战神")
        self.assertEqual(battle_state.opponent_pet, "圣光迪莫")
        self.assertEqual(battle_state.player_hp_state, "约70%")
        self.assertIn("烈焰冲锋", battle_state.visible_moves)
        self.assertIn("烧伤", battle_state.status_effects)
        self.assertIn("对方先手", battle_state.field_notes)
        self.assertIn("圣光迪莫", battle_state.suggested_query_terms)
        self.assertIn("对方第四技能未知", battle_state.unknowns)
        self.assertEqual(battle_state.confidence_map["player_pet"], 0.95)

    def test_describe_battle_state_returns_fallback_when_information_is_insufficient(self) -> None:
        client = MultimodalClient(AppSettings(api_key="secret"))
        mocked_answer = """
我方精灵: 未知
对方精灵: 未知
我方血量: 未知
可见技能: 无
已观察伤害: 无
速度判断: 无法判断
状态效果: 无
场地信息: 这是软件界面，不是战斗画面
战术总结: 当前截图缺少真实战斗信息
检索关键词: AI洛克 | 软件界面
不确定点: 未能稳定识别双方精灵
置信度: 我方精灵=0.10; 对方精灵=0.10
"""
        with mock.patch.object(client, "answer_image", return_value=mocked_answer):
            battle_state = client.describe_battle_state(b"abc")

        self.assertEqual(battle_state.tactical_summary, "当前截图缺少真实战斗信息")
        self.assertIn("AI洛克", battle_state.suggested_query_terms)
        self.assertIn("未能稳定识别双方精灵", battle_state.unknowns)

    def test_parse_knowledge_image_text_reads_prompt_shaped_output(self) -> None:
        client = MultimodalClient(AppSettings(api_key="secret"))
        payload = """
标题: 烈火战神打草系
摘要: 火系对草系时优先保持先手压制。
关键词: 烈火战神 | 草系 | 先手压制
要点: 烈焰冲锋可压血线 | 注意反制技能
"""

        parsed = client._parse_knowledge_image_text(payload, Path("sample.png"))

        self.assertEqual(parsed["title"], "烈火战神打草系")
        self.assertIn("草系", parsed["keywords"])
        self.assertIn("烈焰冲锋可压血线", parsed["facts"])

    def test_parse_advice_text_reads_prompt_shaped_output(self) -> None:
        client = MultimodalClient(AppSettings(api_key="secret"))
        payload = """
推荐操作: 先换宠到水系抗性位
原因: 对方先手且有压制技能，我方当前站场风险高
资料依据: 圣光迪莫常见先手压制 | 水系可抗火系输出
置信度: 中
注意事项: 警惕对方补刀 | 注意残血被先手收掉
"""

        advice = client._parse_advice_text(payload)

        self.assertEqual(advice.recommended_action, "先换宠到水系抗性位")
        self.assertEqual(advice.confidence, "中")
        self.assertIn("圣光迪莫常见先手压制", advice.evidence)
        self.assertIn("警惕对方补刀", advice.caveats)

    def test_generate_advice_returns_local_fallback_when_battle_state_is_insufficient(self) -> None:
        client = MultimodalClient(AppSettings(api_key="secret"))
        battle_state = BattleState(
            tactical_summary="截图里缺少足够的战斗信息，暂时无法稳定判断回合。",
            unknowns=["请截到完整的战斗区域后再分析"],
        )

        advice = client.generate_advice(battle_state, [])

        self.assertIn("补一张包含完整战斗区域的截图", advice.recommended_action)
        self.assertEqual(advice.confidence, "高")

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

    def test_image_strategies_include_compatible_fallbacks(self) -> None:
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

    def test_answer_image_uses_plain_text_payload(self) -> None:
        client = MultimodalClient(AppSettings(api_key="secret"))
        with mock.patch.object(client, "_post", return_value={"output_text": "建议先观察"}) as mocked_post:
            answer = client.answer_image("Describe the screenshot", b"abc")

        self.assertEqual(answer, "建议先观察")
        payload = mocked_post.call_args.args[0]
        self.assertNotIn("text", payload)
        self.assertEqual(payload["input"][0]["content"][0]["text"], "Describe the screenshot")

    def test_generate_advice_uses_plain_text_output_path(self) -> None:
        client = MultimodalClient(AppSettings(api_key="secret"))
        battle_state = client._parse_battle_state_text(
            """
我方精灵: 烈火战神
对方精灵: 圣光迪莫
我方血量: 约70%
可见技能: 烈焰冲锋
已观察伤害: 无
速度判断: 对方先手
状态效果: 无
场地信息: 无
战术总结: 对方先手压制
检索关键词: 烈火战神 | 圣光迪莫
不确定点: 无
置信度: 我方精灵=0.95; 对方精灵=0.90
"""
        )
        raw_advice = """
推荐操作: 先换宠
原因: 对方先手压制明显
资料依据: 圣光迪莫常见先手压制 | 当前血量不适合硬拼
置信度: 中
注意事项: 注意补刀
"""
        with mock.patch.object(client, "_post", return_value={"output_text": raw_advice}) as mocked_post:
            advice = client.generate_advice(battle_state, [])

        self.assertEqual(advice.recommended_action, "先换宠")
        payload = mocked_post.call_args.args[0]
        self.assertNotIn("text", payload)


if __name__ == "__main__":
    unittest.main()
