import tempfile
from pathlib import Path

from komuzik.database import Database
from komuzik.handlers import format_ban_message
from komuzik.repository import StatsRepository


def test_format_ban_message():
    msg = format_ban_message("спам")
    assert msg == (
        "🚫 Вы заблокированы.\n"
        "Причина: спам\n"
        "Если ошибка — /report"
    )


def test_ban_get_and_is_banned():
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(str(Path(tmp) / "t.db"))
        db.connect()
        repo = StatsRepository(db)
        uid = 1001
        admin_id = 99

        assert repo.get_ban(uid) is None
        assert not repo.is_banned(uid)

        repo.ban_user(uid, "спам", banned_by=admin_id)
        assert repo.get_ban(uid) == "спам"
        assert repo.is_banned(uid)

        db.close()


def test_reban_updates_reason():
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(str(Path(tmp) / "t.db"))
        db.connect()
        repo = StatsRepository(db)
        uid = 2002

        repo.ban_user(uid, "старая причина", banned_by=1)
        repo.ban_user(uid, "новая причина", banned_by=2)
        assert repo.get_ban(uid) == "новая причина"
        assert repo.count_bans() == 1

        db.close()


def test_unban_returns_bool():
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(str(Path(tmp) / "t.db"))
        db.connect()
        repo = StatsRepository(db)
        uid = 3003

        assert repo.unban_user(uid) is False
        assert not repo.is_banned(uid)

        repo.ban_user(uid, "тест", banned_by=1)
        assert repo.unban_user(uid) is True
        assert repo.get_ban(uid) is None
        assert repo.unban_user(uid) is False

        db.close()


def test_count_bans():
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(str(Path(tmp) / "t.db"))
        db.connect()
        repo = StatsRepository(db)

        assert repo.count_bans() == 0

        repo.ban_user(1, "a", banned_by=99)
        repo.ban_user(2, "b", banned_by=99)
        assert repo.count_bans() == 2

        repo.unban_user(1)
        assert repo.count_bans() == 1

        db.close()
