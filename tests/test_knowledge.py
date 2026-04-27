import tempfile
import unittest
from pathlib import Path

from ailock.knowledge import KnowledgeStore
from ailock.models import KnowledgeEntry


class KnowledgeStoreTests(unittest.TestCase):
    def test_knowledge_store_search_returns_best_hit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = KnowledgeStore(Path(temp_dir) / "knowledge.db")
            store.upsert(
                KnowledgeEntry(
                    source_path="a.txt",
                    source_type="text",
                    title="火系宠物打法",
                    content="当敌方是草系时优先使用火系技能压制。",
                    keywords=["火系", "草系", "压制"],
                )
            )
            store.upsert(
                KnowledgeEntry(
                    source_path="b.txt",
                    source_type="text",
                    title="水系宠物打法",
                    content="水系在面对火系目标时更容易形成属性克制。",
                    keywords=["水系", "火系", "克制"],
                )
            )

            hits = store.search("火系 草系", limit=1)

            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0].title, "火系宠物打法")


if __name__ == "__main__":
    unittest.main()
