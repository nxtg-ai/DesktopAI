from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_post_event_updates_state():
    payload = {
        "type": "foreground",
        "hwnd": "0xABC",
        "title": "Test App",
        "process_exe": "C:\\Program Files\\Test\\Test.exe",
        "pid": 4242,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "test",
    }
    resp = client.post("/api/events", json=payload)
    assert resp.status_code == 200

    state = client.get("/api/state").json()
    assert state["current"]["title"] == "Test App"

    events = client.get("/api/events?limit=1").json()
    assert len(events["events"]) == 1
