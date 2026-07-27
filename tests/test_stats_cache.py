"""Stats infographic cache must keep caption and image in sync."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from komuzik import stats_infographic as si
from komuzik.handlers import BOT_GROUPS_CACHE, BotHandlers
from komuzik.stats_infographic import format_stats_caption


def _sample_stats(**overrides):
    base = {
        "total_users": 10,
        "total_groups": 2,
        "total_downloads": 100,
        "successful_downloads": 90,
        "by_source": {"dm": 50, "inline": 30, "group": 20},
    }
    base.update(overrides)
    return base


def test_format_stats_caption_mirrors_numbers():
    caption = format_stats_caption(_sample_stats(), "day")
    assert "за день" in caption
    assert "👥 10" in caption
    assert "💬 2" in caption
    assert "📥 100" in caption
    assert "✅ 90%" in caption
    assert "ЛС 50" in caption


def test_cache_hit_returns_frozen_stats(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(si, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(si, "CACHE_TTL_SECONDS", 300)

    frozen = _sample_stats(total_downloads=42)
    fresh = _sample_stats(total_downloads=999)

    png = tmp_path / f"stats_{si.CACHE_VERSION}_day.png"
    png.write_bytes(b"png")
    meta = tmp_path / f"stats_{si.CACHE_VERSION}_day.json"
    meta.write_text(
        json.dumps({"ts": __import__("time").time(), "stats": frozen}),
        encoding="utf-8",
    )

    with patch.object(si, "run_render", new=AsyncMock()) as render:
        image = asyncio.run(si.get_stats_image(fresh, "day"))

    render.assert_not_called()
    assert image.stats["total_downloads"] == 42
    assert format_stats_caption(image.stats, image.period) == format_stats_caption(
        frozen, "day"
    )
    assert "999" not in format_stats_caption(image.stats, image.period)


def test_cache_miss_writes_stats_snapshot(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(si, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(si, "CACHE_TTL_SECONDS", 300)

    stats = _sample_stats(total_downloads=7)

    async def fake_render(fn, stats_arg, period):
        out = tmp_path / f"stats_{period}_1.png"
        out.write_bytes(b"png")
        return out

    with patch.object(si, "run_render", new=fake_render):
        image = asyncio.run(si.get_stats_image(stats, "month"))

    assert image.stats is stats
    meta = tmp_path / f"stats_{si.CACHE_VERSION}_month.json"
    payload = json.loads(meta.read_text(encoding="utf-8"))
    assert payload["stats"]["total_downloads"] == 7
    assert image.path.exists()


def test_bot_groups_cache_avoids_second_dialog_walk():
    BOT_GROUPS_CACHE.clear()

    class Client:
        def __init__(self):
            self.calls = 0

        async def iter_dialogs(self):
            self.calls += 1
            yield type("D", (), {"is_group": True})()
            yield type("D", (), {"is_group": False})()
            yield type("D", (), {"is_group": True})()

    client = Client()
    handlers = BotHandlers.__new__(BotHandlers)
    handlers.client = client

    assert asyncio.run(handlers._count_bot_groups()) == 2
    assert asyncio.run(handlers._count_bot_groups()) == 2
    assert client.calls == 1
    BOT_GROUPS_CACHE.clear()
