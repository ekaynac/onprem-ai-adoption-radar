from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from radar.web.app import create_app


def _init_project(tmp_path: Path) -> None:
    from radar.init_project import initialize_project

    initialize_project(tmp_path)


def _form() -> dict[str, str]:
    return {
        "id": "rss-web-feed",
        "type": "rss",
        "project": "Web Feed",
        "category": "model_serving",
        "url": "https://example.com/feed.xml",
        "tags": "vendor-blog",
    }


def test_post_source_open_without_token(tmp_path: Path, monkeypatch) -> None:
    _init_project(tmp_path)
    monkeypatch.delenv("RADAR_API_TOKEN", raising=False)
    client = TestClient(create_app(tmp_path))

    response = client.post("/sources", data=_form(), follow_redirects=False)

    assert response.status_code in (302, 303)


def test_post_source_requires_token_when_set(
    tmp_path: Path, monkeypatch
) -> None:
    _init_project(tmp_path)
    monkeypatch.setenv("RADAR_API_TOKEN", "secret")
    client = TestClient(create_app(tmp_path))

    denied = client.post("/sources", data=_form(), follow_redirects=False)
    assert denied.status_code == 401

    wrong = client.post(
        "/sources",
        data=_form(),
        headers={"authorization": "Bearer nope"},
        follow_redirects=False,
    )
    assert wrong.status_code == 401

    ok = client.post(
        "/sources",
        data=_form(),
        headers={"authorization": "Bearer secret"},
        follow_redirects=False,
    )
    assert ok.status_code in (302, 303)


def test_post_source_rejects_cross_origin(tmp_path: Path) -> None:
    _init_project(tmp_path)
    client = TestClient(create_app(tmp_path))

    response = client.post(
        "/sources",
        data=_form(),
        headers={"origin": "https://evil.example"},
        follow_redirects=False,
    )

    assert response.status_code == 403


def test_post_source_allows_same_origin(tmp_path: Path) -> None:
    _init_project(tmp_path)
    client = TestClient(create_app(tmp_path))

    response = client.post(
        "/sources",
        data=_form(),
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )

    assert response.status_code in (302, 303)
