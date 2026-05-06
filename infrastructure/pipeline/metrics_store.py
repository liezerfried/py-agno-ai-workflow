"""
Persists per-run pipeline metrics to a pipeline_runs table in SQLite.
One row per pipeline run. Read back by the Chainlit history view.
"""
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

_DB_PATH = Path("tmp/traces.db")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id      TEXT PRIMARY KEY,
    timestamp   TEXT NOT NULL,
    filename    TEXT NOT NULL,
    total_rows  INTEGER NOT NULL,
    corrected   INTEGER NOT NULL,
    review_queue INTEGER NOT NULL,
    hallucinations INTEGER NOT NULL,
    precision   REAL
)
"""


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute(_CREATE_TABLE)
    conn.commit()
    return conn


def record_run(
    filename: str,
    total_rows: int,
    corrected: int,
    review_queue: int,
    hallucinations: int,
    precision: float | None,
) -> str:
    run_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO pipeline_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, timestamp, filename, total_rows, corrected, review_queue, hallucinations, precision),
        )
    return run_id


def get_recent_runs(limit: int = 20) -> list[dict]:
    """Return the last `limit` runs, newest first. Returns [] if the table does not exist yet."""
    try:
        with _connect() as conn:
            cursor = conn.execute(
                "SELECT run_id, timestamp, filename, total_rows, corrected, "
                "review_queue, hallucinations, precision "
                "FROM pipeline_runs ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
            columns = [d[0] for d in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
    except sqlite3.OperationalError:
        return []
