from __future__ import annotations

import json
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
ACTION_TYPES = {"move", "switch", "item", "unknown", "pass"}


@dataclass(slots=True)
class BattleMoveSlot:
    slot_index: int
    skill_name: str = ""
    skill_document_id: int | None = None
    pp_remaining: int | None = None
    pp_max: int | None = None
    disabled: bool = False
    confidence: float = 0.0
    candidates: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BattleCombatantSnapshot:
    side: str
    pet_name: str = ""
    pet_id: int | None = None
    hp_state: str = ""
    hp_current: int | None = None
    hp_max: int | None = None
    hp_percent: float | None = None
    status_effects: list[str] = field(default_factory=list)
    buffs: dict[str, Any] = field(default_factory=dict)
    marks: list[dict[str, Any]] = field(default_factory=list)
    ability: str = ""
    item: str = ""
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    move_slots: list[BattleMoveSlot] = field(default_factory=list)


@dataclass(slots=True)
class BattleAction:
    actor_side: str
    action_type: str = "unknown"
    skill_name: str = ""
    skill_document_id: int | None = None
    target_side: str = ""
    result: dict[str, Any] = field(default_factory=dict)
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
                    source TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    ended_at TEXT
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
                    hp_state TEXT NOT NULL DEFAULT '',
                    hp_current INTEGER,
                    hp_max INTEGER,
                    hp_percent REAL,
                    status_json TEXT NOT NULL DEFAULT '[]',
                    buffs_json TEXT NOT NULL DEFAULT '{}',
                    marks_json TEXT NOT NULL DEFAULT '[]',
                    ability TEXT NOT NULL DEFAULT '',
                    item TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 0,
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
                    disabled INTEGER NOT NULL DEFAULT 0,
                    confidence REAL NOT NULL DEFAULT 0,
                    candidates_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(combatant_snapshot_id)
                        REFERENCES battle_combatant_snapshots(id) ON DELETE CASCADE,
                    FOREIGN KEY(skill_document_id) REFERENCES documents(id),
                    UNIQUE(combatant_snapshot_id, slot_index)
                );

                CREATE TABLE IF NOT EXISTS battle_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    step_id INTEGER NOT NULL,
                    actor_side TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    pet_snapshot_id INTEGER,
                    skill_document_id INTEGER,
                    skill_name TEXT NOT NULL DEFAULT '',
                    target_side TEXT NOT NULL DEFAULT '',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(step_id) REFERENCES battle_steps(id) ON DELETE CASCADE,
                    FOREIGN KEY(pet_snapshot_id) REFERENCES battle_combatant_snapshots(id),
                    FOREIGN KEY(skill_document_id) REFERENCES documents(id)
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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_battle_steps_session ON battle_steps(session_id, turn_number, step_number)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_battle_snapshots_pet ON battle_combatant_snapshots(pet_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_battle_move_slots_skill ON battle_move_slots(skill_document_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_battle_actions_skill ON battle_actions(skill_document_id)")
            conn.commit()
        finally:
            conn.close()

    def start_session(
        self,
        *,
        battle_format: str = "",
        source: str = "",
        notes: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                INSERT INTO battle_sessions (
                    status, format, source, notes, metadata_json, started_at
                ) VALUES ('active', ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (battle_format, source, notes, _json_dumps(metadata or {})),
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
                step_id = self._insert_step(conn, session_id, phase, step)
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
                    conn.execute(
                        """
                        UPDATE battle_sessions
                        SET status = 'completed', ended_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (session_id,),
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
            payload["actions"] = [
                self._action_row_to_dict(row)
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
            pet_id = combatant.pet_id or self._resolve_pet_id(conn, combatant.pet_name)
            cursor = conn.execute(
                """
                INSERT INTO battle_combatant_snapshots (
                    step_id, side, pet_id, pet_name, hp_state, hp_current, hp_max,
                    hp_percent, status_json, buffs_json, marks_json, ability, item,
                    confidence, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    step_id,
                    combatant.side,
                    pet_id,
                    combatant.pet_name,
                    combatant.hp_state,
                    combatant.hp_current,
                    combatant.hp_max,
                    combatant.hp_percent,
                    _json_dumps(combatant.status_effects),
                    _json_dumps(combatant.buffs),
                    _json_dumps(combatant.marks),
                    combatant.ability,
                    combatant.item,
                    combatant.confidence,
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
        conn.execute(
            """
            INSERT INTO battle_move_slots (
                combatant_snapshot_id, slot_index, skill_document_id, skill_name,
                pp_remaining, pp_max, disabled, confidence, candidates_json, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                move_slot.slot_index,
                skill_document_id,
                move_slot.skill_name,
                move_slot.pp_remaining,
                move_slot.pp_max,
                int(move_slot.disabled),
                move_slot.confidence,
                _json_dumps(move_slot.candidates),
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
            conn.execute(
                """
                INSERT INTO battle_actions (
                    step_id, actor_side, action_type, pet_snapshot_id,
                    skill_document_id, skill_name, target_side, result_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    step_id,
                    action.actor_side,
                    action.action_type,
                    snapshot_ids.get(action.actor_side),
                    skill_document_id,
                    action.skill_name,
                    action.target_side,
                    _json_dumps(action.result),
                    _json_dumps(action.metadata),
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
    def _snapshot_row_to_dict(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
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
    def _action_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["result"] = _loads_json(payload.pop("result_json"), {})
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
