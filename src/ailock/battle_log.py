from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


SESSION_STATUSES = {"active", "completed", "abandoned"}
STEP_PHASES = {"observation", "advice", "action", "resolution", "correction", "summary"}
EVENT_TO_PHASE = {
    "observe": "observation",
    "advise": "advice",
    "select_action": "action",
    "resolve_action": "resolution",
    "manual_correct": "correction",
    "finish": "summary",
}
ALLOWED_NEXT_EVENTS = {
    None: {"observe", "manual_correct"},
    "observation": {"observe", "advise", "select_action", "manual_correct", "finish"},
    "advice": {"observe", "select_action", "manual_correct", "finish"},
    "action": {"observe", "resolve_action", "manual_correct", "finish"},
    "resolution": {"observe", "advise", "manual_correct", "finish"},
    "correction": {"observe", "advise", "select_action", "finish"},
    "summary": set(),
}
SIDES = {"player", "opponent"}
ACTION_TYPES = {"move", "switch", "magic", "item", "unknown", "pass"}
EFFECT_TYPES = {
    "damage",
    "heal",
    "energy_change",
    "status_add",
    "status_remove",
    "buff_change",
    "mark_change",
    "field_change",
    "faint",
    "summon",
    "miss",
    "critical",
    "attribute_matchup",
    "unknown_effect",
}


@dataclass(slots=True)
class BattleMoveSlot:
    slot_index: int
    skill_name: str = ""
    skill_document_id: int | None = None
    pp_remaining: int | None = None
    pp_max: int | None = None
    energy_cost_standard: int | None = None
    energy_cost_observed: int | None = None
    cooldown_remaining: int | None = None
    disabled: bool = False
    confidence: float = 0.0
    candidates: list[dict[str, Any]] = field(default_factory=list)
    raw_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BattleCombatantSnapshot:
    side: str
    pet_name: str = ""
    pet_id: int | None = None
    pet_name_raw: str = ""
    hp_state: str = ""
    hp_current: int | None = None
    hp_max: int | None = None
    hp_percent: float | None = None
    energy_current: int | None = None
    energy_max: int | None = None
    energy_delta: int | None = None
    status_effects: list[str] = field(default_factory=list)
    buffs: dict[str, Any] = field(default_factory=dict)
    marks: list[dict[str, Any]] = field(default_factory=list)
    ability: str = ""
    item: str = ""
    is_active: bool = True
    is_fainted: bool = False
    confidence: float = 0.0
    raw_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    move_slots: list[BattleMoveSlot] = field(default_factory=list)


@dataclass(slots=True)
class BattleTeamMember:
    side: str
    team_slot: int
    pet_name: str = ""
    pet_id: int | None = None
    pet_name_raw: str = ""
    primary_attribute: str = ""
    secondary_attribute: str = ""
    level_normalized: bool | None = None
    is_active: bool = False
    is_fainted: bool = False
    has_entered: bool = False
    confidence: float = 0.0
    raw_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BattleFieldSnapshot:
    weather: str = ""
    terrain: str = ""
    turn_time_remaining_seconds: int | None = None
    field_effects: list[dict[str, Any]] = field(default_factory=list)
    global_marks: list[dict[str, Any]] = field(default_factory=list)
    victory_state: str = ""
    raw_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BattleActionEffect:
    effect_type: str = "unknown_effect"
    effect_order: int = 0
    target_side: str = ""
    target_pet_id: int | None = None
    target_pet_name: str = ""
    value: float | None = None
    hp_before: int | None = None
    hp_after: int | None = None
    energy_before: int | None = None
    energy_after: int | None = None
    status_name: str = ""
    buff_name: str = ""
    mark_name: str = ""
    field_key: str = ""
    raw_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BattleAction:
    actor_side: str
    action_type: str = "unknown"
    skill_name: str = ""
    skill_document_id: int | None = None
    target_side: str = ""
    action_order: int | None = None
    priority: int | None = None
    speed_note: str = ""
    success: bool | None = None
    energy_before: int | None = None
    energy_cost_standard: int | None = None
    energy_cost_observed: int | None = None
    energy_after: int | None = None
    from_pet_id: int | None = None
    from_pet_name: str = ""
    to_pet_id: int | None = None
    to_pet_name: str = ""
    raw_text: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    effects: list[BattleActionEffect] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BattleStepInput:
    turn_number: int
    step_number: int
    event_type: str = "observe"
    screenshot_path: str = ""
    analysis_log_path: str = ""
    player: BattleCombatantSnapshot | None = None
    opponent: BattleCombatantSnapshot | None = None
    teams: list[BattleTeamMember] = field(default_factory=list)
    field_snapshot: BattleFieldSnapshot | None = None
    field_state: dict[str, Any] = field(default_factory=dict)
    advice: dict[str, Any] = field(default_factory=dict)
    recognition: dict[str, Any] = field(default_factory=dict)
    confidence: dict[str, float] = field(default_factory=dict)
    uncertainties: list[str] = field(default_factory=list)
    actions: list[BattleAction] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class BattleLogStore:
    """Persistent battle timeline with explicit transition events.

    The store keeps normalized links where possible, but every raw name is also
    stored so recognition output remains reviewable even when matching fails.
    """

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_path TEXT NOT NULL UNIQUE,
                    source_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    keywords TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS pet_catalog (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    no TEXT,
                    aliases TEXT NOT NULL DEFAULT '[]',
                    primary_attribute TEXT,
                    secondary_attribute TEXT,
                    source TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS battle_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    status TEXT NOT NULL DEFAULT 'active',
                    format TEXT NOT NULL DEFAULT '',
                    season TEXT NOT NULL DEFAULT '',
                    battlefield TEXT NOT NULL DEFAULT '',
                    rules_json TEXT NOT NULL DEFAULT '{}',
                    player_name TEXT NOT NULL DEFAULT '',
                    opponent_name TEXT NOT NULL DEFAULT '',
                    result TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    ended_at TEXT
                );

                CREATE TABLE IF NOT EXISTS battle_team_members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    side TEXT NOT NULL,
                    team_slot INTEGER NOT NULL,
                    pet_id INTEGER,
                    pet_name TEXT NOT NULL DEFAULT '',
                    pet_name_raw TEXT NOT NULL DEFAULT '',
                    primary_attribute TEXT NOT NULL DEFAULT '',
                    secondary_attribute TEXT NOT NULL DEFAULT '',
                    level_normalized INTEGER,
                    is_active INTEGER NOT NULL DEFAULT 0,
                    is_fainted INTEGER NOT NULL DEFAULT 0,
                    has_entered INTEGER NOT NULL DEFAULT 0,
                    confidence REAL NOT NULL DEFAULT 0,
                    raw_text TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(session_id) REFERENCES battle_sessions(id) ON DELETE CASCADE,
                    FOREIGN KEY(pet_id) REFERENCES pet_catalog(id),
                    UNIQUE(session_id, side, team_slot)
                );

                CREATE TABLE IF NOT EXISTS battle_steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    turn_number INTEGER NOT NULL,
                    step_number INTEGER NOT NULL,
                    phase TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    screenshot_path TEXT NOT NULL DEFAULT '',
                    analysis_log_path TEXT NOT NULL DEFAULT '',
                    field_state_json TEXT NOT NULL DEFAULT '{}',
                    advice_json TEXT NOT NULL DEFAULT '{}',
                    recognition_json TEXT NOT NULL DEFAULT '{}',
                    confidence_json TEXT NOT NULL DEFAULT '{}',
                    uncertainties_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(session_id) REFERENCES battle_sessions(id) ON DELETE CASCADE,
                    UNIQUE(session_id, turn_number, step_number)
                );

                CREATE TABLE IF NOT EXISTS battle_combatant_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    step_id INTEGER NOT NULL,
                    side TEXT NOT NULL,
                    pet_id INTEGER,
                    pet_name TEXT NOT NULL DEFAULT '',
                    pet_name_raw TEXT NOT NULL DEFAULT '',
                    hp_state TEXT NOT NULL DEFAULT '',
                    hp_current INTEGER,
                    hp_max INTEGER,
                    hp_percent REAL,
                    energy_current INTEGER,
                    energy_max INTEGER,
                    energy_delta INTEGER,
                    status_json TEXT NOT NULL DEFAULT '[]',
                    buffs_json TEXT NOT NULL DEFAULT '{}',
                    marks_json TEXT NOT NULL DEFAULT '[]',
                    ability TEXT NOT NULL DEFAULT '',
                    item TEXT NOT NULL DEFAULT '',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    is_fainted INTEGER NOT NULL DEFAULT 0,
                    confidence REAL NOT NULL DEFAULT 0,
                    raw_text TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(step_id) REFERENCES battle_steps(id) ON DELETE CASCADE,
                    FOREIGN KEY(pet_id) REFERENCES pet_catalog(id),
                    UNIQUE(step_id, side)
                );

                CREATE TABLE IF NOT EXISTS battle_move_slots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    combatant_snapshot_id INTEGER NOT NULL,
                    slot_index INTEGER NOT NULL,
                    skill_document_id INTEGER,
                    skill_name TEXT NOT NULL DEFAULT '',
                    pp_remaining INTEGER,
                    pp_max INTEGER,
                    energy_cost_standard INTEGER,
                    energy_cost_observed INTEGER,
                    cooldown_remaining INTEGER,
                    disabled INTEGER NOT NULL DEFAULT 0,
                    confidence REAL NOT NULL DEFAULT 0,
                    candidates_json TEXT NOT NULL DEFAULT '[]',
                    raw_text TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(combatant_snapshot_id)
                        REFERENCES battle_combatant_snapshots(id) ON DELETE CASCADE,
                    FOREIGN KEY(skill_document_id) REFERENCES documents(id),
                    UNIQUE(combatant_snapshot_id, slot_index)
                );

                CREATE TABLE IF NOT EXISTS battle_field_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    step_id INTEGER NOT NULL UNIQUE,
                    weather TEXT NOT NULL DEFAULT '',
                    terrain TEXT NOT NULL DEFAULT '',
                    turn_time_remaining_seconds INTEGER,
                    field_effects_json TEXT NOT NULL DEFAULT '[]',
                    global_marks_json TEXT NOT NULL DEFAULT '[]',
                    victory_state TEXT NOT NULL DEFAULT '',
                    raw_text TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(step_id) REFERENCES battle_steps(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS battle_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    step_id INTEGER NOT NULL,
                    actor_side TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    action_order INTEGER,
                    priority INTEGER,
                    speed_note TEXT NOT NULL DEFAULT '',
                    success INTEGER,
                    pet_snapshot_id INTEGER,
                    skill_document_id INTEGER,
                    skill_name TEXT NOT NULL DEFAULT '',
                    target_side TEXT NOT NULL DEFAULT '',
                    energy_before INTEGER,
                    energy_cost_standard INTEGER,
                    energy_cost_observed INTEGER,
                    energy_after INTEGER,
                    from_pet_id INTEGER,
                    from_pet_name TEXT NOT NULL DEFAULT '',
                    to_pet_id INTEGER,
                    to_pet_name TEXT NOT NULL DEFAULT '',
                    raw_text TEXT NOT NULL DEFAULT '',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(step_id) REFERENCES battle_steps(id) ON DELETE CASCADE,
                    FOREIGN KEY(pet_snapshot_id) REFERENCES battle_combatant_snapshots(id),
                    FOREIGN KEY(skill_document_id) REFERENCES documents(id),
                    FOREIGN KEY(from_pet_id) REFERENCES pet_catalog(id),
                    FOREIGN KEY(to_pet_id) REFERENCES pet_catalog(id)
                );

                CREATE TABLE IF NOT EXISTS battle_action_effects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_id INTEGER,
                    step_id INTEGER NOT NULL,
                    effect_order INTEGER NOT NULL DEFAULT 0,
                    effect_type TEXT NOT NULL,
                    target_side TEXT NOT NULL DEFAULT '',
                    target_pet_id INTEGER,
                    target_pet_name TEXT NOT NULL DEFAULT '',
                    value REAL,
                    hp_before INTEGER,
                    hp_after INTEGER,
                    energy_before INTEGER,
                    energy_after INTEGER,
                    status_name TEXT NOT NULL DEFAULT '',
                    buff_name TEXT NOT NULL DEFAULT '',
                    mark_name TEXT NOT NULL DEFAULT '',
                    field_key TEXT NOT NULL DEFAULT '',
                    raw_text TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(action_id) REFERENCES battle_actions(id) ON DELETE CASCADE,
                    FOREIGN KEY(step_id) REFERENCES battle_steps(id) ON DELETE CASCADE,
                    FOREIGN KEY(target_pet_id) REFERENCES pet_catalog(id)
                );

                CREATE TABLE IF NOT EXISTS battle_transitions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    from_step_id INTEGER,
                    to_step_id INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    from_phase TEXT,
                    to_phase TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(session_id) REFERENCES battle_sessions(id) ON DELETE CASCADE,
                    FOREIGN KEY(from_step_id) REFERENCES battle_steps(id),
                    FOREIGN KEY(to_step_id) REFERENCES battle_steps(id)
                );
                """
            )
            self._ensure_schema_columns(conn)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_battle_team_session ON battle_team_members(session_id, side, team_slot)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_battle_steps_session ON battle_steps(session_id, turn_number, step_number)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_battle_snapshots_pet ON battle_combatant_snapshots(pet_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_battle_move_slots_skill ON battle_move_slots(skill_document_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_battle_actions_skill ON battle_actions(skill_document_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_battle_effects_action ON battle_action_effects(action_id, effect_order)")
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _ensure_schema_columns(conn: sqlite3.Connection) -> None:
        BattleLogStore._ensure_columns(
            conn,
            "battle_sessions",
            {
                "season": "TEXT NOT NULL DEFAULT ''",
                "battlefield": "TEXT NOT NULL DEFAULT ''",
                "rules_json": "TEXT NOT NULL DEFAULT '{}'",
                "player_name": "TEXT NOT NULL DEFAULT ''",
                "opponent_name": "TEXT NOT NULL DEFAULT ''",
                "result": "TEXT NOT NULL DEFAULT ''",
            },
        )
        BattleLogStore._ensure_columns(
            conn,
            "battle_combatant_snapshots",
            {
                "pet_name_raw": "TEXT NOT NULL DEFAULT ''",
                "energy_current": "INTEGER",
                "energy_max": "INTEGER",
                "energy_delta": "INTEGER",
                "is_active": "INTEGER NOT NULL DEFAULT 1",
                "is_fainted": "INTEGER NOT NULL DEFAULT 0",
                "raw_text": "TEXT NOT NULL DEFAULT ''",
            },
        )
        BattleLogStore._ensure_columns(
            conn,
            "battle_move_slots",
            {
                "energy_cost_standard": "INTEGER",
                "energy_cost_observed": "INTEGER",
                "cooldown_remaining": "INTEGER",
                "raw_text": "TEXT NOT NULL DEFAULT ''",
            },
        )
        BattleLogStore._ensure_columns(
            conn,
            "battle_actions",
            {
                "action_order": "INTEGER",
                "priority": "INTEGER",
                "speed_note": "TEXT NOT NULL DEFAULT ''",
                "success": "INTEGER",
                "energy_before": "INTEGER",
                "energy_cost_standard": "INTEGER",
                "energy_cost_observed": "INTEGER",
                "energy_after": "INTEGER",
                "from_pet_id": "INTEGER",
                "from_pet_name": "TEXT NOT NULL DEFAULT ''",
                "to_pet_id": "INTEGER",
                "to_pet_name": "TEXT NOT NULL DEFAULT ''",
                "raw_text": "TEXT NOT NULL DEFAULT ''",
            },
        )

    @staticmethod
    def _ensure_columns(
        conn: sqlite3.Connection,
        table_name: str,
        columns: dict[str, str],
    ) -> None:
        existing = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table_name})")}
        for column_name, column_sql in columns.items():
            if column_name not in existing:
                conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")

    def start_session(
        self,
        *,
        battle_format: str = "",
        season: str = "",
        battlefield: str = "",
        rules: dict[str, Any] | None = None,
        player_name: str = "",
        opponent_name: str = "",
        source: str = "",
        notes: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                INSERT INTO battle_sessions (
                    status, format, season, battlefield, rules_json,
                    player_name, opponent_name, source, notes, metadata_json, started_at
                ) VALUES ('active', ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    battle_format,
                    season,
                    battlefield,
                    _json_dumps(rules or {}),
                    player_name,
                    opponent_name,
                    source,
                    notes,
                    _json_dumps(metadata or {}),
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()

    def append_step(self, session_id: int, step: BattleStepInput) -> int:
        if step.event_type not in EVENT_TO_PHASE:
            raise ValueError(f"unsupported battle event type: {step.event_type}")
        phase = EVENT_TO_PHASE[step.event_type]
        if phase not in STEP_PHASES:
            raise ValueError(f"unsupported battle phase: {phase}")
        conn = self._connect()
        try:
            with conn:
                session = self._load_session(conn, session_id)
                if session["status"] != "active":
                    raise ValueError(f"battle session is not active: {session_id}")
                previous = self._load_last_step(conn, session_id)
                previous_phase = str(previous["phase"]) if previous is not None else None
                allowed = ALLOWED_NEXT_EVENTS[previous_phase]
                if step.event_type not in allowed:
                    raise ValueError(
                        f"cannot apply event {step.event_type!r} after phase {previous_phase!r}"
                    )
                self._upsert_team_members(conn, session_id, step.teams)
                step_id = self._insert_step(conn, session_id, phase, step)
                self._insert_field_snapshot(conn, step_id, step)
                snapshot_ids = self._insert_combatants(conn, step_id, step)
                self._insert_actions(conn, step_id, step, snapshot_ids)
                conn.execute(
                    """
                    INSERT INTO battle_transitions (
                        session_id, from_step_id, to_step_id, event_type,
                        from_phase, to_phase, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        session_id,
                        int(previous["id"]) if previous is not None else None,
                        step_id,
                        step.event_type,
                        previous_phase,
                        phase,
                        _json_dumps({"turn_number": step.turn_number, "step_number": step.step_number}),
                    ),
                )
                if step.event_type == "finish":
                    result = ""
                    if step.field_snapshot is not None:
                        result = step.field_snapshot.victory_state
                    if not result:
                        result = str(step.metadata.get("result", "")).strip()
                    conn.execute(
                        """
                        UPDATE battle_sessions
                        SET status = 'completed',
                            result = CASE WHEN ? = '' THEN result ELSE ? END,
                            ended_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (result, result, session_id),
                    )
                return step_id
        finally:
            conn.close()

    def abandon_session(self, session_id: int, *, reason: str = "") -> None:
        conn = self._connect()
        try:
            with conn:
                self._load_session(conn, session_id)
                conn.execute(
                    """
                    UPDATE battle_sessions
                    SET status = 'abandoned',
                        notes = CASE WHEN ? = '' THEN notes ELSE ? END,
                        ended_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (reason, reason, session_id),
                )
        finally:
            conn.close()

    def list_steps(self, session_id: int) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT *
                FROM battle_steps
                WHERE session_id = ?
                ORDER BY turn_number, step_number
                """,
                (session_id,),
            ).fetchall()
            return [self._step_row_to_dict(row) for row in rows]
        finally:
            conn.close()

    def load_session_timeline(self, session_id: int) -> dict[str, Any]:
        conn = self._connect()
        try:
            session = dict(self._load_session(conn, session_id))
            session["rules"] = _loads_json(session.pop("rules_json"), {})
            session["metadata"] = _loads_json(session.pop("metadata_json"), {})
            teams = [
                self._team_member_row_to_dict(row)
                for row in conn.execute(
                    """
                    SELECT *
                    FROM battle_team_members
                    WHERE session_id = ?
                    ORDER BY side, team_slot
                    """,
                    (session_id,),
                ).fetchall()
            ]
            steps = [
                self.load_step(int(row["id"]))
                for row in conn.execute(
                    """
                    SELECT id
                    FROM battle_steps
                    WHERE session_id = ?
                    ORDER BY turn_number, step_number, id
                    """,
                    (session_id,),
                ).fetchall()
            ]
            return {"session": session, "teams": teams, "steps": steps}
        finally:
            conn.close()

    def load_step(self, step_id: int) -> dict[str, Any]:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM battle_steps WHERE id = ?", (step_id,)).fetchone()
            if row is None:
                raise ValueError(f"battle step not found: {step_id}")
            payload = self._step_row_to_dict(row)
            snapshots = conn.execute(
                """
                SELECT *
                FROM battle_combatant_snapshots
                WHERE step_id = ?
                ORDER BY side
                """,
                (step_id,),
            ).fetchall()
            payload["combatants"] = [self._snapshot_row_to_dict(conn, snapshot) for snapshot in snapshots]
            field_snapshot = conn.execute(
                "SELECT * FROM battle_field_snapshots WHERE step_id = ?",
                (step_id,),
            ).fetchone()
            payload["field_snapshot"] = (
                self._field_snapshot_row_to_dict(field_snapshot)
                if field_snapshot is not None
                else None
            )
            payload["actions"] = [
                self._action_row_to_dict(conn, row)
                for row in conn.execute(
                    "SELECT * FROM battle_actions WHERE step_id = ? ORDER BY id",
                    (step_id,),
                ).fetchall()
            ]
            return payload
        finally:
            conn.close()

    def _insert_step(
        self,
        conn: sqlite3.Connection,
        session_id: int,
        phase: str,
        step: BattleStepInput,
    ) -> int:
        cursor = conn.execute(
            """
            INSERT INTO battle_steps (
                session_id, turn_number, step_number, phase, event_type,
                screenshot_path, analysis_log_path, field_state_json, advice_json,
                recognition_json, confidence_json, uncertainties_json, metadata_json,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                session_id,
                step.turn_number,
                step.step_number,
                phase,
                step.event_type,
                step.screenshot_path,
                step.analysis_log_path,
                _json_dumps(step.field_state),
                _json_dumps(step.advice),
                _json_dumps(step.recognition),
                _json_dumps(step.confidence),
                _json_dumps(step.uncertainties),
                _json_dumps(step.metadata),
            ),
        )
        return int(cursor.lastrowid)

    def _upsert_team_members(
        self,
        conn: sqlite3.Connection,
        session_id: int,
        team_members: list[BattleTeamMember],
    ) -> None:
        for member in team_members:
            if member.side not in SIDES:
                raise ValueError(f"unsupported team member side: {member.side}")
            pet_name = member.pet_name or member.pet_name_raw
            pet_id = member.pet_id or self._resolve_pet_id(conn, pet_name)
            conn.execute(
                """
                INSERT INTO battle_team_members (
                    session_id, side, team_slot, pet_id, pet_name, pet_name_raw,
                    primary_attribute, secondary_attribute, level_normalized,
                    is_active, is_fainted, has_entered, confidence, raw_text,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, side, team_slot) DO UPDATE SET
                    pet_id=excluded.pet_id,
                    pet_name=excluded.pet_name,
                    pet_name_raw=excluded.pet_name_raw,
                    primary_attribute=excluded.primary_attribute,
                    secondary_attribute=excluded.secondary_attribute,
                    level_normalized=excluded.level_normalized,
                    is_active=excluded.is_active,
                    is_fainted=excluded.is_fainted,
                    has_entered=excluded.has_entered,
                    confidence=excluded.confidence,
                    raw_text=excluded.raw_text,
                    metadata_json=excluded.metadata_json
                """,
                (
                    session_id,
                    member.side,
                    member.team_slot,
                    pet_id,
                    pet_name,
                    member.pet_name_raw or pet_name,
                    member.primary_attribute,
                    member.secondary_attribute,
                    _optional_bool_to_int(member.level_normalized),
                    int(member.is_active),
                    int(member.is_fainted),
                    int(member.has_entered),
                    member.confidence,
                    member.raw_text,
                    _json_dumps(member.metadata),
                ),
            )

    def _insert_field_snapshot(
        self,
        conn: sqlite3.Connection,
        step_id: int,
        step: BattleStepInput,
    ) -> None:
        snapshot = step.field_snapshot
        if snapshot is None and not step.field_state:
            return
        if snapshot is None:
            snapshot = BattleFieldSnapshot(metadata={"field_state": step.field_state})
        conn.execute(
            """
            INSERT INTO battle_field_snapshots (
                step_id, weather, terrain, turn_time_remaining_seconds,
                field_effects_json, global_marks_json, victory_state, raw_text,
                metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                step_id,
                snapshot.weather,
                snapshot.terrain,
                snapshot.turn_time_remaining_seconds,
                _json_dumps(snapshot.field_effects),
                _json_dumps(snapshot.global_marks),
                snapshot.victory_state,
                snapshot.raw_text,
                _json_dumps(snapshot.metadata),
            ),
        )

    def _insert_combatants(
        self,
        conn: sqlite3.Connection,
        step_id: int,
        step: BattleStepInput,
    ) -> dict[str, int]:
        snapshot_ids: dict[str, int] = {}
        for combatant in (step.player, step.opponent):
            if combatant is None:
                continue
            if combatant.side not in SIDES:
                raise ValueError(f"unsupported combatant side: {combatant.side}")
            pet_name = combatant.pet_name or combatant.pet_name_raw
            pet_id = combatant.pet_id or self._resolve_pet_id(conn, pet_name)
            cursor = conn.execute(
                """
                INSERT INTO battle_combatant_snapshots (
                    step_id, side, pet_id, pet_name, pet_name_raw, hp_state,
                    hp_current, hp_max, hp_percent, energy_current, energy_max,
                    energy_delta, status_json, buffs_json, marks_json, ability,
                    item, is_active, is_fainted, confidence, raw_text,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    step_id,
                    combatant.side,
                    pet_id,
                    pet_name,
                    combatant.pet_name_raw or pet_name,
                    combatant.hp_state,
                    combatant.hp_current,
                    combatant.hp_max,
                    combatant.hp_percent,
                    combatant.energy_current,
                    combatant.energy_max,
                    combatant.energy_delta,
                    _json_dumps(combatant.status_effects),
                    _json_dumps(combatant.buffs),
                    _json_dumps(combatant.marks),
                    combatant.ability,
                    combatant.item,
                    int(combatant.is_active),
                    int(combatant.is_fainted),
                    combatant.confidence,
                    combatant.raw_text,
                    _json_dumps(combatant.metadata),
                ),
            )
            snapshot_id = int(cursor.lastrowid)
            snapshot_ids[combatant.side] = snapshot_id
            for move_slot in combatant.move_slots:
                self._insert_move_slot(conn, snapshot_id, move_slot)
        return snapshot_ids

    def _insert_move_slot(
        self,
        conn: sqlite3.Connection,
        snapshot_id: int,
        move_slot: BattleMoveSlot,
    ) -> None:
        skill_document_id = move_slot.skill_document_id or self._resolve_skill_document_id(
            conn,
            move_slot.skill_name,
        )
        energy_cost_standard = move_slot.energy_cost_standard
        if energy_cost_standard is None and skill_document_id is not None:
            energy_cost_standard = self._resolve_skill_energy_cost(conn, skill_document_id)
        conn.execute(
            """
            INSERT INTO battle_move_slots (
                combatant_snapshot_id, slot_index, skill_document_id, skill_name,
                pp_remaining, pp_max, energy_cost_standard, energy_cost_observed,
                cooldown_remaining, disabled, confidence, candidates_json, raw_text,
                metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                move_slot.slot_index,
                skill_document_id,
                move_slot.skill_name,
                move_slot.pp_remaining,
                move_slot.pp_max,
                energy_cost_standard,
                move_slot.energy_cost_observed,
                move_slot.cooldown_remaining,
                int(move_slot.disabled),
                move_slot.confidence,
                _json_dumps(move_slot.candidates),
                move_slot.raw_text,
                _json_dumps(move_slot.metadata),
            ),
        )

    def _insert_actions(
        self,
        conn: sqlite3.Connection,
        step_id: int,
        step: BattleStepInput,
        snapshot_ids: dict[str, int],
    ) -> None:
        for action in step.actions:
            if action.actor_side not in SIDES:
                raise ValueError(f"unsupported action side: {action.actor_side}")
            if action.action_type not in ACTION_TYPES:
                raise ValueError(f"unsupported action type: {action.action_type}")
            skill_document_id = action.skill_document_id or self._resolve_skill_document_id(
                conn,
                action.skill_name,
            )
            energy_cost_standard = action.energy_cost_standard
            if energy_cost_standard is None and skill_document_id is not None:
                energy_cost_standard = self._resolve_skill_energy_cost(conn, skill_document_id)
            from_pet_id = action.from_pet_id or self._resolve_pet_id(conn, action.from_pet_name)
            to_pet_id = action.to_pet_id or self._resolve_pet_id(conn, action.to_pet_name)
            cursor = conn.execute(
                """
                INSERT INTO battle_actions (
                    step_id, actor_side, action_type, action_order, priority,
                    speed_note, success, pet_snapshot_id, skill_document_id,
                    skill_name, target_side, energy_before, energy_cost_standard,
                    energy_cost_observed, energy_after, from_pet_id, from_pet_name,
                    to_pet_id, to_pet_name, raw_text, result_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    step_id,
                    action.actor_side,
                    action.action_type,
                    action.action_order,
                    action.priority,
                    action.speed_note,
                    _optional_bool_to_int(action.success),
                    snapshot_ids.get(action.actor_side),
                    skill_document_id,
                    action.skill_name,
                    action.target_side,
                    action.energy_before,
                    energy_cost_standard,
                    action.energy_cost_observed,
                    action.energy_after,
                    from_pet_id,
                    action.from_pet_name,
                    to_pet_id,
                    action.to_pet_name,
                    action.raw_text,
                    _json_dumps(action.result),
                    _json_dumps(action.metadata),
                ),
            )
            action_id = int(cursor.lastrowid)
            for effect in action.effects:
                self._insert_action_effect(conn, step_id, action_id, effect)

    def _insert_action_effect(
        self,
        conn: sqlite3.Connection,
        step_id: int,
        action_id: int | None,
        effect: BattleActionEffect,
    ) -> None:
        if effect.effect_type not in EFFECT_TYPES:
            raise ValueError(f"unsupported battle effect type: {effect.effect_type}")
        if effect.target_side and effect.target_side not in SIDES:
            raise ValueError(f"unsupported effect target side: {effect.target_side}")
        target_pet_id = effect.target_pet_id or self._resolve_pet_id(conn, effect.target_pet_name)
        conn.execute(
            """
            INSERT INTO battle_action_effects (
                action_id, step_id, effect_order, effect_type, target_side,
                target_pet_id, target_pet_name, value, hp_before, hp_after,
                energy_before, energy_after, status_name, buff_name, mark_name,
                field_key, raw_text, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                action_id,
                step_id,
                effect.effect_order,
                effect.effect_type,
                effect.target_side,
                target_pet_id,
                effect.target_pet_name,
                effect.value,
                effect.hp_before,
                effect.hp_after,
                effect.energy_before,
                effect.energy_after,
                effect.status_name,
                effect.buff_name,
                effect.mark_name,
                effect.field_key,
                effect.raw_text,
                _json_dumps(effect.metadata),
            ),
        )

    @staticmethod
    def _load_session(conn: sqlite3.Connection, session_id: int) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM battle_sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            raise ValueError(f"battle session not found: {session_id}")
        return row

    @staticmethod
    def _load_last_step(conn: sqlite3.Connection, session_id: int) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT *
            FROM battle_steps
            WHERE session_id = ?
            ORDER BY turn_number DESC, step_number DESC, id DESC
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()

    @classmethod
    def _resolve_pet_id(cls, conn: sqlite3.Connection, raw_name: str) -> int | None:
        normalized = _normalize_name(raw_name)
        if not normalized:
            return None
        try:
            rows = conn.execute("SELECT id, name, aliases FROM pet_catalog").fetchall()
        except sqlite3.OperationalError:
            return None
        for row in rows:
            if _normalize_name(str(row["name"])) == normalized:
                return int(row["id"])
        for row in rows:
            aliases = _loads_json(row["aliases"], [])
            if any(_normalize_name(str(alias)) == normalized for alias in aliases):
                return int(row["id"])
        return None

    @staticmethod
    def _resolve_skill_document_id(conn: sqlite3.Connection, raw_name: str) -> int | None:
        normalized = _normalize_name(raw_name)
        if not normalized:
            return None
        try:
            rows = conn.execute(
                """
                SELECT id, title, source_path
                FROM documents
                WHERE source_type = 'rocom_skill' OR source_path LIKE 'rocom_skill::%'
                """
            ).fetchall()
        except sqlite3.OperationalError:
            return None
        for row in rows:
            if _normalize_name(str(row["title"])) == normalized:
                return int(row["id"])
            source_name = str(row["source_path"]).removeprefix("rocom_skill::")
            if _normalize_name(source_name) == normalized:
                return int(row["id"])
        return None

    @staticmethod
    def _resolve_skill_energy_cost(conn: sqlite3.Connection, skill_document_id: int) -> int | None:
        row = conn.execute(
            "SELECT content FROM documents WHERE id = ?",
            (skill_document_id,),
        ).fetchone()
        if row is None:
            return None
        content = str(row["content"])
        for pattern in (r"\u8017\u80fd[:\uff1a]\s*(\d+)", r"\u8017\u80fd\s*(\d+)"):
            match = re.search(pattern, content)
            if match:
                return int(match.group(1))
        return None

    @staticmethod
    def _step_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        for key, fallback in (
            ("field_state_json", {}),
            ("advice_json", {}),
            ("recognition_json", {}),
            ("confidence_json", {}),
            ("uncertainties_json", []),
            ("metadata_json", {}),
        ):
            public_key = key.removesuffix("_json")
            payload[public_key] = _loads_json(payload.pop(key), fallback)
        return payload

    @staticmethod
    def _team_member_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["level_normalized"] = _optional_int_to_bool(payload["level_normalized"])
        payload["is_active"] = bool(payload["is_active"])
        payload["is_fainted"] = bool(payload["is_fainted"])
        payload["has_entered"] = bool(payload["has_entered"])
        payload["metadata"] = _loads_json(payload.pop("metadata_json"), {})
        return payload

    @staticmethod
    def _field_snapshot_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["field_effects"] = _loads_json(payload.pop("field_effects_json"), [])
        payload["global_marks"] = _loads_json(payload.pop("global_marks_json"), [])
        payload["metadata"] = _loads_json(payload.pop("metadata_json"), {})
        return payload

    @staticmethod
    def _snapshot_row_to_dict(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["is_active"] = bool(payload["is_active"])
        payload["is_fainted"] = bool(payload["is_fainted"])
        for key, fallback in (
            ("status_json", []),
            ("buffs_json", {}),
            ("marks_json", []),
            ("metadata_json", {}),
        ):
            public_key = "status_effects" if key == "status_json" else key.removesuffix("_json")
            payload[public_key] = _loads_json(payload.pop(key), fallback)
        payload["move_slots"] = [
            BattleLogStore._move_slot_row_to_dict(slot)
            for slot in conn.execute(
                """
                SELECT *
                FROM battle_move_slots
                WHERE combatant_snapshot_id = ?
                ORDER BY slot_index
                """,
                (row["id"],),
            ).fetchall()
        ]
        return payload

    @staticmethod
    def _move_slot_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["disabled"] = bool(payload["disabled"])
        payload["candidates"] = _loads_json(payload.pop("candidates_json"), [])
        payload["metadata"] = _loads_json(payload.pop("metadata_json"), {})
        return payload

    @staticmethod
    def _action_row_to_dict(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["success"] = _optional_int_to_bool(payload["success"])
        payload["result"] = _loads_json(payload.pop("result_json"), {})
        payload["metadata"] = _loads_json(payload.pop("metadata_json"), {})
        payload["effects"] = [
            BattleLogStore._action_effect_row_to_dict(effect)
            for effect in conn.execute(
                """
                SELECT *
                FROM battle_action_effects
                WHERE action_id = ?
                ORDER BY effect_order, id
                """,
                (row["id"],),
            ).fetchall()
        ]
        return payload

    @staticmethod
    def _action_effect_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["metadata"] = _loads_json(payload.pop("metadata_json"), {})
        return payload


def _json_dumps(value: Any) -> str:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    elif hasattr(value, "__dataclass_fields__"):
        value = asdict(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _loads_json(value: str | None, fallback: Any) -> Any:
    if value is None:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _normalize_name(value: str) -> str:
    return "".join(str(value).lower().strip().split())


def _optional_bool_to_int(value: bool | None) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_int_to_bool(value: int | None) -> bool | None:
    if value is None:
        return None
    return bool(value)
