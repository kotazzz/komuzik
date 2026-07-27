"""Multi-link playlist buttons and mix_kind routing."""

from unittest.mock import MagicMock

from komuzik.handlers.playlist import PlaylistMixin
from komuzik.playlist import (
    MIX_MIXED,
    MIX_NON_YT_ONLY,
    MIX_YT_ONLY,
    PlaylistEntry,
    PlaylistSession,
)
from komuzik.repository import UserSettings


def _session(mix_kind: str, *, last_mode=None, last_quality=None) -> tuple:
    handlers = PlaylistMixin.__new__(PlaylistMixin)
    stats = MagicMock()
    settings = UserSettings(
        user_id=1,
        last_mode=last_mode,
        last_quality=last_quality,
        default_quality="720p",
    )
    stats.get_user_settings.return_value = settings
    handlers.stats = stats

    entries = [
        PlaylistEntry("a", "A", "https://youtu.be/abcdefghijk", platform="youtube"),
        PlaylistEntry("b", "B", "https://vt.tiktok.com/x", platform="tiktok"),
    ]
    if mix_kind == MIX_YT_ONLY:
        entries = entries[:1]
        entries[0].platform = "youtube"
    elif mix_kind == MIX_NON_YT_ONLY:
        entries = [
            PlaylistEntry("t1", "T1", "https://vt.tiktok.com/1", platform="tiktok"),
            PlaylistEntry("t2", "T2", "https://vt.tiktok.com/2", platform="tiktok"),
        ]
    session = PlaylistSession(
        user_id=1,
        playlist_url="multi",
        title="Links",
        is_music=False,
        entries=entries,
        source="multi_links",
        mix_kind=mix_kind,
        default_quality="720p",
    )
    return handlers, session


def _button_data(rows) -> list[str]:
    out = []
    for row in rows:
        for btn in row:
            data = getattr(btn, "data", None)
            if isinstance(data, bytes):
                data = data.decode()
            out.append(str(data))
    return out


def test_yt_only_buttons_have_video_audio_preview_no_hint():
    handlers, session = _session(MIX_YT_ONLY, last_mode="audio", last_quality="low")
    data = _button_data(handlers._playlist_buttons(session))
    assert "pl_video" in data
    assert "pl_audio" in data
    assert "pl_repeat" in data
    assert "pl_preview" in data
    assert "pl_hint" not in data
    assert "pl_download" not in data


def test_non_yt_buttons_download_and_preview():
    handlers, session = _session(MIX_NON_YT_ONLY)
    data = _button_data(handlers._playlist_buttons(session))
    assert "pl_download" in data
    assert "pl_preview" in data
    assert "pl_video" not in data
    assert "pl_hint" not in data


def test_mixed_buttons_download_and_preview():
    handlers, session = _session(MIX_MIXED)
    data = _button_data(handlers._playlist_buttons(session))
    assert "pl_download" in data
    assert "pl_preview" in data
    assert "pl_video" not in data


def test_message_handler_routes_multi_links():
    import asyncio
    from types import MethodType, SimpleNamespace
    from unittest.mock import AsyncMock

    from komuzik.handlers.downloads import DownloadsMixin

    called: list = []

    async def fake_multi(self, event, user_id, links):
        called.append((user_id, [link.platform for link in links]))

    handlers = DownloadsMixin.__new__(DownloadsMixin)
    handlers.stats = MagicMock()
    handlers.download_limiter = MagicMock()
    handlers.download_limiter.ADMIN_USER_IDS = set()
    handlers._track_user = MagicMock()
    handlers._get_user_info = MagicMock(return_value=(42, "u"))
    handlers.command_pattern = staticmethod(lambda command: rf"^/{command}(?:@\w+)?(?:\s|$)")
    handlers._reject_if_banned = AsyncMock(return_value=False)
    handlers._maybe_handle_admin_pending = AsyncMock(return_value=False)
    handlers._maybe_handle_report_reply = AsyncMock(return_value=False)
    handlers._maybe_handle_playlist_exclusion_reply = AsyncMock(return_value=False)
    handlers._start_multi_link_session = MethodType(fake_multi, handlers)

    text = (
        "https://www.youtube.com/watch?v=abcdefghijk "
        "https://vt.tiktok.com/ZMabcdef/"
    )
    event = SimpleNamespace(
        sender_id=42,
        is_group=False,
        message=SimpleNamespace(text=text, id=1),
    )

    asyncio.run(DownloadsMixin.message_handler(handlers, event))
    assert called
    assert called[0][0] == 42
    assert "youtube" in called[0][1]
    assert "tiktok" in called[0][1]


def test_playlist_i18n_keys_present():
    from komuzik.i18n import t

    assert "Читаю" in t("playlist.reading_links")
    assert "3" in t("playlist.multi_title", count=3)
    warning = t("playlist.preview.mixed_warning", quality="720p")
    assert "720p" in warning
    assert t("playlist.buttons.download")
    assert t("playlist.buttons.preview")
    assert t("playlist.buttons.repeat")
