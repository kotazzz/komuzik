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
