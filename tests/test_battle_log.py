import sqlite3
import tempfile
import unittest
from pathlib import Path

from ailock.battle_log import (
    BattleAction,
    BattleActionEffect,
    BattleCombatantSnapshot,
    BattleFieldSnapshot,
    BattleLogStore,
    BattleMoveSlot,
    BattleStepInput,
    BattleTeamMember,
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

    def test_records_complete_turn_timeline_with_energy_teams_field_and_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "knowledge.db"
            pet_catalog = PetCatalogStore(database_path)
            dimo_id = pet_catalog.upsert(name="Dimo", aliases=["Holy Dimo"], primary_attribute="Light")
            fox_id = pet_catalog.upsert(name="Fire Fox", aliases=["Firefox"], primary_attribute="Fire")
            dragon_id = pet_catalog.upsert(name="Stone Dragon", primary_attribute="Rock")
            knowledge = KnowledgeStore(database_path)
            knowledge.upsert(
                KnowledgeEntry(
                    source_path="rocom_skill::Flame Dash",
                    source_type="rocom_skill",
                    title="Flame Dash",
                    content="技能名称: Flame Dash; 属性: Fire; 类型: 魔攻; 耗能: 2; 威力/伤害: 80;",
                    keywords=["Flame Dash", "Fire"],
                )
            )
            store = BattleLogStore(database_path)
            session_id = store.start_session(
                battle_format="pvp",
                season="s1",
                battlefield="training_field",
                rules={"team_size": 3, "turn_seconds": 30},
                player_name="me",
                opponent_name="rival",
                source="unit-test",
            )

            observe_step_id = store.append_step(
                session_id,
                BattleStepInput(
                    turn_number=1,
                    step_number=1,
                    event_type="observe",
                    screenshot_path="data/captures/t1-start.png",
                    teams=[
                        BattleTeamMember(
                            side="player",
                            team_slot=1,
                            pet_name="Holy Dimo",
                            is_active=True,
                            has_entered=True,
                            level_normalized=True,
                        ),
                        BattleTeamMember(side="player", team_slot=2, pet_name="Fire Fox"),
                        BattleTeamMember(side="opponent", team_slot=1, pet_name="Stone Dragon", is_active=True),
                    ],
                    field_snapshot=BattleFieldSnapshot(
                        weather="sun",
                        terrain="arena",
                        turn_time_remaining_seconds=28,
                        global_marks=[{"name": "opening"}],
                    ),
                    player=BattleCombatantSnapshot(
                        side="player",
                        pet_name="Holy Dimo",
                        hp_current=120,
                        hp_max=120,
                        hp_percent=100,
                        energy_current=4,
                        energy_max=6,
                        move_slots=[
                            BattleMoveSlot(
                                slot_index=1,
                                skill_name="Flame Dash",
                                energy_cost_observed=2,
                                pp_remaining=5,
                                raw_text="Flame Dash costs 2 energy",
                            )
                        ],
                    ),
                    opponent=BattleCombatantSnapshot(
                        side="opponent",
                        pet_name="Stone Dragon",
                        hp_current=150,
                        hp_max=150,
                        hp_percent=100,
                        energy_current=3,
                        energy_max=6,
                    ),
                ),
            )

            action_step_id = store.append_step(
                session_id,
                BattleStepInput(
                    turn_number=1,
                    step_number=2,
                    event_type="select_action",
                    actions=[
                        BattleAction(
                            actor_side="player",
                            action_type="move",
                            action_order=1,
                            skill_name="Flame Dash",
                            target_side="opponent",
                            energy_before=4,
                            energy_cost_observed=2,
                            energy_after=2,
                            success=True,
                            raw_text="Holy Dimo used Flame Dash.",
                            effects=[
                                BattleActionEffect(
                                    effect_order=1,
                                    effect_type="damage",
                                    target_side="opponent",
                                    target_pet_name="Stone Dragon",
                                    value=48,
                                    hp_before=150,
                                    hp_after=102,
                                    raw_text="Stone Dragon HP 150 -> 102",
                                ),
                                BattleActionEffect(
                                    effect_order=2,
                                    effect_type="mark_change",
                                    target_side="opponent",
                                    target_pet_name="Stone Dragon",
                                    mark_name="burn-mark",
                                    raw_text="Applied one burn mark.",
                                ),
                            ],
                        ),
                        BattleAction(
                            actor_side="opponent",
                            action_type="switch",
                            action_order=2,
                            from_pet_name="Stone Dragon",
                            to_pet_name="Fire Fox",
                            success=True,
                            raw_text="Opponent switched to Fire Fox.",
                            effects=[
                                BattleActionEffect(
                                    effect_order=1,
                                    effect_type="summon",
                                    target_side="opponent",
                                    target_pet_name="Fire Fox",
                                    raw_text="Fire Fox entered battle.",
                                )
                            ],
                        ),
                    ],
                ),
            )
            resolution_step_id = store.append_step(
                session_id,
                BattleStepInput(
                    turn_number=1,
                    step_number=3,
                    event_type="observe",
                    field_snapshot=BattleFieldSnapshot(victory_state="ongoing"),
                    player=BattleCombatantSnapshot(
                        side="player",
                        pet_name="Holy Dimo",
                        hp_current=120,
                        hp_max=120,
                        energy_current=2,
                        energy_max=6,
                        energy_delta=-2,
                    ),
                    opponent=BattleCombatantSnapshot(
                        side="opponent",
                        pet_name="Fire Fox",
                        hp_current=130,
                        hp_max=130,
                        energy_current=3,
                        energy_max=6,
                    ),
                ),
            )

            observe = store.load_step(observe_step_id)
            player = next(item for item in observe["combatants"] if item["side"] == "player")
            move = player["move_slots"][0]
            self.assertEqual(player["pet_id"], dimo_id)
            self.assertEqual(player["energy_current"], 4)
            self.assertEqual(move["energy_cost_standard"], 2)
            self.assertEqual(move["energy_cost_observed"], 2)
            self.assertEqual(observe["field_snapshot"]["weather"], "sun")

            action_step = store.load_step(action_step_id)
            move_action = action_step["actions"][0]
            switch_action = action_step["actions"][1]
            self.assertEqual(move_action["skill_document_id"], move["skill_document_id"])
            self.assertEqual(move_action["energy_before"], 4)
            self.assertEqual(move_action["energy_cost_standard"], 2)
            self.assertEqual(move_action["energy_after"], 2)
            self.assertTrue(move_action["success"])
            self.assertEqual(move_action["effects"][0]["effect_type"], "damage")
            self.assertEqual(move_action["effects"][0]["target_pet_id"], dragon_id)
            self.assertEqual(move_action["effects"][1]["mark_name"], "burn-mark")
            self.assertEqual(switch_action["action_type"], "switch")
            self.assertEqual(switch_action["from_pet_id"], dragon_id)
            self.assertEqual(switch_action["to_pet_id"], fox_id)

            timeline = store.load_session_timeline(session_id)
            self.assertEqual(timeline["session"]["rules"], {"team_size": 3, "turn_seconds": 30})
            self.assertEqual(len(timeline["teams"]), 3)
            self.assertEqual(len(timeline["steps"]), 3)
            self.assertEqual(timeline["steps"][-1]["id"], resolution_step_id)
            final_player = next(item for item in timeline["steps"][-1]["combatants"] if item["side"] == "player")
            self.assertEqual(final_player["energy_delta"], -2)

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
                BattleStepInput(
                    turn_number=1,
                    step_number=2,
                    event_type="finish",
                    field_snapshot=BattleFieldSnapshot(victory_state="player_win"),
                ),
            )

            conn = sqlite3.connect(database_path)
            row = conn.execute(
                "SELECT status, result FROM battle_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            transition_count = conn.execute("SELECT COUNT(*) FROM battle_transitions").fetchone()[0]
            conn.close()

            self.assertEqual(row[0], "completed")
            self.assertEqual(row[1], "player_win")
            self.assertEqual(transition_count, 2)
            with self.assertRaisesRegex(ValueError, "not active"):
                store.append_step(
                    session_id,
                    BattleStepInput(turn_number=2, step_number=1, event_type="observe"),
                )


if __name__ == "__main__":
    unittest.main()
