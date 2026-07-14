from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any


class InvalidTransition(RuntimeError):
    pass


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "awaiting_decision": {"ignored", "triaging", "closed"},
    "ignored": {"triaging", "awaiting_decision", "closed"},
    "triaging": {"waiting_approval", "blocked", "closed"},
    "waiting_approval": {"triaging", "claimed", "blocked", "closed"},
    "claimed": {"coding", "blocked"},
    "coding": {"validating", "blocked"},
    "validating": {"publishing", "blocked"},
    "publishing": {"pr_open", "blocked"},
    "pr_open": {"merged", "blocked", "closed"},
    "blocked": {"triaging", "claimed", "closed"},
    "merged": set(),
    "closed": {"awaiting_decision", "merged"},
}
SNAPSHOT_STATES = frozenset(ALLOWED_TRANSITIONS)


class Store:
    def __init__(self, database_path: str | Path):
        self.database_path = str(database_path)
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("Store is not initialized")
        return self._connection

    def initialize(self) -> None:
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS deliveries (
                delivery_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                received_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS issues (
                issue_number INTEGER PRIMARY KEY,
                revision TEXT NOT NULL,
                title TEXT NOT NULL,
                issue_url TEXT NOT NULL,
                author TEXT NOT NULL,
                github_state TEXT NOT NULL,
                bot_state TEXT NOT NULL,
                triage_json TEXT,
                active_run_id TEXT,
                workflow_url TEXT,
                pr_number INTEGER,
                pr_url TEXT,
                updated_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_number INTEGER NOT NULL,
                run_id TEXT,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(issue_number) REFERENCES issues(issue_number)
            );
            CREATE TABLE IF NOT EXISTS notifications (
                run_id TEXT NOT NULL,
                notification_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending', 'sending', 'sent', 'dead')),
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at INTEGER,
                lease_until INTEGER,
                sent_at INTEGER,
                last_error TEXT,
                PRIMARY KEY(run_id, notification_type)
            );
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                issue_number INTEGER NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('triage', 'fix')),
                issue_revision TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'succeeded', 'failed')),
                result_json TEXT,
                error TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                started_at INTEGER,
                finished_at INTEGER,
                FOREIGN KEY(issue_number) REFERENCES issues(issue_number)
            );
            """
        )
        now = int(time.time())
        self._connection.execute(
            """
            UPDATE runs
            SET status = 'queued', started_at = NULL, updated_at = ?
            WHERE status = 'running'
            """,
            (now,),
        )
        self._connection.commit()

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def record_delivery(self, delivery_id: str, event_type: str) -> bool:
        with self._lock, self.connection:
            try:
                self.connection.execute(
                    "INSERT INTO deliveries(delivery_id, event_type, received_at) VALUES (?, ?, ?)",
                    (delivery_id, event_type, int(time.time())),
                )
            except sqlite3.IntegrityError:
                return False
        return True

    def upsert_issue(
        self,
        issue_number: int,
        revision: str,
        title: str,
        issue_url: str,
        author: str,
        github_state: str,
    ) -> None:
        now = int(time.time())
        with self._lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO issues(
                    issue_number, revision, title, issue_url, author,
                    github_state, bot_state, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'awaiting_decision', ?)
                ON CONFLICT(issue_number) DO UPDATE SET
                    revision=excluded.revision,
                    title=excluded.title,
                    issue_url=excluded.issue_url,
                    author=excluded.author,
                    github_state=excluded.github_state,
                    updated_at=excluded.updated_at
                """,
                (issue_number, revision, title, issue_url, author, github_state, now),
            )

    def get_issue(self, issue_number: int) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM issues WHERE issue_number = ?", (issue_number,)
        ).fetchone()
        return dict(row) if row else None

    def list_issues(self, state: str | None = None) -> list[dict[str, Any]]:
        if state:
            rows = self.connection.execute(
                "SELECT * FROM issues WHERE bot_state = ? ORDER BY updated_at DESC, issue_number DESC",
                (state,),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM issues ORDER BY updated_at DESC, issue_number DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def apply_snapshot(self, issues: list[dict[str, Any]]) -> None:
        now = int(time.time())
        with self._lock, self.connection:
            for issue in issues:
                bot_state = str(issue["bot_state"])
                if bot_state not in SNAPSHOT_STATES:
                    raise ValueError(f"Unknown bot state: {bot_state}")
                self.connection.execute(
                    """
                    INSERT INTO issues(
                        issue_number, revision, title, issue_url, author,
                        github_state, bot_state, pr_number, pr_url, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(issue_number) DO UPDATE SET
                        revision=excluded.revision,
                        title=excluded.title,
                        issue_url=excluded.issue_url,
                        author=excluded.author,
                        github_state=excluded.github_state,
                        bot_state=excluded.bot_state,
                        pr_number=excluded.pr_number,
                        pr_url=excluded.pr_url,
                        updated_at=excluded.updated_at
                    """,
                    (
                        int(issue["issue_number"]),
                        str(issue["revision"]),
                        str(issue["title"]),
                        str(issue["issue_url"]),
                        str(issue["author"]),
                        str(issue["github_state"]),
                        bot_state,
                        issue.get("pr_number"),
                        issue.get("pr_url"),
                        now,
                    ),
                )

    def transition_issue(
        self,
        issue_number: int,
        new_state: str,
        *,
        event_type: str,
        payload: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> None:
        now = int(time.time())
        with self._lock, self.connection:
            row = self.connection.execute(
                "SELECT bot_state FROM issues WHERE issue_number = ?", (issue_number,)
            ).fetchone()
            if row is None:
                raise KeyError(issue_number)
            current = str(row["bot_state"])
            if new_state not in ALLOWED_TRANSITIONS.get(current, set()):
                raise InvalidTransition(f"{current} -> {new_state}")
            self.connection.execute(
                "UPDATE issues SET bot_state = ?, updated_at = ? WHERE issue_number = ?",
                (new_state, now, issue_number),
            )
            self.connection.execute(
                """
                INSERT INTO events(issue_number, run_id, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (issue_number, run_id, event_type, json.dumps(payload or {}), now),
            )

    def enqueue_run(self, issue_number: int, kind: str, target_state: str) -> str:
        if kind not in {"triage", "fix"}:
            raise ValueError(f"Unknown run kind: {kind}")
        run_id = str(uuid.uuid4())
        now = int(time.time())
        with self._lock:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                issue = self.connection.execute(
                    """
                    SELECT revision, bot_state, active_run_id
                    FROM issues WHERE issue_number = ?
                    """,
                    (issue_number,),
                ).fetchone()
                if issue is None:
                    raise KeyError(issue_number)
                if issue["active_run_id"] is not None:
                    raise RuntimeError(f"Issue {issue_number} already has an active run")
                current_state = str(issue["bot_state"])
                if target_state not in ALLOWED_TRANSITIONS.get(current_state, set()):
                    raise InvalidTransition(f"{current_state} -> {target_state}")
                self.connection.execute(
                    """
                    INSERT INTO runs(
                        run_id, issue_number, kind, issue_revision, status,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'queued', ?, ?)
                    """,
                    (run_id, issue_number, kind, issue["revision"], now, now),
                )
                self.connection.execute(
                    """
                    UPDATE issues
                    SET bot_state = ?, active_run_id = ?, updated_at = ?
                    WHERE issue_number = ?
                    """,
                    (target_state, run_id, now, issue_number),
                )
                self.connection.execute(
                    """
                    INSERT INTO events(issue_number, run_id, event_type, payload_json, created_at)
                    VALUES (?, ?, 'run_queued', ?, ?)
                    """,
                    (issue_number, run_id, json.dumps({"kind": kind}), now),
                )
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
        return run_id

    def claim_run(self, now: int | None = None) -> dict[str, Any] | None:
        timestamp = int(time.time()) if now is None else now
        with self._lock:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                row = self.connection.execute(
                    """
                    SELECT * FROM runs
                    WHERE status = 'queued'
                    ORDER BY created_at, rowid
                    LIMIT 1
                    """
                ).fetchone()
                if row is None:
                    self.connection.commit()
                    return None
                self.connection.execute(
                    """
                    UPDATE runs
                    SET status = 'running', started_at = ?, updated_at = ?
                    WHERE run_id = ?
                    """,
                    (timestamp, timestamp, row["run_id"]),
                )
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
        return self.get_run(str(row["run_id"]))

    def finish_run(
        self,
        run_id: str,
        status: str,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        if status not in {"succeeded", "failed"}:
            raise ValueError(f"Invalid terminal run status: {status}")
        now = int(time.time())
        with self._lock:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                run = self.connection.execute(
                    "SELECT issue_number FROM runs WHERE run_id = ?", (run_id,)
                ).fetchone()
                if run is None:
                    raise KeyError(run_id)
                self.connection.execute(
                    """
                    UPDATE runs
                    SET status = ?, result_json = ?, error = ?,
                        finished_at = ?, updated_at = ?
                    WHERE run_id = ?
                    """,
                    (
                        status,
                        json.dumps(result, ensure_ascii=False) if result is not None else None,
                        error[-2000:] if error else None,
                        now,
                        now,
                        run_id,
                    ),
                )
                self.connection.execute(
                    """
                    UPDATE issues SET active_run_id = NULL, updated_at = ?
                    WHERE issue_number = ? AND active_run_id = ?
                    """,
                    (now, run["issue_number"], run_id),
                )
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        run = dict(row)
        run["result"] = json.loads(run["result_json"]) if run["result_json"] else None
        return run

    def update_issue_metadata(
        self,
        issue_number: int,
        *,
        triage: dict[str, Any] | None = None,
        workflow_url: str | None = None,
        pr_number: int | None = None,
        pr_url: str | None = None,
    ) -> None:
        fields: list[str] = []
        values: list[Any] = []
        if triage is not None:
            fields.append("triage_json = ?")
            values.append(json.dumps(triage, ensure_ascii=False))
        if workflow_url is not None:
            fields.append("workflow_url = ?")
            values.append(workflow_url)
        if pr_number is not None:
            fields.append("pr_number = ?")
            values.append(pr_number)
        if pr_url is not None:
            fields.append("pr_url = ?")
            values.append(pr_url)
        if not fields:
            return
        fields.append("updated_at = ?")
        values.append(int(time.time()))
        values.append(issue_number)
        with self._lock, self.connection:
            self.connection.execute(
                f"UPDATE issues SET {', '.join(fields)} WHERE issue_number = ?",
                values,
            )

    def enqueue_notification(
        self,
        run_id: str,
        notification_type: str,
        payload: dict[str, Any],
        *,
        now: int | None = None,
    ) -> bool:
        timestamp = int(time.time()) if now is None else now
        with self._lock, self.connection:
            cursor = self.connection.execute(
                """
                INSERT OR IGNORE INTO notifications(
                    run_id, notification_type, payload_json, status, next_attempt_at
                ) VALUES (?, ?, ?, 'pending', ?)
                """,
                (run_id, notification_type, json.dumps(payload, ensure_ascii=False), timestamp),
            )
        return cursor.rowcount == 1

    def claim_notifications(
        self,
        *,
        now: int,
        lease_seconds: int = 60,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        with self._lock:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                rows = self.connection.execute(
                    """
                    SELECT * FROM notifications
                    WHERE (status = 'pending' AND COALESCE(next_attempt_at, 0) <= ?)
                       OR (status = 'sending' AND COALESCE(lease_until, 0) <= ?)
                    ORDER BY COALESCE(next_attempt_at, 0), run_id
                    LIMIT ?
                    """,
                    (now, now, limit),
                ).fetchall()
                for row in rows:
                    self.connection.execute(
                        """
                        UPDATE notifications SET status = 'sending', lease_until = ?
                        WHERE run_id = ? AND notification_type = ?
                        """,
                        (now + lease_seconds, row["run_id"], row["notification_type"]),
                    )
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
        return [dict(row) for row in rows]

    def mark_notification_sent(self, run_id: str, notification_type: str, *, now: int) -> None:
        with self._lock, self.connection:
            self.connection.execute(
                """
                UPDATE notifications
                SET status = 'sent', sent_at = ?, lease_until = NULL, last_error = NULL
                WHERE run_id = ? AND notification_type = ?
                """,
                (now, run_id, notification_type),
            )

    def mark_notification_failed(
        self,
        run_id: str,
        notification_type: str,
        error: str,
        *,
        now: int,
    ) -> None:
        row = self.get_notification(run_id, notification_type)
        if row is None:
            raise KeyError((run_id, notification_type))
        attempts = int(row["attempts"]) + 1
        status = "dead" if attempts >= 24 else "pending"
        delays = (30, 120, 600)
        delay = delays[attempts - 1] if attempts <= len(delays) else 3600
        next_attempt = None if status == "dead" else now + delay
        with self._lock, self.connection:
            self.connection.execute(
                """
                UPDATE notifications
                SET status = ?, attempts = ?, next_attempt_at = ?, lease_until = NULL,
                    last_error = ?
                WHERE run_id = ? AND notification_type = ?
                """,
                (status, attempts, next_attempt, error[-2000:], run_id, notification_type),
            )

    def get_notification(self, run_id: str, notification_type: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            """
            SELECT * FROM notifications WHERE run_id = ? AND notification_type = ?
            """,
            (run_id, notification_type),
        ).fetchone()
        return dict(row) if row else None
