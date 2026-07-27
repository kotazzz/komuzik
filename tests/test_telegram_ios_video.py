"""Already-H.264 videos must not be remuxed a second time."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

from komuzik.downloaders import _ensure_telegram_ios_video, _is_h264_codec


def test_is_h264_codec_variants():
    assert _is_h264_codec("h264")
    assert _is_h264_codec("avc1.640028")
    assert _is_h264_codec("AVC")
    assert not _is_h264_codec("vp9")
    assert not _is_h264_codec("av01")
    assert not _is_h264_codec(None)


def test_h264_skips_ffmpeg_entirely(tmp_path: Path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake")

    probe = {"vcodec": "h264", "acodec": "aac", "width": 1280, "height": 720, "duration": 10}

    with (
        patch("komuzik.downloaders._probe_video_file", new=AsyncMock(return_value=probe)),
        patch("komuzik.downloaders.run_media", new=AsyncMock()) as run_media,
    ):
        path, meta = asyncio.run(_ensure_telegram_ios_video(str(video)))

    assert path == str(video)
    assert meta is probe
    run_media.assert_not_called()


def test_non_h264_reencodes(tmp_path: Path):
    video = tmp_path / "clip.webm"
    video.write_bytes(b"fake")
    out = tmp_path / "clip_tg.mp4"

    before = {"vcodec": "vp9", "width": 640, "height": 360, "duration": 5}
    after = {"vcodec": "h264", "width": 640, "height": 360, "duration": 5}
    probes = AsyncMock(side_effect=[before, after])

    async def fake_run_media(func, args):
        # Simulate ffmpeg writing the output file
        Path(args[-1]).write_bytes(b"reencoded")

    with (
        patch("komuzik.downloaders._probe_video_file", new=probes),
        patch("komuzik.downloaders.run_media", new=fake_run_media),
    ):
        path, meta = asyncio.run(_ensure_telegram_ios_video(str(video)))

    assert path == str(out)
    assert meta["vcodec"] == "h264"
    assert out.exists()
    assert not video.exists()
