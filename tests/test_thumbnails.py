from komuzik.downloaders import thumbnail_from_ydl_entry, youtube_thumbnail_url
from komuzik.inline_thumbs import input_web_thumb


def test_youtube_thumbnail_url():
    assert youtube_thumbnail_url("dQw4w9WgXcQ") == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
    assert youtube_thumbnail_url("bad") is None
    assert youtube_thumbnail_url(None) is None


def test_thumbnail_from_ydl_entry_prefers_largest():
    entry = {
        "id": "dQw4w9WgXcQ",
        "thumbnails": [
            {"url": "https://example.com/small.jpg", "width": 120, "height": 90},
            {"url": "https://example.com/big.jpg", "width": 480, "height": 360},
        ],
    }
    assert thumbnail_from_ydl_entry(entry) == "https://example.com/big.jpg"


def test_thumbnail_from_ydl_entry_fallback_id():
    assert thumbnail_from_ydl_entry({"id": "dQw4w9WgXcQ"}) == (
        "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
    )


def test_input_web_thumb():
    thumb = input_web_thumb("https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg")
    assert thumb.url.endswith("hqdefault.jpg")
    assert thumb.mime_type == "image/jpeg"
