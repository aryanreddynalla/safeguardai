"""SQLite persistence for approvals, simulated deliveries and audit events."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "agentshield.db"

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection

def init_db() -> None:
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                action TEXT NOT NULL,
                tool TEXT NOT NULL,
                destination TEXT,
                fields_json TEXT NOT NULL,
                decision TEXT NOT NULL,
                reason TEXT NOT NULL,
                approval_id TEXT,
                execution_status TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS approval_requests (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                recipient TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                status TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS simulated_deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                recipient TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                approval_id TEXT
            );
            """
        )

def log_event(
    *,
    action: str,
    tool: str,
    destination: str | None,
    fields: list[str],
    decision: str,
    reason: str,
    execution_status: str,
    approval_id: str | None = None,
) -> None:
    with connect() as db:
        db.execute(
            """INSERT INTO audit_events
            (created_at, action, tool, destination, fields_json, decision,
             reason, approval_id, execution_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                utc_now(), action, tool, destination,
                json.dumps(sorted(fields)), decision, reason,
                approval_id, execution_status,
            ),
        )

def create_approval(
    *, approval_id: str, expires_at: str, recipient: str,
    payload: dict[str, Any], payload_hash: str,
) -> None:
    with connect() as db:
        db.execute(
            """INSERT INTO approval_requests
            (id, created_at, expires_at, recipient, payload_json, payload_hash, status)
            VALUES (?, ?, ?, ?, ?, ?, 'PENDING')""",
            (approval_id, utc_now(), expires_at, recipient, json.dumps(payload, sort_keys=True), payload_hash),
        )

def get_approval(approval_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT * FROM approval_requests WHERE id = ?", (approval_id,)).fetchone()
        return dict(row) if row else None

def set_approval_status(approval_id: str, status: str) -> None:
    with connect() as db:
        db.execute("UPDATE approval_requests SET status = ? WHERE id = ?", (status, approval_id))

def record_delivery(recipient: str, payload: dict[str, Any], approval_id: str | None = None) -> int:
    with connect() as db:
        cursor = db.execute(
            """INSERT INTO simulated_deliveries (created_at, recipient, payload_json, approval_id)
            VALUES (?, ?, ?, ?)""",
            (utc_now(), recipient, json.dumps(payload, sort_keys=True), approval_id),
        )
        return int(cursor.lastrowid)

def overview() -> dict[str, Any]:
    with connect() as db:
        total = db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        blocked = db.execute("SELECT COUNT(*) FROM audit_events WHERE decision = 'BLOCK'").fetchone()[0]
        executed = db.execute("SELECT COUNT(*) FROM audit_events WHERE execution_status = 'EXECUTED'").fetchone()[0]
        pending = db.execute("SELECT COUNT(*) FROM approval_requests WHERE status = 'PENDING'").fetchone()[0]
        deliveries = db.execute("SELECT COUNT(*) FROM simulated_deliveries").fetchone()[0]
    return {
        "total_events": total,
        "blocked_actions": blocked,
        "executed_actions": executed,
        "pending_approvals": pending,
        "simulated_deliveries": deliveries,
    }

def list_events(limit: int = 30) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["fields"] = json.loads(item.pop("fields_json"))
        result.append(item)
    return result

def list_approvals() -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            "SELECT id, created_at, expires_at, recipient, payload_json, status FROM approval_requests ORDER BY created_at DESC LIMIT 30"
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json"))
        result.append(item)
    return result

def list_deliveries(limit: int = 10) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM simulated_deliveries ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json"))
        result.append(item)
    return result
