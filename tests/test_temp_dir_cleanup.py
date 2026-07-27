"""temp_dir cleanup between retries and deterministic file selection."""

import os
from pathlib import Path

import pytest

from komuzik.downloaders import _clear_temp_dir, _find_downloaded_file


def test_clear_temp_dir_removes_files_and_subdirs(tmp_path: Path):
    (tmp_path / "a.part").write_bytes(b"x")
    nested = tmp_path / "sub"
    nested.mkdir()
    (nested / "b.mp4").write_bytes(b"y" * 10)

    _clear_temp_dir(str(tmp_path))

    assert list(tmp_path.iterdir()) == []
    assert tmp_path.is_dir()


def test_clear_temp_dir_tolerates_missing_dir(tmp_path: Path):
    _clear_temp_dir(str(tmp_path / "does-not-exist"))


def test_find_ignores_part_files_even_if_listed_first(tmp_path: Path):
    """Regression: os.listdir order is arbitrary; a leftover .part must not win."""
    (tmp_path / "video.mp4.part").write_bytes(b"partial" * 1000)
    (tmp_path / "video.mp4").write_bytes(b"complete" * 100)

    path = _find_downloaded_file(str(tmp_path))

    assert path.endswith("video.mp4")
    assert not path.endswith(".part")


def test_find_prefers_largest_complete_file(tmp_path: Path):
    (tmp_path / "small.mp4").write_bytes(b"a" * 10)
    (tmp_path / "large.mp4").write_bytes(b"b" * 1000)

    path = _find_downloaded_file(str(tmp_path))

    assert os.path.basename(path) == "large.mp4"


def test_find_skips_images_unless_allowed(tmp_path: Path):
    (tmp_path / "cover.jpg").write_bytes(b"img" * 100)
    (tmp_path / "audio.mp3").write_bytes(b"aud" * 50)

    path = _find_downloaded_file(str(tmp_path), expected_extension="mp3")
    assert path.endswith("audio.mp3")

    img_only = tmp_path / "img_only"
    img_only.mkdir()
    (img_only / "photo.png").write_bytes(b"p" * 20)

    with pytest.raises(Exception, match="No media file"):
        _find_downloaded_file(str(img_only), allow_images=False)

    path = _find_downloaded_file(str(img_only), allow_images=True)
    assert path.endswith("photo.png")


def test_find_rejects_empty_directory(tmp_path: Path):
    with pytest.raises(Exception, match="No files downloaded"):
        _find_downloaded_file(str(tmp_path))


def test_find_rejects_empty_file(tmp_path: Path):
    (tmp_path / "empty.mp4").write_bytes(b"")
    with pytest.raises(Exception, match="empty"):
        _find_downloaded_file(str(tmp_path))


def test_find_ignores_ytdl_and_temp_sidecars(tmp_path: Path):
    (tmp_path / "clip.mp4.ytdl").write_bytes(b"meta" * 100)
    (tmp_path / "clip.mp4.temp").write_bytes(b"tmp" * 100)
    (tmp_path / "clip.mp4").write_bytes(b"ok" * 10)

    path = _find_downloaded_file(str(tmp_path))
    assert os.path.basename(path) == "clip.mp4"


def test_retry_leftover_part_cannot_win_after_clear(tmp_path: Path):
    """Simulates the TikTok/HLS bug: failed attempt leaves .part, retry succeeds."""
    (tmp_path / "id.mp4.part").write_bytes(b"broken" * 5000)
    _clear_temp_dir(str(tmp_path))
    (tmp_path / "id.mp4").write_bytes(b"good" * 100)

    path = _find_downloaded_file(str(tmp_path))
    assert path.endswith("id.mp4")
    assert Path(path).stat().st_size == 400
