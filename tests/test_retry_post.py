"""post_with_retry: same 429/5xx semantics as get_with_retry, for POST endpoints."""

import pytest

from radar.enrichment.retry import get_with_retry, post_with_retry


class _Response:
    def __init__(self, status_code: int = 200):
        self.status_code = status_code
        self.headers: dict[str, str] = {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Client:
    def __init__(self, statuses: list[int]):
        self._statuses = statuses
        self.post_calls: list[tuple[str, dict]] = []

    async def post(self, url: str, **kwargs):
        self.post_calls.append((url, kwargs))
        return _Response(self._statuses.pop(0))

    async def get(self, url: str, **kwargs):
        return _Response(self._statuses.pop(0))


@pytest.mark.asyncio
async def test_post_retries_429_then_succeeds(monkeypatch):
    import asyncio

    async def _no_sleep(_):
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    client = _Client([429, 200])

    response = await post_with_retry(client, "https://api.test/batch", json={"ids": []})

    assert response.status_code == 200
    assert len(client.post_calls) == 2
    assert client.post_calls[0][1] == {"json": {"ids": []}}


@pytest.mark.asyncio
async def test_post_raises_after_exhausting_retries(monkeypatch):
    import asyncio

    async def _no_sleep(_):
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    client = _Client([503, 503, 503, 503])

    with pytest.raises(RuntimeError, match="HTTP 503"):
        await post_with_retry(client, "https://api.test/batch")


@pytest.mark.asyncio
async def test_get_with_retry_still_works():
    client = _Client([200])

    response = await get_with_retry(client, "https://api.test/x")

    assert response.status_code == 200
