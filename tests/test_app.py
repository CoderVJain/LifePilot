"""The simulator's HTTP surface. Offline and free: no Bedrock call here."""

from fastapi.testclient import TestClient

from simulator.app import app


def test_static_files_must_be_revalidated():
    """A cached app.js survived a server restart and a reload, so the page rendered the old card
    while the server served the new one. On video day that is a stale demo on camera."""
    with TestClient(app) as client:
        response = client.get("/app.js")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"


def test_the_page_still_loads():
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "LifePilot" in response.text
