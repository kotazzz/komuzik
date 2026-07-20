import tempfile
from pathlib import Path

from komuzik.database import Database
from komuzik.repository import StatsRepository


def test_storage_chat_id_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(str(Path(tmp) / "t.db"))
        db.connect()
        repo = StatsRepository(db)
        assert repo.get_storage_chat_id() is None
        repo.set_storage_chat_id(-100123)
        assert repo.get_storage_chat_id() == -100123
        repo.set_storage_chat_id(-100999)
        assert repo.get_storage_chat_id() == -100999
        repo.clear_storage_chat_id()
        assert repo.get_storage_chat_id() is None
        db.close()
