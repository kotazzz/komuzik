"""Twitter/X downloads must be counted separately from TikTok."""

import tempfile
from pathlib import Path

import pytest

from komuzik.database import Database
from komuzik.repository import (
    DOWNLOAD_EVENT_TYPES,
    VIDEO_LIKE_EVENT_TYPES,
    StatsRepository,
    format_download_history_line,
)


@pytest.fixture
def repo():
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(str(Path(tmp) / "t.db"))
        db.connect()
        yield StatsRepository(db)
        db.close()


def test_twitter_is_a_download_event_type():
    assert "twitter_download" in DOWNLOAD_EVENT_TYPES
    assert "twitter_download" in VIDEO_LIKE_EVENT_TYPES


def test_track_twitter_download_uses_own_platform(repo):
    repo.track_twitter_download(1, "u", url="https://x.com/a/status/1", title="Tweet")

    row = repo.db.fetchone(
        "SELECT event_type, platform FROM statistics WHERE user_id = 1",
    )
    assert row["event_type"] == "twitter_download"
    assert row["platform"] == "twitter"


def test_twitter_does_not_inflate_tiktok_counter(repo):
    repo.track_tiktok_download(1, "u", url="https://tiktok.com/@a/video/1")
    repo.track_twitter_download(1, "u", url="https://x.com/a/status/1")
    repo.track_twitter_download(1, "u", url="https://twitter.com/a/status/2")

    stats = repo.get_statistics("all")
    assert stats["total_tiktoks"] == 1
    assert stats["total_twitter"] == 2
    # both still count as downloads and as video-like content
    assert stats["total_downloads"] == 3
    assert stats["by_content"]["video"] == 3


def test_twitter_appears_in_user_history(repo):
    repo.track_twitter_download(1, "u", url="https://x.com/a/status/1", title="Tweet")

    rows = repo.list_user_downloads(1)
    assert len(rows) == 1
    line = format_download_history_line(rows[0])
    assert "Твиттер" in line
    assert "ТикТок" not in line


def test_historical_twitter_rows_are_reclassified():
    """Old rows were written through the TikTok tracker; migration splits them out."""
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "t.db")

        db = Database(path)
        db.connect()
        legacy = [
            ("https://twitter.com/a/status/1", "tiktok"),
            ("https://x.com/b/status/2", "tiktok"),
            ("https://www.tiktok.com/@c/video/3", "tiktok"),
            (None, "tiktok"),
        ]
        for url, platform in legacy:
            db.execute(
                """INSERT INTO statistics (event_type, user_id, platform, url, success)
                   VALUES ('tiktok_download', 7, ?, ?, 1)""",
                (platform, url),
            )
        db.close()

        # reopening runs migrations
        db = Database(path)
        db.connect()
        repo = StatsRepository(db)
        stats = repo.get_statistics("all")

        assert stats["total_twitter"] == 2
        # the real TikTok row and the url-less row stay put
        assert stats["total_tiktoks"] == 2
        assert stats["total_downloads"] == 4

        migrated = db.fetchall(
            "SELECT platform FROM statistics WHERE event_type = 'twitter_download'"
        )
        assert {r["platform"] for r in migrated} == {"twitter"}
        db.close()


def test_reclassification_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "t.db")
        db = Database(path)
        db.connect()
        db.execute(
            """INSERT INTO statistics (event_type, user_id, platform, url, success)
               VALUES ('tiktok_download', 7, 'tiktok', 'https://x.com/a/status/1', 1)"""
        )
        db.close()

        for _ in range(3):
            db = Database(path)
            db.connect()
            stats = StatsRepository(db).get_statistics("all")
            db.close()
            assert stats["total_twitter"] == 1
            assert stats["total_downloads"] == 1


def test_tiktok_lookalike_urls_are_not_reclassified():
    """'%x.com%' would have swallowed unrelated hosts — the predicate is stricter."""
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "t.db")
        db = Database(path)
        db.connect()
        for url in ("https://vertx.com/watch/1", "https://tiktok.com/@x.com/video/2"):
            db.execute(
                """INSERT INTO statistics (event_type, user_id, platform, url, success)
                   VALUES ('tiktok_download', 7, 'tiktok', ?, 1)""",
                (url,),
            )
        db.close()

        db = Database(path)
        db.connect()
        stats = StatsRepository(db).get_statistics("all")
        db.close()

        assert stats["total_twitter"] == 0
        assert stats["total_tiktoks"] == 2
