import asyncio
from datetime import datetime, timedelta, timezone

from app.db import EventDatabase
from app.schemas import AutonomyRunRecord, TaskRecord, WindowEvent


def test_db_persists_events(tmp_path):
    db_path = tmp_path / "events.db"
    db = EventDatabase(str(db_path), retention_days=0, max_events=0)
    event = WindowEvent(
        type="foreground",
        hwnd="0x1",
        title="Docs",
        process_exe="C:\\Docs.exe",
        pid=101,
        timestamp=datetime.now(timezone.utc),
        source="test",
        category="docs",
    )
    asyncio.run(db.record_event(event))

    current, events, idle, idle_since = asyncio.run(db.load_snapshot(limit=10))
    assert len(events) == 1
    assert current is not None
    assert current.title == "Docs"
    assert idle is False
    assert idle_since is None


def _sample_run(run_id: str, updated_at: datetime) -> AutonomyRunRecord:
    return AutonomyRunRecord(
        run_id=run_id,
        task_id=f"task-{run_id}",
        objective=f"Objective {run_id}",
        status="completed",
        iteration=3,
        max_iterations=8,
        parallel_agents=2,
        auto_approve_irreversible=False,
        approval_token=None,
        last_error=None,
        started_at=updated_at - timedelta(seconds=10),
        updated_at=updated_at,
        finished_at=updated_at,
        agent_log=[],
    )


def test_db_autonomy_runs_pruned_to_max(tmp_path):
    db_path = tmp_path / "autonomy.db"
    db = EventDatabase(str(db_path), retention_days=0, max_events=0, max_autonomy_runs=2)
    now = datetime.now(timezone.utc)
    asyncio.run(db.upsert_autonomy_run(_sample_run("run-1", now)))
    asyncio.run(db.upsert_autonomy_run(_sample_run("run-2", now + timedelta(seconds=1))))
    asyncio.run(db.upsert_autonomy_run(_sample_run("run-3", now + timedelta(seconds=2))))

    rows = asyncio.run(db.list_autonomy_runs(limit=10))
    assert [row.run_id for row in rows] == ["run-3", "run-2"]


def test_db_autonomy_upsert_updates_existing_row(tmp_path):
    db_path = tmp_path / "autonomy-update.db"
    db = EventDatabase(str(db_path), retention_days=0, max_events=0, max_autonomy_runs=2)
    now = datetime.now(timezone.utc)
    first = _sample_run("run-x", now)
    asyncio.run(db.upsert_autonomy_run(first))

    updated = _sample_run("run-x", now + timedelta(seconds=5))
    updated.status = "failed"
    updated.last_error = "boom"
    asyncio.run(db.upsert_autonomy_run(updated))

    rows = asyncio.run(db.list_autonomy_runs(limit=10))
    assert len(rows) == 1
    assert rows[0].run_id == "run-x"
    assert rows[0].status == "failed"
    assert rows[0].last_error == "boom"


def test_db_autonomy_runs_pruned_by_retention_days(tmp_path):
    db_path = tmp_path / "autonomy-retention.db"
    db = EventDatabase(
        str(db_path),
        retention_days=0,
        max_events=0,
        max_autonomy_runs=0,
        autonomy_retention_days=1,
    )
    now = datetime.now(timezone.utc)
    old_run = _sample_run("run-old", now - timedelta(days=2))
    new_run = _sample_run("run-new", now)
    asyncio.run(db.upsert_autonomy_run(old_run))
    asyncio.run(db.upsert_autonomy_run(new_run))

    rows = asyncio.run(db.list_autonomy_runs(limit=10))
    assert [row.run_id for row in rows] == ["run-new"]


def _sample_task(task_id: str, updated_at: datetime) -> TaskRecord:
    return TaskRecord(
        task_id=task_id,
        objective=f"Task {task_id}",
        status="planned",
        current_step_index=None,
        steps=[],
        approval_token=None,
        last_error=None,
        created_at=updated_at - timedelta(seconds=5),
        updated_at=updated_at,
    )


def test_db_task_records_pruned_to_max(tmp_path):
    db_path = tmp_path / "tasks.db"
    db = EventDatabase(
        str(db_path),
        retention_days=0,
        max_events=0,
        max_autonomy_runs=0,
        max_task_records=2,
    )
    now = datetime.now(timezone.utc)
    asyncio.run(db.upsert_task_record(_sample_task("task-1", now)))
    asyncio.run(db.upsert_task_record(_sample_task("task-2", now + timedelta(seconds=1))))
    asyncio.run(db.upsert_task_record(_sample_task("task-3", now + timedelta(seconds=2))))

    rows = asyncio.run(db.list_task_records(limit=10))
    assert [row.task_id for row in rows] == ["task-3", "task-2"]


def test_db_task_records_pruned_by_retention_days(tmp_path):
    db_path = tmp_path / "tasks-retention.db"
    db = EventDatabase(
        str(db_path),
        retention_days=0,
        max_events=0,
        max_autonomy_runs=0,
        max_task_records=0,
        task_retention_days=1,
    )
    now = datetime.now(timezone.utc)
    old_task = _sample_task("task-old", now - timedelta(days=2))
    new_task = _sample_task("task-new", now)
    asyncio.run(db.upsert_task_record(old_task))
    asyncio.run(db.upsert_task_record(new_task))

    rows = asyncio.run(db.list_task_records(limit=10))
    assert [row.task_id for row in rows] == ["task-new"]


def test_db_supports_file_memory_uri_without_creating_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = EventDatabase("file::memory:?cache=shared", retention_days=0, max_events=0)
    event = WindowEvent(
        type="foreground",
        hwnd="0x9",
        title="URI Memory",
        process_exe="C:\\Uri.exe",
        pid=909,
        timestamp=datetime.now(timezone.utc),
        source="test",
    )
    asyncio.run(db.record_event(event))
    current, events, _idle, _idle_since = asyncio.run(db.load_snapshot(limit=10))
    assert current is not None
    assert len(events) == 1
    assert current.title == "URI Memory"
    # URI memory mode should not create an on-disk sqlite file in cwd.
    assert not (tmp_path / "file::memory:?cache=shared").exists()


def test_db_supports_file_uri_with_query_options(tmp_path):
    sqlite_uri = f"file:{tmp_path}/uri.db?mode=rwc"
    db = EventDatabase(sqlite_uri, retention_days=0, max_events=0)
    event = WindowEvent(
        type="foreground",
        hwnd="0xA",
        title="URI File",
        process_exe="C:\\UriFile.exe",
        pid=1001,
        timestamp=datetime.now(timezone.utc),
        source="test",
    )
    asyncio.run(db.record_event(event))

    # The underlying sqlite file should be created at the path in the URI.
    assert (tmp_path / "uri.db").exists()
    current, events, _idle, _idle_since = asyncio.run(db.load_snapshot(limit=10))
    assert current is not None
    assert len(events) == 1
    assert current.title == "URI File"


def test_db_file_uri_does_not_create_literal_file_scheme_dirs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sqlite_uri = f"file:{tmp_path}/uri-clean.db?mode=rwc"
    db = EventDatabase(sqlite_uri, retention_days=0, max_events=0)
    event = WindowEvent(
        type="foreground",
        hwnd="0xB",
        title="URI Clean",
        process_exe="C:\\UriClean.exe",
        pid=1101,
        timestamp=datetime.now(timezone.utc),
        source="test",
    )
    asyncio.run(db.record_event(event))
    assert (tmp_path / "uri-clean.db").exists()
    assert not (tmp_path / "file:").exists()


def test_db_runtime_settings_round_trip_and_clear(tmp_path):
    db_path = tmp_path / "runtime-settings.db"
    db = EventDatabase(str(db_path), retention_days=0, max_events=0)

    missing = asyncio.run(db.get_runtime_setting("autonomy_planner_mode"))
    assert missing is None

    asyncio.run(db.set_runtime_setting("autonomy_planner_mode", "auto"))
    loaded = asyncio.run(db.get_runtime_setting("autonomy_planner_mode"))
    assert loaded == "auto"

    asyncio.run(db.delete_runtime_setting("autonomy_planner_mode"))
    deleted = asyncio.run(db.get_runtime_setting("autonomy_planner_mode"))
    assert deleted is None

    asyncio.run(db.set_runtime_setting("autonomy_planner_mode", "auto"))
    asyncio.run(db.clear())
    after_clear = asyncio.run(db.get_runtime_setting("autonomy_planner_mode"))
    assert after_clear is None
