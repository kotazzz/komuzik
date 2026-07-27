"""Unit tests for handler mixins (FakeEvent style, no real Telegram)."""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from komuzik.config import MSG_PRIVACY
from komuzik.handlers import CALLBACK_URLS, BotHandlers, format_ban_message
from komuzik.handlers.common import ADMIN_USERS_KIND_ANON, ADMIN_USERS_KIND_KNOWN
from komuzik.repository import UserSettings


def _run(coro):
    return asyncio.run(coro)


class FakeMessageEvent:
    def __init__(self, *, sender_id: int = 42, is_group: bool = False):
        self.sender_id = sender_id
        self.sender = SimpleNamespace(username="tester")
        self.is_group = is_group
        self.responses: list[tuple[str, dict]] = []

    async def respond(self, text, **kwargs):
        self.responses.append((text, kwargs))


class FakeCallbackEvent:
    def __init__(
        self,
        data: str,
        *,
        sender_id: int = 42,
        is_private: bool = True,
    ):
        self.data = data.encode()
        self.sender_id = sender_id
        self.is_private = is_private
        self.answers: list[tuple[str | None, bool]] = []
        self.edits: list[tuple[str, dict]] = []
        self.responses: list[tuple[str, dict]] = []

    async def answer(self, text=None, *, alert=False):
        self.answers.append((text, alert))

    async def edit(self, text, **kwargs):
        self.edits.append((text, kwargs))

    async def respond(self, text, **kwargs):
        self.responses.append((text, kwargs))


def _button_data(rows) -> set[bytes]:
    out: set[bytes] = set()
    for row in rows:
        for btn in row:
            data = getattr(btn, "data", None)
            if data is not None:
                out.add(data)
    return out


def _make_handlers(*, banned_reason: str | None = None, admin_ids: set[int] | None = None):
    handlers = BotHandlers.__new__(BotHandlers)
    stats = MagicMock()
    stats.get_ban.return_value = banned_reason
    stats.get_user_settings.return_value = UserSettings(user_id=42)

    limiter = MagicMock()
    limiter.ADMIN_USER_IDS = admin_ids or set()
    handlers.stats = stats
    handlers.download_limiter = limiter
    return handlers, stats, limiter


def test_privacy_handler_rejects_banned_user_in_dm():
    handlers, stats, _ = _make_handlers(banned_reason="спам")
    event = FakeMessageEvent(sender_id=99)

    _run(handlers.privacy_handler(event))

    stats.get_ban.assert_called_once_with(99)
    assert len(event.responses) == 1
    assert event.responses[0][0] == format_ban_message("спам")
    assert MSG_PRIVACY not in event.responses[0][0]


def test_privacy_handler_sends_policy_when_not_banned():
    handlers, stats, _ = _make_handlers()
    event = FakeMessageEvent()

    _run(handlers.privacy_handler(event))

    stats.get_ban.assert_called_once_with(42)
    stats.track_user.assert_called_once()
    assert len(event.responses) == 1
    assert event.responses[0][0] == MSG_PRIVACY


def test_privacy_handler_silent_in_group_when_banned():
    handlers, _, _ = _make_handlers(banned_reason="спам")
    event = FakeMessageEvent(sender_id=99, is_group=True)

    _run(handlers.privacy_handler(event))

    assert event.responses == []


def test_callback_noop_answers_only():
    handlers, _, _ = _make_handlers()
    event = FakeCallbackEvent("noop")

    _run(handlers.callback_handler(event))

    assert event.answers == [(None, False)]
    assert event.edits == []


def test_callback_routes_help_prefix():
    handlers, _, _ = _make_handlers()
    routed: list[str] = []

    async def fake_help(event, data):
        routed.append(data)

    handlers._handle_help_callback = fake_help
    event = FakeCallbackEvent("help_toc")

    _run(handlers.callback_handler(event))

    assert routed == ["help_toc"]


def test_callback_routes_settings_prefix():
    handlers, _, _ = _make_handlers()
    routed: list[str] = []

    async def fake_settings(event, data):
        routed.append(data)

    handlers._handle_settings_callback = fake_settings
    event = FakeCallbackEvent("settings_q_720p")

    _run(handlers.callback_handler(event))

    assert routed == ["settings_q_720p"]


def test_callback_blocks_banned_user_before_routing():
    handlers, _, _ = _make_handlers(banned_reason="спам")

    async def fail_settings(_event, _data):
        raise AssertionError("settings handler must not run for banned user")

    handlers._handle_settings_callback = fail_settings
    event = FakeCallbackEvent("settings_q_720p", sender_id=99)

    _run(handlers.callback_handler(event))

    assert len(event.responses) == 1
    assert event.responses[0][0] == format_ban_message("спам")
    assert event.answers == [(None, False)]


def test_callback_report_cancel_clears_state():
    from komuzik.handlers.common import REPORT_STATES

    handlers, _, _ = _make_handlers()
    REPORT_STATES[42] = True
    event = FakeCallbackEvent("report_cancel")

    _run(handlers.callback_handler(event))

    assert 42 not in REPORT_STATES
    assert len(event.edits) == 1


def test_quality_callback_keeps_token_for_reuse():
    handlers, _, _ = _make_handlers()
    token = "deadbeef"
    url = "https://youtu.be/abcdefghijk"
    CALLBACK_URLS[token] = url

    downloaded: list[tuple[str, str]] = []

    async def fake_download(_event, got_url, quality):
        downloaded.append((got_url, quality))

    handlers._download_and_send_video = fake_download
    data = f"quality_720p_{token}"
    event = FakeCallbackEvent(data)

    _run(handlers._handle_quality_callback(event, data))

    assert token in CALLBACK_URLS
    assert CALLBACK_URLS[token] == url
    assert downloaded == [(url, "720p")]
    CALLBACK_URLS.pop(token, None)


def test_select_callback_consumes_token():
    handlers, _, _ = _make_handlers()
    token = "cafebabe"
    url = "https://youtu.be/abcdefghijk"
    CALLBACK_URLS[token] = url

    shown: list[str] = []

    async def fake_show(_event, got_url):
        shown.append(got_url)

    handlers._show_content_type_selection = fake_show
    data = f"select_{token}"
    event = FakeCallbackEvent(data)

    _run(handlers._handle_select_callback(event, data))

    assert token not in CALLBACK_URLS
    assert shown == [url]


def test_admin_history_back_button_known_user():
    handlers, stats, _ = _make_handlers()
    stats.get_user.return_value = {"id": 1, "username": "alice"}
    stats.count_user_downloads.return_value = 0

    _text, buttons = handlers._format_admin_history_page(1, 0)
    data = _button_data(buttons)

    assert f"admin_users_{ADMIN_USERS_KIND_KNOWN}_p_0".encode() in data
    assert f"admin_users_{ADMIN_USERS_KIND_ANON}_p_0".encode() not in data


def test_admin_history_back_button_anonymous_user():
    handlers, stats, _ = _make_handlers()
    stats.get_user.return_value = {"id": 3}
    stats.count_user_downloads.return_value = 0

    _text, buttons = handlers._format_admin_history_page(3, 0)
    data = _button_data(buttons)

    assert f"admin_users_{ADMIN_USERS_KIND_ANON}_p_0".encode() in data
    for payload in data:
        assert "аноним".encode() not in payload
        assert "известн".encode() not in payload


def test_admin_history_back_kind_from_display_name_only():
    handlers, stats, _ = _make_handlers()
    stats.get_user.return_value = {"id": 5, "display_name": "Only Name"}
    stats.count_user_downloads.return_value = 0

    _text, buttons = handlers._format_admin_history_page(5, 0)
    data = _button_data(buttons)

    assert f"admin_users_{ADMIN_USERS_KIND_KNOWN}_p_0".encode() in data
