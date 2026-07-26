"""TTLCache must bound both entry lifetime and total size."""

import pytest

from komuzik.state import TTLCache


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _cache(*, maxsize: int = 3, ttl: float = 10, sliding: bool = False):
    clock = FakeClock()
    cache = TTLCache(maxsize=maxsize, ttl=ttl, sliding=sliding, timer=clock, name="test")
    return cache, clock


def test_rejects_invalid_bounds():
    with pytest.raises(ValueError, match="maxsize"):
        TTLCache(maxsize=0, ttl=1)
    with pytest.raises(ValueError, match="ttl"):
        TTLCache(maxsize=1, ttl=0)


def test_stores_and_reads_back():
    cache, _ = _cache()
    cache["a"] = 1
    assert cache["a"] == 1
    assert cache.get("a") == 1
    assert "a" in cache
    assert len(cache) == 1


def test_entry_expires_after_ttl():
    cache, clock = _cache()
    cache["a"] = 1

    clock.advance(9)
    assert cache.get("a") == 1

    clock.advance(2)
    assert cache.get("a") is None
    assert "a" not in cache
    assert len(cache) == 0


def test_expired_entries_are_actually_freed():
    """Lazy expiry must still release memory, not just hide the values."""
    cache, clock = _cache(maxsize=100)
    for i in range(50):
        cache[i] = i

    clock.advance(11)
    assert len(cache) == 0
    assert cache._data == {}


def test_evicts_oldest_beyond_maxsize():
    cache, _ = _cache(maxsize=3)
    for i in range(5):
        cache[i] = i

    assert len(cache) == 3
    assert sorted(cache.keys()) == [2, 3, 4]
    assert cache.evictions == 2


def test_reinsert_refreshes_position_not_duplicates():
    cache, _ = _cache(maxsize=3)
    cache["a"] = 1
    cache["b"] = 2
    cache["a"] = 3
    cache["c"] = 4
    cache["d"] = 5

    # 'b' is the oldest by last write, so it goes first
    assert cache.get("b") is None
    assert cache.get("a") == 3
    assert len(cache) == 3


def test_sliding_read_extends_lifetime():
    cache, clock = _cache(sliding=True)
    cache["a"] = 1

    for _ in range(5):
        clock.advance(8)
        assert cache.get("a") == 1

    clock.advance(11)
    assert cache.get("a") is None


def test_non_sliding_read_does_not_extend():
    cache, clock = _cache(sliding=False)
    cache["a"] = 1
    clock.advance(8)
    assert cache.get("a") == 1
    clock.advance(4)
    assert cache.get("a") is None


def test_pop_semantics():
    cache, _ = _cache()
    cache["a"] = 1

    assert cache.pop("a") == 1
    assert cache.get("a") is None
    assert cache.pop("a", "fallback") == "fallback"
    with pytest.raises(KeyError):
        cache.pop("missing")


def test_pop_of_expired_key_returns_default():
    cache, clock = _cache()
    cache["a"] = 1
    clock.advance(11)
    assert cache.pop("a", None) is None


def test_purge_keeps_deadline_order_under_sliding_reads():
    """_purge_expired walks from the front, so order must stay by deadline."""
    cache, clock = _cache(maxsize=10, sliding=True)
    cache["a"] = 1
    cache["b"] = 2
    cache["c"] = 3

    clock.advance(5)
    cache.get("a")  # refreshes 'a' to the tail

    clock.advance(6)  # b and c expired, a still alive
    assert len(cache) == 1
    assert cache.get("a") == 1


def test_inline_jobs_style_churn_stays_bounded():
    """Simulates inline search: many writes, almost no reads."""
    cache, _ = _cache(maxsize=5_000, ttl=900)
    for i in range(200_000):
        cache[f"token{i}"] = i

    assert len(cache) == 5_000
    assert cache.evictions == 195_000
