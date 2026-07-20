import re
import tempfile
from pathlib import Path

from komuzik.database import Database
from komuzik.repository import StatsRepository
from komuzik.timeutil import today_msk


def test_today_msk_format():
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", today_msk())


def test_remaining_quota_and_increment():
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(str(Path(tmp) / "t.db"))
        db.connect()
        repo = StatsRepository(db)
        uid = 42

        assert repo.remaining_playlist_quota(uid, is_admin=False) == 50

        repo.increment_playlist_usage(uid, amount=3)
        assert repo.get_playlist_usage(uid) == 3
        assert repo.remaining_playlist_quota(uid, is_admin=False) == 47

        repo.set_user_playlist_limit(uid, 10)
        assert repo.remaining_playlist_quota(uid, is_admin=False) == 7

        repo.clear_user_playlist_limit(uid)
        assert repo.remaining_playlist_quota(uid, is_admin=False) == 47

        assert repo.remaining_playlist_quota(uid, is_admin=True) is None

        db.close()
