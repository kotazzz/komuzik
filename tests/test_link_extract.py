"""Ordered multi-URL extraction from free-form chat text."""

from komuzik.link_extract import ParsedLink, extract_media_urls


def test_extract_space_comma_newline():
    text = (
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ "
        "https://www.tiktok.com/@u/video/1,\n"
        "https://x.com/a/status/2"
    )
    links = extract_media_urls(text)
    assert [l.platform for l in links] == ["youtube", "tiktok", "twitter"]
    assert links[0].url.startswith("https://")
    assert "dQw4w9WgXcQ" in links[0].url


def test_extract_preserves_order_and_dedupes():
    text = (
        "https://vt.tiktok.com/abc "
        "https://www.youtube.com/watch?v=abcdefghijk "
        "https://vt.tiktok.com/abc"
    )
    links = extract_media_urls(text)
    assert len(links) == 2
    assert links[0].platform == "tiktok"
    assert links[1].platform == "youtube"


def test_extract_skips_native_playlist_page():
    text = (
        "https://www.youtube.com/playlist?list=PLxxxxxxxxxxxxxxxxxxxxxx "
        "https://www.youtube.com/watch?v=abcdefghijk"
    )
    links = extract_media_urls(text)
    assert len(links) == 1
    assert links[0].platform == "youtube"
    assert "watch" in links[0].url


def test_extract_strips_trailing_punctuation():
    links = extract_media_urls("см. https://www.youtube.com/watch?v=abcdefghijk.")
    assert len(links) == 1
    assert not links[0].url.endswith(".")


def test_extract_empty():
    assert extract_media_urls("") == []
    assert extract_media_urls("просто текст без ссылок") == []


def test_parsed_link_is_frozen():
    link = ParsedLink(url="https://example.com", platform="tiktok")
    assert link.platform == "tiktok"
