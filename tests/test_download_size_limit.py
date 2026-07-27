"""Pre-download size checks must see merged format sizes and abort early."""

import pytest
from yt_dlp.utils import DownloadError

from komuzik.downloaders import (
    DownloadTooLargeError,
    _get_expected_size,
    _is_max_filesize_error,
    _reraise_size_limit,
    _size_limit_opts,
)
from komuzik.user_errors import format_download_error


def test_root_filesize_still_works():
    assert _get_expected_size({"filesize": 1234}) == 1234
    assert _get_expected_size({"filesize_approx": 999}) == 999


def test_sums_requested_formats_when_root_size_missing():
    """YouTube video+audio streams only expose size on requested_formats."""
    info = {
        "requested_formats": [
            {"filesize": 800_000_000},
            {"filesize_approx": 50_000_000},
        ]
    }
    assert _get_expected_size(info) == 850_000_000


def test_requested_formats_prefer_exact_over_approx_per_stream():
    info = {
        "requested_formats": [
            {"filesize": 100, "filesize_approx": 999},
            {"filesize_approx": 20},
        ]
    }
    assert _get_expected_size(info) == 120


def test_missing_size_returns_zero():
    assert _get_expected_size({}) == 0
    assert _get_expected_size({"requested_formats": [{"vcodec": "avc1"}]}) == 0


def test_size_limit_opts_set_max_filesize():
    opts = _size_limit_opts()
    assert "max_filesize" in opts
    assert opts["max_filesize"] > 0


def test_ydlp_max_filesize_message_is_detected():
    assert _is_max_filesize_error(DownloadError("File is larger than max-filesize"))
    assert _is_max_filesize_error(DownloadError("Aborting: larger than max filesize"))
    assert not _is_max_filesize_error(DownloadError("Unable to extract webpage"))


def test_reraise_translates_to_download_too_large():
    with pytest.raises(DownloadTooLargeError):
        _reraise_size_limit(DownloadError("File is larger than max-filesize"), "YouTube video")


def test_reraise_passes_other_errors_through():
    with pytest.raises(DownloadError, match="Unable to extract"):
        _reraise_size_limit(DownloadError("Unable to extract"), "YouTube video")


def test_user_message_for_too_large():
    text = format_download_error(DownloadTooLargeError("YouTube video exceeds 2 GB"))
    assert "слишком большой" in text
    assert "2 GB" not in text  # no raw internals
