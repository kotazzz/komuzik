"""Regression tests for the small-defects pack."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from komuzik.handlers import BotHandlers
from komuzik.repository import StatsRepository
from komuzik.search_preview import _fetch_image, _wrap_text
from komuzik.timeutil import MSK


def test_fetch_image_rejects_non_http_schemes():
    assert _fetch_image("file:///etc/passwd") is None
    assert _fetch_image("ftp://example.com/a.jpg") is None


def test_wrap_text_does_not_drop_overflow_word():
    draw = MagicMock()
    # Width of a string equals its character count — easy to reason about.
    draw.textbbox = lambda _xy, text, font=None: (0, 0, len(text), 10)

    lines = _wrap_text(draw, "one two three four", font=None, max_width=7, max_lines=2)
    # Without the fold-back fix, "three"/"four" could vanish entirely.
    joined = " ".join(lines)
    assert "three" in joined or "four" in joined
    assert joined.endswith("…") or "four" in joined


def test_date_filter_uses_msk_midnight(monkeypatch):
    class FakeDateTime:
        @classmethod
        def now(cls, tz=None):
            from datetime import datetime

            # 2026-07-27 02:30 MSK → previous calendar day still running in UTC
            return datetime(2026, 7, 27, 2, 30, tzinfo=MSK)

    monkeypatch.setattr("komuzik.repository.datetime", FakeDateTime)
    repo = StatsRepository.__new__(StatsRepository)
    clause = repo._get_date_filter("day")
    # Midnight MSK = 21:00 previous day UTC
    assert "2026-07-26 21:00:00" in clause
    assert "datetime('now'" not in clause


def test_unlimited_user_skips_playlist_quota():
    from komuzik.database import Database

    with tempfile.TemporaryDirectory() as tmp:
        db = Database(str(Path(tmp) / "t.db"))
        db.connect()
        repo = StatsRepository(db)
        assert (
            repo.remaining_playlist_quota(7, is_admin=False, is_unlimited=True) is None
        )
        assert repo.remaining_playlist_quota(7, is_admin=False, is_unlimited=False) == 50
        db.close()


def test_cleanup_removes_nested_gallery_dl_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    root = tmp_path / "tmpABC"
    nested = root / "gallery-dl" / "twitter"
    nested.mkdir(parents=True)
    media = nested / "pic.jpg"
    media.write_bytes(b"x")

    handlers = BotHandlers.__new__(BotHandlers)
    handlers._cleanup_download_file(str(media))
    assert not root.exists()


def test_get_max_concurrent_is_read_only():
    from komuzik.database import Database

    with tempfile.TemporaryDirectory() as tmp:
        db = Database(str(Path(tmp) / "t.db"))
        db.connect()
        repo = StatsRepository(db)
        assert repo.get_max_concurrent(default=3) == 3
        row = db.fetchone(
            "SELECT value FROM bot_config WHERE key = ?",
            ("max_concurrent_per_user",),
        )
        assert row is None  # must not seed on read
        repo.set_max_concurrent(5)
        assert repo.get_max_concurrent(default=3) == 5
        db.close()
