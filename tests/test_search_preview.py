from PIL import Image

from komuzik.search_preview import (
    THUMB_H,
    THUMB_W,
    _thumb_slot,
    fmt_compact,
    fmt_duration,
    render_search_preview,
)


def test_fmt_compact():
    assert fmt_compact(None) == "—"
    assert fmt_compact(42) == "42"
    assert "тыс" in fmt_compact(1500)
    assert "млн" in fmt_compact(2_500_000)


def test_fmt_duration():
    assert fmt_duration(65) == "1:05"
    assert fmt_duration(3661) == "1:01:01"


def test_thumb_slot_always_fixed_size():
    weird = Image.new("RGB", (100, 400), (255, 0, 0))
    assert _thumb_slot(weird).size == (THUMB_W, THUMB_H)
    assert _thumb_slot(None).size == (THUMB_W, THUMB_H)


def test_render_search_preview_smoke():
    results = [
        {
            "title": "Test Video One",
            "channel": "Demo Channel",
            "duration": 125,
            "view_count": 12_000,
            "like_count": 340,
            "thumbnail": None,
        },
        {
            "title": "Another Long Title That Should Wrap Nicely On The Card",
            "channel": "Second",
            "duration": 61,
            "view_count": None,
            "like_count": None,
            "thumbnail": None,
        },
    ]
    path = render_search_preview(results, "demo query", start_index=11)
    assert path.exists()
    assert path.stat().st_size > 1000
    assert THUMB_W == 320 and THUMB_H == 180
    path.unlink(missing_ok=True)
    path.parent.rmdir()
