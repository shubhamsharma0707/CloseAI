"""
memory_store.py — RISHI's Persistent Memory Layer
====================================================
Gives RISHI (and its orchestrators: Chanakya, Kavach, Engineer) memory that
survives a server restart. The in-memory `shared_blackboard` in RISHI.py is
still used for fast, ephemeral, within-task scratch space — this module is
the durable layer underneath it.

Why SQLite, not a new service
------------------------------
RISHI is explicitly local-first and already zero-extra-infra (FastAPI +
Ollama). SQLite ships with Python, needs no daemon, and a single file
(rishi_memory.db) is trivial to back up, inspect, or wipe. This matches the
project's existing pattern (hash-chained .jsonl ledgers) of "durable but
file-based, no external dependency."

Three tables, three different jobs
-----------------------------------
1. episodes      — every completed task attempt: what was asked, which
                    agent handled it, what happened, success/fail, how long.
                    This is RISHI's "experience."
2. corrections    — specifically moments where a HUMAN overrode, rejected,
                    or corrected RISHI/an agent. Weighted higher than
                    self-reported outcomes in episodes, because user
                    correction is ground truth and self-assessment isn't.
3. facts          — durable, revisable knowledge extracted over time
                    ("user prefers qwen3:30b for finance tasks"). Each fact
                    has a confidence score that rises on reinforcement and
                    falls (or the fact is retired) on contradiction — facts
                    are never silently overwritten, so the history of what
                    RISHI used to believe is auditable too.

Concurrency
-----------
RISHI is an asyncio app with multiple agents writing concurrently. SQLite
handles concurrent readers fine but serializes writers — we keep write
transactions short and wrap every write in a module-level asyncio.Lock so
two coroutines never interleave a multi-statement write.
"""

import json
import logging
import os
import sqlite3
import time
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("RISHI.Memory")

DB_PATH = os.path.join(os.path.dirname(__file__), "rishi_memory.db")

_write_lock = asyncio.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS episodes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    task_summary    TEXT NOT NULL,
    outcome         TEXT NOT NULL,          -- 'success' | 'failure' | 'partial'
    detail          TEXT,                   -- free-text or JSON detail
    duration_ms     INTEGER,
    source_ledger   TEXT                    -- which .jsonl this was backfilled from, if any
);
CREATE INDEX IF NOT EXISTS idx_episodes_agent   ON episodes(agent_id);
CREATE INDEX IF NOT EXISTS idx_episodes_outcome ON episodes(outcome);
CREATE INDEX IF NOT EXISTS idx_episodes_time    ON episodes(timestamp);

CREATE TABLE IF NOT EXISTS corrections (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    what_rishi_did  TEXT NOT NULL,
    what_user_wanted TEXT NOT NULL,
    episode_id      INTEGER,                -- optional FK to episodes.id
    FOREIGN KEY (episode_id) REFERENCES episodes(id)
);
CREATE INDEX IF NOT EXISTS idx_corrections_agent ON corrections(agent_id);

CREATE TABLE IF NOT EXISTS facts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fact_key        TEXT NOT NULL,
    fact_value      TEXT NOT NULL,
    category        TEXT NOT NULL DEFAULT 'general',
    confidence      REAL NOT NULL DEFAULT 0.6,
    reinforced_count INTEGER NOT NULL DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'active',  -- 'active' | 'retired'
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_key    ON facts(fact_key);
CREATE INDEX IF NOT EXISTS idx_facts_status ON facts(status);
"""


@contextmanager
def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    with _connect() as conn:
        conn.executescript(_SCHEMA)
    logger.info(f"[Memory] Database ready at {DB_PATH}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# EPISODES — "what happened"
# ---------------------------------------------------------------------------
async def record_episode(
    agent_id: str,
    task_summary: str,
    outcome: str,
    detail: str = "",
    duration_ms: Optional[int] = None,
    source_ledger: Optional[str] = None,
) -> int:
    """Record one completed task attempt. Returns the new episode's row id."""
    if outcome not in ("success", "failure", "partial"):
        outcome = "partial"
    async with _write_lock:
        with _connect() as conn:
            cur = conn.execute(
                "INSERT INTO episodes (timestamp, agent_id, task_summary, outcome, detail, duration_ms, source_ledger) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (_now(), agent_id, task_summary, outcome, detail, duration_ms, source_ledger),
            )
            return cur.lastrowid


async def recall_recent_episodes(agent_id: Optional[str] = None, n: int = 10, outcome: Optional[str] = None) -> str:
    """
    Return the n most recent episodes as a JSON string, optionally filtered
    by agent_id and/or outcome. This is what an orchestrator calls before
    retrying a task, to check "have I seen something like this before."
    """
    query = "SELECT timestamp, agent_id, task_summary, outcome, detail FROM episodes WHERE 1=1"
    params: list = []
    if agent_id:
        query += " AND agent_id = ?"
        params.append(agent_id)
    if outcome:
        query += " AND outcome = ?"
        params.append(outcome)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(n)

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return json.dumps([dict(r) for r in rows], default=str)


# ---------------------------------------------------------------------------
# CORRECTIONS — "what the human actually wanted instead"
# ---------------------------------------------------------------------------
async def record_correction(
    agent_id: str,
    what_rishi_did: str,
    what_user_wanted: str,
    episode_id: Optional[int] = None,
) -> int:
    """
    Record a human correction. These carry more weight than self-reported
    episode outcomes — RISHI marking its own work 'success' is a claim;
    a user correction is evidence.
    """
    async with _write_lock:
        with _connect() as conn:
            cur = conn.execute(
                "INSERT INTO corrections (timestamp, agent_id, what_rishi_did, what_user_wanted, episode_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (_now(), agent_id, what_rishi_did, what_user_wanted, episode_id),
            )
            return cur.lastrowid


async def recall_corrections(agent_id: Optional[str] = None, n: int = 10) -> str:
    """Return recent corrections as JSON, optionally filtered by agent."""
    query = "SELECT timestamp, agent_id, what_rishi_did, what_user_wanted FROM corrections WHERE 1=1"
    params: list = []
    if agent_id:
        query += " AND agent_id = ?"
        params.append(agent_id)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(n)
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return json.dumps([dict(r) for r in rows], default=str)


# ---------------------------------------------------------------------------
# FACTS — durable, revisable knowledge
# ---------------------------------------------------------------------------
async def remember(key: str, value: str, category: str = "general", confidence: float = 0.6) -> str:
    """
    Store or reinforce a durable fact. If an active fact with the same key
    already exists:
      - same value  -> reinforce (confidence rises, capped at 0.99)
      - different value -> the OLD fact is retired (status='retired', kept
        for audit) and a NEW fact row is inserted. We never silently
        overwrite — both versions stay queryable.
    """
    async with _write_lock:
        with _connect() as conn:
            existing = conn.execute(
                "SELECT id, fact_value, confidence, reinforced_count FROM facts "
                "WHERE fact_key = ? AND status = 'active'",
                (key,),
            ).fetchone()

            if existing is None:
                conn.execute(
                    "INSERT INTO facts (fact_key, fact_value, category, confidence, reinforced_count, status, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, 1, 'active', ?, ?)",
                    (key, value, category, confidence, _now(), _now()),
                )
                return f"Stored new fact: '{key}' = '{value}'"

            if existing["fact_value"] == value:
                new_confidence = min(0.99, existing["confidence"] + 0.05)
                conn.execute(
                    "UPDATE facts SET confidence = ?, reinforced_count = reinforced_count + 1, updated_at = ? WHERE id = ?",
                    (new_confidence, _now(), existing["id"]),
                )
                return f"Reinforced existing fact: '{key}' (confidence now {new_confidence:.2f})"

            # Value changed — retire the old, insert the new, both stay on record.
            conn.execute("UPDATE facts SET status = 'retired', updated_at = ? WHERE id = ?", (_now(), existing["id"]))
            conn.execute(
                "INSERT INTO facts (fact_key, fact_value, category, confidence, reinforced_count, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 1, 'active', ?, ?)",
                (key, value, category, confidence, _now(), _now()),
            )
            return f"Updated fact '{key}': '{existing['fact_value']}' -> '{value}' (previous value retired, not deleted)"


async def recall(query: str, category: Optional[str] = None, limit: int = 10) -> str:
    """
    Look up facts whose key or value contains `query` (simple substring
    match — this is local-first key-value memory, not a vector DB).
    Returns active facts only, ordered by confidence.
    """
    sql = "SELECT fact_key, fact_value, category, confidence, reinforced_count, updated_at FROM facts WHERE status = 'active' AND (fact_key LIKE ? OR fact_value LIKE ?)"
    params: list = [f"%{query}%", f"%{query}%"]
    if category:
        sql += " AND category = ?"
        params.append(category)
    sql += " ORDER BY confidence DESC LIMIT ?"
    params.append(limit)

    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return json.dumps([dict(r) for r in rows], default=str)


# ---------------------------------------------------------------------------
# BACKFILL — seed episodic memory from the existing hash-chained ledgers
# so memory doesn't start completely empty on first run.
# ---------------------------------------------------------------------------
def backfill_from_ledger(ledger_path: str, default_agent_id: str = "unknown") -> int:
    """
    One-time (idempotent via source_ledger check) import of a *_audit_ledger.jsonl
    file into the episodes table. Synchronous — intended to be called once at
    startup, before the event loop is handling traffic.
    """
    if not os.path.exists(ledger_path):
        return 0

    ledger_name = os.path.basename(ledger_path)
    with _connect() as conn:
        already_done = conn.execute(
            "SELECT COUNT(*) as c FROM episodes WHERE source_ledger = ?", (ledger_name,)
        ).fetchone()["c"]
        if already_done > 0:
            return 0  # already backfilled in a prior run

        count = 0
        with open(ledger_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                agent_id = entry.get("agent_id", default_agent_id)
                payload_raw = entry.get("payload", "{}")
                try:
                    payload = json.loads(payload_raw) if isinstance(payload_raw, str) else payload_raw
                except json.JSONDecodeError:
                    payload = {"raw": payload_raw}

                phase = payload.get("phase") or payload.get("event_type") or "UNKNOWN_EVENT"
                outcome = "failure" if ("FAIL" in str(phase).upper() or "DENIED" in str(phase).upper()) else "success"

                conn.execute(
                    "INSERT INTO episodes (timestamp, agent_id, task_summary, outcome, detail, source_ledger) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        entry.get("timestamp", _now()),
                        agent_id,
                        str(phase),
                        outcome,
                        json.dumps(payload.get("event_data", payload))[:2000],
                        ledger_name,
                    ),
                )
                count += 1
        logger.info(f"[Memory] Backfilled {count} episodes from {ledger_name}")
        return count


def backfill_all_ledgers(project_root: Optional[str] = None) -> dict:
    """Backfill every *_audit_ledger.jsonl found in the project root."""
    root = project_root or os.path.dirname(__file__)
    results = {}
    for fname in os.listdir(root):
        if fname.endswith("_audit_ledger.jsonl"):
            results[fname] = backfill_from_ledger(os.path.join(root, fname))
    return results


# ---------------------------------------------------------------------------
# TOOL MAP — mirrors RISHI.py's TOOL_IMPLEMENTATIONS pattern so these can be
# merged straight into it with a single dict.update() call.
# ---------------------------------------------------------------------------
MEMORY_TOOL_IMPLEMENTATIONS: dict[str, tuple] = {
    "remember": (
        remember,
        "Store or reinforce a durable fact RISHI should retain across sessions. "
        "If the key already exists with a different value, the old value is retired (kept for audit) "
        "and the new value becomes active — nothing is silently overwritten.",
    ),
    "recall": (
        recall,
        "Search stored facts by substring match on key or value, optionally filtered by category. "
        "Returns active facts ordered by confidence.",
    ),
    "recall_recent_episodes": (
        recall_recent_episodes,
        "Return the most recent task episodes (successes/failures/partials) for an agent, "
        "optionally filtered by outcome. Use this before retrying a task to check for precedent.",
    ),
}


if __name__ == "__main__":
    # Manual smoke test / first-time setup.
    logging.basicConfig(level=logging.INFO)
    init_db()
    results = backfill_all_ledgers()
    print(json.dumps(results, indent=2))
