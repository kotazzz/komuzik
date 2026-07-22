from komuzik.inline_query import parse_inline_query


def test_plain_text_is_not_url_job():
    assert parse_inline_query("never gonna give you up") is None


def test_url_still_parses_for_search_result():
    job = parse_inline_query(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        default_quality="480p",
    )
    assert job is not None
    assert job.platform == "youtube"
    assert job.mode == "video"
    assert job.quality == "480p"


def test_hls_host_url_parses_silently():
    job = parse_inline_query("https://murrtube.net/v/BS0W")
    assert job is not None
    assert job.platform == "hls_host"
    assert job.mode == "video"
    assert job.quality == "best"
    assert job.description == "Видео"
    assert "murr" not in job.description.lower()


def test_hls_host_url_without_scheme():
    job = parse_inline_query("murrtube.net/v/BS0W")
    assert job is not None
    assert job.platform == "hls_host"
    assert job.url.startswith("https://")
