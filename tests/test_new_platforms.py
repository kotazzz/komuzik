"""TikTok photo classification, Twitch/VK/Yandex URL routing, chat toggles."""

import tempfile
from pathlib import Path

from komuzik.database import Database
from komuzik.downloaders import (
    DownloadRejectedError,
    assess_twitch_info,
    classify_gallery_files,
    info_has_video,
    twitch_url_kind,
)
from komuzik.i18n import t
from komuzik.inline_query import parse_inline_query
from komuzik.link_extract import extract_media_urls
from komuzik.repository import StatsRepository
from komuzik.user_errors import format_download_error


def test_slideshow_metadata_is_not_a_video():
    assert not info_has_video({"ext": "mp3", "formats": [{"vcodec": "none", "ext": "mp3"}]})
    assert info_has_video({"ext": "mp4", "formats": [{"vcodec": "h264", "ext": "mp4"}]})


def test_gallery_files_keep_image_order_and_one_audio():
    images, audio = classify_gallery_files(
        [
            "/tmp/02.jpg",
            "/tmp/00.mp3",
            "/tmp/01.jpeg",
            "/tmp/notes.json",
            "/tmp/03.jpg.part",
        ]
    )
    assert images == ["/tmp/01.jpeg", "/tmp/02.jpg"]
    assert audio == "/tmp/00.mp3"


def test_twitch_url_kinds():
    assert twitch_url_kind("https://clips.twitch.tv/SomeSlug") == "clip"
    assert twitch_url_kind("https://www.twitch.tv/xqc/clip/SomeSlug") == "clip"
    assert twitch_url_kind("https://www.twitch.tv/videos/123?t=5m10s") == "vod"
    assert twitch_url_kind("https://www.twitch.tv/xqc") == "channel"
    assert twitch_url_kind("https://www.twitch.tv/xqc/clip/SomeSlug") != "channel"


def test_twitch_vod_limits():
    live = assess_twitch_info({"is_live": True, "duration": 10}, kind="clip", max_duration=1800)
    assert live == "live"
    short_clip = assess_twitch_info({"duration": 10}, kind="clip", max_duration=1800)
    assert short_clip is None
    long_vod = assess_twitch_info(
        {"duration": 1900, "live_status": "was_live"}, kind="vod", max_duration=1800
    )
    assert long_vod == "too_long"
    unknown = assess_twitch_info({"live_status": "was_live"}, kind="vod", max_duration=1800)
    assert unknown == "too_long"
    short_vod = assess_twitch_info(
        {"duration": 600, "live_status": "was_live"}, kind="vod", max_duration=1800
    )
    assert short_vod is None


def test_extract_new_platforms_and_skip_bare_channel():
    text = (
        "https://www.twitch.tv/videos/99?t=1m "
        "https://vk.com/video-1_2 "
        "https://music.yandex.ru/album/3/track/4 "
        "https://www.twitch.tv/shroud"
    )
    links = extract_media_urls(text)
    assert [link.platform for link in links] == ["twitch", "vk", "yandex"]
    assert "t=1m" in links[0].url


def test_inline_jobs_for_new_platforms():
    clip = parse_inline_query("https://clips.twitch.tv/Abc")
    assert clip is not None
    assert clip.platform == "twitch"
    live = parse_inline_query("https://www.twitch.tv/shroud")
    assert live is not None
    assert live.platform == "twitch"
    assert "эфир" in live.description
    vk = parse_inline_query("https://vk.com/clip-10_20")
    assert vk is not None
    assert vk.platform == "vk"
    track = parse_inline_query("https://music.yandex.ru/album/1/track/2")
    assert track is not None
    assert track.platform == "yandex"
    assert track.mode == "audio"
    album = parse_inline_query("https://music.yandex.ru/album/1")
    assert album is not None
    assert album.platform == "yandex"


def test_rejected_error_is_shown_as_is():
    err = DownloadRejectedError(t("errors.twitch_live"))
    assert format_download_error(err, context="префикс") == t("errors.twitch_live")


def test_chat_settings_roundtrip_new_platforms():
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(str(Path(tmp) / "t.db"))
        db.connect()
        repo = StatsRepository(db)
        settings = repo.get_chat_settings(5)
        assert settings.allow_twitch is True
        assert settings.allow_vk is True
        assert settings.allow_yandex is True
        saved = repo.toggle_chat_setting(5, "allow_twitch")
        assert saved.allow_twitch is False
        assert repo.get_chat_settings(5).allow_vk is True
        assert repo.get_chat_settings(5).allows_platform("yandex") is True
        assert repo.get_chat_settings(5).allows_platform("twitch") is False
        db.close()
