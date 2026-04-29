import sqlite3
import tempfile
import unittest
from pathlib import Path

from ailock.battle_log import (
    BattleAction,
    BattleCombatantSnapshot,
    BattleLogStore,
    BattleMoveSlot,
    BattleStepInput,
)
from ailock.knowledge import KnowledgeStore
from ailock.models import KnowledgeEntry
from ailock.pet_vision import PetCatalogStore


class BattleLogStoreTests(unittest.TestCase):
    def test_append_step_links_pet_and_skill_references(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "knowledge.db"
            pet_catalog = PetCatalogStore(database_path)
            pet_id = pet_catalog.upsert(name="Dimo", aliases=["Holy Dimo"])
            knowledge = KnowledgeStore(database_path)
            knowledge.upsert(
                KnowledgeEntry(
                    source_path="rocom_skill::Flame Dash",
                    source_type="rocom_skill",
                    title="Flame Dash",
                    content="A fire move.",
                    keywords=["Flame Dash"],
                )
            )
            store = BattleLogStore(database_path)
            session_id = store.start_session(battle_format="pvp", source="unit-test")

            step_id = store.append_step(
                session_id,
                BattleStepInput(
                    turn_number=1,
                    step_number=1,
                    event_type="observe",
                    player=BattleCombatantSnapshot(
                        side="player",
                        pet_name="Holy Dimo",
                        hp_percent=87.5,
                        status_effects=["burn"],
                        buffs={"speed": 1},
                        marks=[{"name": "sun-mark", "stacks": 2}],
                        confidence=0.91,
                        move_slots=[
                            BattleMoveSlot(
                                slot_index=1,
                                skill_name="Flame Dash",
                                pp_remaining=4,
                                pp_max=5,
                                confidence=0.88,
                            )
                        ],
                    ),
                    opponent=BattleCombatantSnapshot(side="opponent", pet_name="Unknown"),
                    field_state={"weather": "sun"},
                    recognition={"source": "fixture"},
                    confidence={"player_pet": 0.91},
                    uncertainties=["opponent_pet"],
                ),
            )

            loaded = store.load_step(step_id)
            player = next(item for item in loaded["combatants"] if item["side"] == "player")
            move = player["move_slots"][0]

            self.assertEqual(player["pet_id"], pet_id)
            self.assertEqual(player["status_effects"], ["burn"])
            self.assertEqual(player["buffs"], {"speed": 1})
            self.assertEqual(player["marks"], [{"name": "sun-mark", "stacks": 2}])
            self.assertEqual(move["skill_name"], "Flame Dash")
            self.assertIsInstance(move["skill_document_id"], int)
            self.assertEqual(loaded["field_state"], {"weather": "sun"})
            self.assertEqual(loaded["uncertainties"], ["opponent_pet"])

    def test_state_machine_rejects_invalid_transition(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = BattleLogStore(Path(temp_dir) / "knowledge.db")
            session_id = store.start_session()
            store.append_step(
                session_id,
                BattleStepInput(turn_number=1, step_number=1, event_type="observe"),
            )
            store.append_step(
                session_id,
                BattleStepInput(
                    turn_number=1,
                    step_number=2,
                    event_type="select_action",
                    actions=[BattleAction(actor_side="player", action_type="move", skill_name="A")],
                ),
            )

            with self.assertRaisesRegex(ValueError, "cannot apply event"):
                store.append_step(
                    session_id,
                    BattleStepInput(turn_number=1, step_number=3, event_type="advise"),
                )

    def test_finish_step_closes_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "knowledge.db"
            store = BattleLogStore(database_path)
            session_id = store.start_session()

            store.append_step(
                session_id,
                BattleStepInput(turn_number=1, step_number=1, event_type="observe"),
            )
            store.append_step(
                session_id,
                BattleStepInput(turn_number=1, step_number=2, event_type="finish"),
            )

            conn = sqlite3.connect(database_path)
            status = conn.execute(
                "SELECT status FROM battle_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()[0]
            transition_count = conn.execute("SELECT COUNT(*) FROM battle_transitions").fetchone()[0]
            conn.close()

            self.assertEqual(status, "completed")
            self.assertEqual(transition_count, 2)
            with self.assertRaisesRegex(ValueError, "not active"):
                store.append_step(
                    session_id,
                    BattleStepInput(turn_number=2, step_number=1, event_type="observe"),
                )


if __name__ == "__main__":
    unittest.main()
