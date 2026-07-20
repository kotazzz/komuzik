import tempfile
from pathlib import Path

from komuzik.database import Database
from komuzik.repository import (
    StatsRepository,
    format_download_history_line,
    format_user_label,
)


def _repo() -> tuple[Database, StatsRepository]:
    tmp = tempfile.mkdtemp()
    db = Database(str(Path(tmp) / "t.db"))
    db.connect()
    return db, StatsRepository(db)


def test_list_users_empty():
    db, repo = _repo()
    try:
        assert repo.list_users() == []
        assert repo.count_users() == 0
        assert repo.count_users(kind="known") == 0
        assert repo.count_users(kind="anonymous") == 0
        assert repo.list_user_downloads(1) == []
        assert repo.count_user_downloads(1) == 0
    finally:
        db.close()


def test_list_users_splits_known_and_anonymous():
    db, repo = _repo()
    try:
        repo.track_user(1, "alice", display_name="Alice")
        repo.track_user(2, "bob", display_name=None)
        repo.track_user(3, None, display_name=None)
        repo.track_user(4, "", display_name="  ")

        assert repo.count_users() == 4
        assert repo.count_users(kind="known") == 2
        assert repo.count_users(kind="anonymous") == 2

        known_ids = {u["id"] for u in repo.list_users(kind="known", limit=10)}
        anon_ids = {u["id"] for u in repo.list_users(kind="anonymous", limit=10)}
        assert known_ids == {1, 2}
        assert anon_ids == {3, 4}
    finally:
        db.close()


def test_migration_adds_url_title_display_name_columns():
    db, repo = _repo()
    try:
        stats_cols = {
            row[1]
            for row in db.fetchall("PRAGMA table_info(statistics)")
        }
        users_cols = {
            row[1]
            for row in db.fetchall("PRAGMA table_info(users)")
        }
        assert "url" in stats_cols
        assert "title" in stats_cols
        assert "display_name" in users_cols
        assert repo.count_users() == 0
    finally:
        db.close()


def test_track_download_with_url_and_title():
    db, repo = _repo()
    try:
        uid = 42
        repo.track_user(uid, "alice", display_name="Alice A")
        repo.track_video_download(
            uid,
            "720p",
            username="alice",
            url="https://youtube.com/watch?v=abc",
            title="My Video",
        )

        users = repo.list_users()
        assert len(users) == 1
        assert users[0]["id"] == uid
        assert users[0]["username"] == "alice"
        assert users[0]["display_name"] == "Alice A"
        assert users[0]["last_seen"] is not None

        downloads = repo.list_user_downloads(uid)
        assert len(downloads) == 1
        assert downloads[0]["event_type"] == "video_download"
        assert downloads[0]["url"] == "https://youtube.com/watch?v=abc"
        assert downloads[0]["title"] == "My Video"
        assert downloads[0]["video_format"] == "720p"
        assert repo.count_user_downloads(uid) == 1
    finally:
        db.close()


def test_track_user_updates_display_name():
    db, repo = _repo()
    try:
        uid = 7
        repo.track_user(uid, "bob")
        repo.track_user(uid, "bob", display_name="Bob B")

        users = repo.list_users()
        assert users[0]["display_name"] == "Bob B"
    finally:
        db.close()


def test_list_users_pagination_and_download_types():
    db, repo = _repo()
    try:
        repo.track_user(1, "u1")
        repo.track_user(2, "u2")
        repo.track_user(3, "u3")

        repo.track_video_download(1, "720p", username="u1")
        repo.track_audio_download(1, "high", username="u1", url="https://yt/a", title="Song")
        repo.track_tiktok_download(1, username="u1")
        repo.track_pinterest_download(1, username="u1")
        repo.track_search(1, username="u1")

        assert repo.count_users() == 3
        assert repo.count_user_downloads(1) == 4
        assert len(repo.list_user_downloads(1, offset=0, limit=2)) == 2

        page = repo.list_users(offset=1, limit=1)
        assert len(page) == 1
    finally:
        db.close()


def test_format_download_history_line_with_link():
    row = {
        "event_type": "video_download",
        "platform": "youtube",
        "video_format": "720p",
        "url": "https://youtube.com/watch?v=abc",
        "title": "My [Video] (clip)",
        "success": True,
        "timestamp": "2026-07-20 13:10:00",
    }
    line = format_download_history_line(row)
    assert line.startswith("• [My Video clip]")
    assert "(https://youtube.com/watch?v=abc)" in line
    assert "youtube · video 720p" in line


def test_format_download_history_line_without_link():
    row = {
        "event_type": "audio_download",
        "platform": "youtube",
        "video_format": "high",
        "url": None,
        "title": None,
        "success": True,
        "timestamp": "2026-07-20 13:10:00",
    }
    line = format_download_history_line(row)
    assert line.startswith("• youtube · audio high")


def test_format_download_history_line_failed():
    row = {
        "event_type": "video_download",
        "platform": "youtube",
        "video_format": "720p",
        "url": "https://youtube.com/watch?v=abc",
        "title": "Fail",
        "success": False,
        "timestamp": "2026-07-20 13:10:00",
    }
    line = format_download_history_line(row)
    assert line.startswith("✗ • [Fail]")


def test_format_user_label():
    assert format_user_label({"id": 1, "display_name": "Alice A", "username": "alice"}) == (
        "Alice A (@alice)"
    )
    assert format_user_label({"id": 2, "username": "bob"}) == "@bob"
    assert format_user_label({"id": 3}) == "аноним"
    assert format_user_label({"id": 4, "display_name": "Only Name"}) == "Only Name"
