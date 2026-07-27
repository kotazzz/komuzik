import tempfile
from pathlib import Path

from komuzik.database import Database
from komuzik.download_limiter import DownloadLimiter
from komuzik.repository import StatsRepository


def test_can_download_respects_db_concurrent():
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(str(Path(tmp) / "t.db"))
        db.connect()
        repo = StatsRepository(db)
        repo.set_max_concurrent(1)

        limiter = DownloadLimiter(stats_repo=repo)
        user_id = 123

        assert limiter.can_download(user_id)
        limiter._active_downloads[user_id] = {"dl-1": limiter._timer()}
        assert not limiter.can_download(user_id)

        db.close()


def test_get_max_per_user_without_repo_uses_yaml():
    limiter = DownloadLimiter()
    assert limiter.get_max_per_user() == limiter.yaml_concurrent
    assert limiter.get_max_per_user() == limiter.MAX_DOWNLOADS_PER_USER
