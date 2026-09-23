"""Small SQLite persistence layer for tasks and student proposals."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "aisana.db"


def _db_path(path: str | os.PathLike[str] | None = None) -> Path:
    configured = path or os.getenv("AISANA_DB_PATH") or DEFAULT_DB_PATH
    return Path(configured).expanduser().resolve()


def _connect(path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    db_path = _db_path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db(path: str | os.PathLike[str] | None = None) -> None:
    """Create tables if needed. Safe to call on every app start."""
    with _connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'draft',
                topic TEXT NOT NULL DEFAULT '',
                raw_text TEXT NOT NULL DEFAULT '',
                card_json TEXT NOT NULL DEFAULT '{}',
                field_status_json TEXT NOT NULL DEFAULT '{}',
                score INTEGER NOT NULL DEFAULT 0,
                level TEXT NOT NULL DEFAULT 'черновик',
                score_history_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                published_at TEXT
            );
            CREATE TABLE IF NOT EXISTS proposals (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                team_name TEXT NOT NULL DEFAULT '',
                idea TEXT NOT NULL DEFAULT '',
                plan TEXT NOT NULL DEFAULT '',
                timeline TEXT NOT NULL DEFAULT '',
                link TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'new',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_catalog
                ON tasks(status, score DESC, published_at, id);
            CREATE INDEX IF NOT EXISTS idx_proposals_task
                ON proposals(task_id, created_at);
            """
        )


def _json(value: Any, fallback: str) -> str:
    return json.dumps(value if value is not None else json.loads(fallback), ensure_ascii=False)


def save_task(task: dict[str, Any], path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Insert or update a Task-shaped dictionary and return it."""
    required = ("id", "created_at")
    missing = [field for field in required if not task.get(field)]
    if missing:
        raise ValueError(f"task missing required fields: {', '.join(missing)}")
    card = task.get("card") or {}
    with _connect(path) as connection:
        connection.execute(
            """INSERT INTO tasks
               (id,status,topic,raw_text,card_json,field_status_json,score,level,
                score_history_json,created_at,published_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 status=excluded.status, topic=excluded.topic, raw_text=excluded.raw_text,
                 card_json=excluded.card_json, field_status_json=excluded.field_status_json,
                 score=excluded.score, level=excluded.level,
                 score_history_json=excluded.score_history_json,
                 published_at=excluded.published_at""",
            (
                str(task["id"]), str(task.get("status", "draft")), str(task.get("topic", "")),
                str(task.get("raw_text", "")), _json(card, "{}"),
                _json(task.get("field_status"), "{}"), int(task.get("score", 0)),
                str(task.get("level", "черновик")), _json(task.get("score_history"), "[]"),
                str(task["created_at"]), task.get("published_at"),
            ),
        )
    return task


def _task_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "status": row["status"],
        "topic": row["topic"],
        "raw_text": row["raw_text"],
        "card": json.loads(row["card_json"]),
        "field_status": json.loads(row["field_status_json"]),
        "score": row["score"],
        "level": row["level"],
        "score_history": json.loads(row["score_history_json"]),
        "created_at": row["created_at"],
        "published_at": row["published_at"],
    }


def get_task(task_id: str, path: str | os.PathLike[str] | None = None) -> dict[str, Any] | None:
    init_db(path)
    with _connect(path) as connection:
        row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return _task_from_row(row) if row else None


def list_tasks(
    *,
    status: str | None = None,
    path: str | os.PathLike[str] | None = None,
) -> list[dict[str, Any]]:
    """List tasks; published tasks are sorted by score, then publication date/id."""
    init_db(path)
    query = "SELECT * FROM tasks"
    params: tuple[Any, ...] = ()
    if status:
        query += " WHERE status = ?"
        params = (status,)
    query += " ORDER BY CASE WHEN status='published' THEN 0 ELSE 1 END, score DESC, published_at, id"
    with _connect(path) as connection:
        rows = connection.execute(query, params).fetchall()
    return [_task_from_row(row) for row in rows]


def save_proposal(
    proposal: dict[str, Any], path: str | os.PathLike[str] | None = None
) -> dict[str, Any]:
    required = ("id", "task_id", "created_at")
    missing = [field for field in required if not proposal.get(field)]
    if missing:
        raise ValueError(f"proposal missing required fields: {', '.join(missing)}")
    with _connect(path) as connection:
        connection.execute(
            """INSERT INTO proposals
               (id,task_id,team_name,idea,plan,timeline,link,status,created_at)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 team_name=excluded.team_name, idea=excluded.idea, plan=excluded.plan,
                 timeline=excluded.timeline, link=excluded.link, status=excluded.status""",
            tuple(str(proposal.get(key, default)) for key, default in (
                ("id", ""), ("task_id", ""), ("team_name", ""), ("idea", ""),
                ("plan", ""), ("timeline", ""), ("link", ""), ("status", "new"),
                ("created_at", ""),
            )),
        )
    return proposal


def list_proposals(
    task_id: str | None = None,
    path: str | os.PathLike[str] | None = None,
) -> list[dict[str, Any]]:
    init_db(path)
    query = "SELECT * FROM proposals"
    params: tuple[Any, ...] = ()
    if task_id is not None:
        query += " WHERE task_id = ?"
        params = (task_id,)
    query += " ORDER BY created_at, id"
    with _connect(path) as connection:
        rows = connection.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def set_proposal_status(
    proposal_id: str,
    status: str,
    path: str | os.PathLike[str] | None = None,
) -> None:
    """Apply only an explicit business decision; there is no auto-selection path."""
    if status not in {"new", "selected", "rejected"}:
        raise ValueError("status must be 'new', 'selected', or 'rejected'")
    init_db(path)
    with _connect(path) as connection:
        cursor = connection.execute(
            "UPDATE proposals SET status = ? WHERE id = ?", (status, proposal_id)
        )
        if cursor.rowcount == 0:
            raise KeyError(f"proposal not found: {proposal_id}")
