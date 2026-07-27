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
