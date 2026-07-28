"""Places search + photo TTL cache."""

from places_search_cache import (
    get_photo_cache,
    get_search_cache,
    invalidate_search,
    set_photo_cache,
    set_search_cache,
)


def test_search_cache_roundtrip():
    invalidate_search()
    assert get_search_cache("okonsen", "foo") is None
    payload = set_search_cache("okonsen", "foo", {"ok": True, "places": [], "query": "q"})
    assert payload["places_cache_hit"] is False
    hit = get_search_cache("okonsen", "foo")
    assert hit and hit["places_cache_hit"] is True
    assert hit["query"] == "q"
    invalidate_search("okonsen", "foo")
    assert get_search_cache("okonsen", "foo") is None


def test_search_cache_site_invalidate():
    invalidate_search()
    set_search_cache("krcare", "a", {"ok": True, "places": []})
    set_search_cache("krcare", "b", {"ok": True, "places": []})
    set_search_cache("okonsen", "a", {"ok": True, "places": []})
    invalidate_search("krcare")
    assert get_search_cache("krcare", "a") is None
    assert get_search_cache("krcare", "b") is None
    assert get_search_cache("okonsen", "a") is not None
    invalidate_search()


def test_search_cache_expires(monkeypatch):
    invalidate_search()
    times = iter([1000.0, 1030.0, 90000.0])
    monkeypatch.setattr("places_search_cache.time.time", lambda: next(times))
    monkeypatch.setattr("places_search_cache.SEARCH_TTL_SEC", 60)
    set_search_cache("okonsen", "slug", {"ok": True, "places": []})
    assert get_search_cache("okonsen", "slug") is not None
    assert get_search_cache("okonsen", "slug") is None
    invalidate_search()


def test_photo_cache_roundtrip():
    invalidate_search()
    ref = "places/ChIJxxx/photos/abc"
    assert get_photo_cache(ref) is None
    set_photo_cache(ref, b"jpeg-bytes")
    assert get_photo_cache(ref) == b"jpeg-bytes"
    invalidate_search()


def test_photo_cache_evicts_oldest(monkeypatch):
    invalidate_search()
    monkeypatch.setattr("places_search_cache.PHOTO_CACHE_MAX", 2)
    monkeypatch.setattr("places_search_cache.PHOTO_TTL_SEC", 100)
    tick = iter([10.0, 20.0, 30.0, 40.0, 50.0])
    monkeypatch.setattr("places_search_cache.time.time", lambda: next(tick))
    set_photo_cache("places/a/photos/1", b"1")
    set_photo_cache("places/b/photos/2", b"2")
    set_photo_cache("places/c/photos/3", b"3")
    assert get_photo_cache("places/a/photos/1") is None
    assert get_photo_cache("places/c/photos/3") == b"3"
    invalidate_search()
