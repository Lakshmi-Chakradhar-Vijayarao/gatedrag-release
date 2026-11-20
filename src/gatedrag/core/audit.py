"""Append-only audit log of every decision (who asked, what was retrieved, what shipped, why)."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Protocol


class AuditLog(Protocol):
    def record(self, event: dict) -> None: ...


class SQLiteAuditLog:
    """Local/default store. A Postgres implementation only needs the same `record` method."""

    def __init__(self, path: str = "audit.db"):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self._conn.execute("PRAGMA journal_mode=WAL")       # concurrent writers from several workers
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS audit (
                   request_id TEXT PRIMARY KEY, ts REAL, user TEXT, question TEXT, decision TEXT,
                   support REAL, regenerated INTEGER, citations TEXT, config TEXT,
                   latency_ms REAL, prompt_tokens INTEGER, completion_tokens INTEGER)"""
        )
        self._conn.commit()

    def record(self, event: dict) -> None:
        row = (
            event["request_id"], time.time(), event.get("user", ""), event["question"], event["decision"],
            event["support"], int(event["regenerated"]), json.dumps(event["citations"]), event["config"],
            event["latency_ms"], event["prompt_tokens"], event["completion_tokens"],
        )
        with self._lock:
            self._conn.execute("INSERT INTO audit VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", row)
            self._conn.commit()

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
