from unittest.mock import MagicMock

from komuzik.handlers import BotHandlers


def _make_handlers(*, is_admin: bool = False, unlimited: bool = False, active: int = 0):
    stats = MagicMock()
    stats.effective_playlist_limit.return_value = 50
    stats.get_playlist_usage.return_value = 12
    stats.get_user_playlist_limit.return_value = None
    stats.get_max_concurrent.return_value = 3

    limiter = MagicMock()
    limiter.ADMIN_USER_IDS = {1} if is_admin else set()
    limiter.UNLIMITED_USER_IDS = {2} if unlimited else set()
    limiter.get_active_count.return_value = active
    limiter.get_max_per_user.return_value = 3

    handlers = BotHandlers.__new__(BotHandlers)
    handlers.stats = stats
    handlers.download_limiter = limiter
    handlers._is_bot_admin = lambda uid: uid in limiter.ADMIN_USER_IDS
    return handlers, stats


def test_format_limits_regular_user():
    handlers, stats = _make_handlers(active=1)
    text = handlers._format_user_limits_message(42)
    assert "1/3" in text
    assert "12/50" in text
    assert "осталось 38" in text
    assert "общий" in text
    stats.effective_playlist_limit.assert_called_once_with(
        42, is_admin=False, is_unlimited=False
    )


def test_format_limits_personal_override():
    handlers, stats = _make_handlers()
    stats.get_user_playlist_limit.return_value = 10
    stats.effective_playlist_limit.return_value = 10
    stats.get_playlist_usage.return_value = 3
    text = handlers._format_user_limits_message(42)
    assert "3/10" in text
    assert "персональный" in text


def test_format_limits_admin_unlimited():
    handlers, stats = _make_handlers(is_admin=True, active=2)
    stats.effective_playlist_limit.return_value = None
    text = handlers._format_user_limits_message(1)
    assert "без лимита" in text
    assert "Плейлист / сутки (МСК): без лимита" in text
    stats.effective_playlist_limit.assert_called_once_with(
        1, is_admin=True, is_unlimited=True
    )
