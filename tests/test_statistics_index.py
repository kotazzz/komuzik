"""Schema indexes used by hot statistics queries."""

from pathlib import Path
from tempfile import TemporaryDirectory

from komuzik.database import Database


def test_statistics_user_timestamp_index_exists():
    with TemporaryDirectory() as tmp:
        db = Database(str(Path(tmp) / "t.db"))
        db.connect()
        try:
            rows = db.fetchall(
                "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
                ("idx_statistics_user_timestamp",),
            )
            assert rows
            sql = db.fetchone(
                "SELECT sql FROM sqlite_master WHERE type='index' AND name=?",
                ("idx_statistics_user_timestamp",),
            )
            assert sql is not None
            assert "user_id" in sql["sql"]
            assert "timestamp" in sql["sql"]
        finally:
            db.close()


def test_statistics_user_timestamp_index_added_on_existing_db():
    """Re-opening an older DB still creates the composite index (IF NOT EXISTS)."""
    with TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "t.db")
        first = Database(path)
        first.connect()
        first.execute("DROP INDEX IF EXISTS idx_statistics_user_timestamp")
        first.close()

        second = Database(path)
        second.connect()
        try:
            rows = second.fetchall(
                "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
                ("idx_statistics_user_timestamp",),
            )
            assert rows
        finally:
            second.close()
