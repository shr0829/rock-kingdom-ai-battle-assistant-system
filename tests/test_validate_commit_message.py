import unittest

from scripts.validate_commit_message import validate_commit_message_text


VALID_MESSAGE = """
避免发布前忘记补齐版本说明

发布前经常只改代码不补文档，回看历史时很难快速知道为什么发版。
本次提交把版本说明检查前置到流程里，减少遗漏并让回溯更直接。

约束: 发布流程仍需兼容现有的 GitHub Release 工作流
备选方案: 只在发版脚本里提醒 | 太晚才暴露问题，容易在临门一脚返工
信心: 高
风险范围: 小
提醒: 如果后续新增发版入口，记得复用同一套说明检查
已验证: 单元测试覆盖合法提交说明
未验证: Windows Git 图形界面的提交流程
""".strip()


class ValidateCommitMessageTests(unittest.TestCase):
    def test_valid_chinese_message_passes(self) -> None:
        self.assertEqual(validate_commit_message_text(VALID_MESSAGE), [])

    def test_missing_required_trailer_fails(self) -> None:
        errors = validate_commit_message_text(
            VALID_MESSAGE.replace("未验证: Windows Git 图形界面的提交流程", "")
        )

        self.assertTrue(any("未验证" in error for error in errors))

    def test_english_subject_fails(self) -> None:
        errors = validate_commit_message_text(VALID_MESSAGE.replace("避免发布前忘记补齐版本说明", "Update release flow"))

        self.assertTrue(any("默认使用中文" in error for error in errors))

    def test_merge_commit_is_ignored(self) -> None:
        self.assertEqual(validate_commit_message_text("Merge branch 'feature'"), [])


if __name__ == "__main__":
    unittest.main()
