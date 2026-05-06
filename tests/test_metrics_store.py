"""
Unit tests for infrastructure/pipeline/metrics_store.py.

All tests use a tmp_path-scoped DB so they never touch tmp/traces.db.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from infrastructure.pipeline import metrics_store


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch):
    """Redirect the module's DB path to a temp file for each test."""
    monkeypatch.setattr(metrics_store, "_DB_PATH", tmp_path / "test_traces.db")


class TestRecordRun:
    def test_returns_run_id(self):
        run_id = metrics_store.record_run(
            filename="test.xlsx",
            total_rows=10,
            corrected=8,
            review_queue=1,
            hallucinations=1,
            precision=0.889,
        )
        assert isinstance(run_id, str)
        assert len(run_id) == 36  # UUID4 format

    def test_run_is_readable_back(self):
        metrics_store.record_run(
            filename="file.xlsx",
            total_rows=5,
            corrected=4,
            review_queue=1,
            hallucinations=0,
            precision=1.0,
        )
        runs = metrics_store.get_recent_runs()
        assert len(runs) == 1
        assert runs[0]["filename"] == "file.xlsx"
        assert runs[0]["total_rows"] == 5
        assert runs[0]["corrected"] == 4
        assert runs[0]["review_queue"] == 1
        assert runs[0]["hallucinations"] == 0
        assert runs[0]["precision"] == pytest.approx(1.0)

    def test_precision_none_stored_as_null(self):
        metrics_store.record_run(
            filename="empty.xlsx",
            total_rows=2,
            corrected=0,
            review_queue=0,
            hallucinations=0,
            precision=None,
        )
        runs = metrics_store.get_recent_runs()
        assert runs[0]["precision"] is None


class TestGetRecentRuns:
    def test_returns_newest_first(self):
        metrics_store.record_run("a.xlsx", 1, 1, 0, 0, 1.0)
        metrics_store.record_run("b.xlsx", 1, 1, 0, 0, 1.0)
        runs = metrics_store.get_recent_runs()
        assert runs[0]["filename"] == "b.xlsx"
        assert runs[1]["filename"] == "a.xlsx"

    def test_limit_is_respected(self):
        for i in range(5):
            metrics_store.record_run(f"f{i}.xlsx", 1, 1, 0, 0, 1.0)
        runs = metrics_store.get_recent_runs(limit=3)
        assert len(runs) == 3

    def test_empty_table_returns_empty_list(self):
        runs = metrics_store.get_recent_runs()
        assert runs == []

    def test_each_row_has_all_columns(self):
        metrics_store.record_run("x.xlsx", 10, 8, 1, 1, 0.889)
        row = metrics_store.get_recent_runs()[0]
        expected_keys = {"run_id", "timestamp", "filename", "total_rows",
                         "corrected", "review_queue", "hallucinations", "precision"}
        assert set(row.keys()) == expected_keys
