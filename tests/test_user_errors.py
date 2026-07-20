from komuzik.user_errors import (
    MSG_DOWNLOAD_UNAVAILABLE,
    format_download_error,
    is_access_restricted_error,
)

TIKTOK_ACCESS = (
    "ERROR: [TikTok] 7663986721033342239: This post may not be comfortable "
    "for some audiences. Log in for access. Use --cookies-from-browser or "
    "--cookies for the authentication."
)


def test_tiktok_login_access_detected():
    assert is_access_restricted_error(TIKTOK_ACCESS)
    assert format_download_error(TIKTOK_ACCESS) == MSG_DOWNLOAD_UNAVAILABLE


def test_youtube_http_403_detected():
    err = "ERROR: [youtube] abc: Unable to download webpage: HTTP Error 403: Forbidden"
    assert is_access_restricted_error(err)
    assert format_download_error(err, context="Префикс:") == MSG_DOWNLOAD_UNAVAILABLE


def test_youtube_http_401_detected():
    err = "ERROR: Unable to download API page: HTTP Error 401: Unauthorized"
    assert is_access_restricted_error(err)


def test_unrelated_error_kept():
    err = "No media file found in download directory"
    assert not is_access_restricted_error(err)
    assert format_download_error(err, context="Префикс:") == f"Префикс:\n{err}"


def test_does_not_match_random_numbers():
    assert not is_access_restricted_error("timeout after 4030 ms")
    assert not is_access_restricted_error("downloaded 401 MB")
