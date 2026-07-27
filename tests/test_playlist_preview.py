"""Playlist session mix_kind and preview formatting."""

from komuzik.playlist import (
    MIX_MIXED,
    MIX_NON_YT_ONLY,
    MIX_YT_ONLY,
    PlaylistEntry,
    PlaylistSession,
    classify_mix_kind,
    format_preview_page,
    platform_emoji,
)


def _entry(platform: str, i: int = 1) -> PlaylistEntry:
    return PlaylistEntry(
        video_id=f"id{i}",
        title=f"Title {i}",
        url=f"https://example.com/{i}",
        platform=platform,
    )


def test_classify_mix_kind():
    assert classify_mix_kind([_entry("youtube"), _entry("youtube", 2)]) == MIX_YT_ONLY
    assert classify_mix_kind([_entry("tiktok"), _entry("twitter", 2)]) == MIX_NON_YT_ONLY
    assert classify_mix_kind([_entry("youtube"), _entry("tiktok", 2)]) == MIX_MIXED


def test_platform_emoji():
    assert platform_emoji("youtube") == "▶️"
    assert platform_emoji("tiktok") == "🎵"


def test_format_preview_mixed_warning_and_emoji():
    session = PlaylistSession(
        user_id=1,
        playlist_url="multi",
        title="Ссылки (2)",
        is_music=False,
        entries=[_entry("youtube"), _entry("tiktok", 2)],
        source="multi_links",
        mix_kind=MIX_MIXED,
        default_quality="720p",
    )
    text = format_preview_page(session)
    assert "> " in text
    assert "720p" in text
    assert "▶️" in text
    assert "🎵" in text


def test_format_preview_yt_only_no_platform_emoji_for_native():
    session = PlaylistSession(
        user_id=1,
        playlist_url="https://youtube.com/playlist?list=x",
        title="PL",
        is_music=False,
        entries=[_entry("youtube")],
        source="youtube_playlist",
        mix_kind=MIX_YT_ONLY,
    )
    text = format_preview_page(session)
    assert "▶️" not in text
    assert "> " not in text
