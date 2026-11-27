import asyncio
import json
import logging
import subprocess
import sys
from datetime import datetime

import pytest
import structlog
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import database
from app.db.models import AlertRow, DeviceRow
from app.logging_config import configure_logging, redact_sensitive_fields
from app.repositories.in_memory_device_repository import InMemoryDeviceRepository
from app.repositories.sqlalchemy_device_repository import SQLAlchemyDeviceRepository
from app.schemas import DeviceCreate
from app.services.device_service import DeviceService


def device_payload(device_id, name, device_type, ip_address):
    return {
        "device_id": device_id,
        "name": name,
        "device_type": device_type,
        "ip_address": ip_address,
        "status": "online",
    }


@pytest.fixture
def app_logs(caplog):
    logger = logging.getLogger("netpulse")
    logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger="netpulse")
    try:
        yield caplog
    finally:
        logger.removeHandler(caplog.handler)


def test_routes_use_overridden_session(client, test_app, test_engine):
    original_override = test_app.dependency_overrides[database.get_session]
    used_engines = []

    def tracking_override():
        session_generator = original_override()
        session = next(session_generator)
        used_engines.append(session.get_bind())
        try:
            yield session
        except BaseException as error:
            session_generator.throw(error)
        else:
            next(session_generator, None)

    test_app.dependency_overrides[database.get_session] = tracking_override

    assert client.get("/devices").status_code == 200
    assert used_engines == [test_engine]


def test_create_read_update_and_summary(client):
    first = device_payload(
        "RTR-101", "Branch Router", "router", "192.168.10.1"
    )
    second = device_payload(
        "SW-102", "Floor Switch", "switch", "192.168.10.2"
    )

    assert client.post("/devices", json=first).status_code == 201
    assert client.post("/devices", json=second).status_code == 201

    devices = client.get("/devices").json()
    assert [device["device_id"] for device in devices] == ["RTR-101", "SW-102"]
    assert client.get("/devices/RTR-101").json() == first
    assert client.get("/devices/summary").json() == {
        "total_devices": 2,
        "online_count": 2,
        "offline_count": 0,
        "device_types": ["router", "switch"],
    }

    updated = client.patch(
        "/devices/RTR-101/status",
        json={"status": "offline"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "offline"
    assert client.get("/devices/summary").json() == {
        "total_devices": 2,
        "online_count": 1,
        "offline_count": 1,
        "device_types": ["router", "switch"],
    }


def test_duplicate_missing_and_validation_errors(client):
    payload = device_payload(
        "RTR-101", "Branch Router", "router", "192.168.10.1"
    )
    assert client.post("/devices", json=payload).status_code == 201
    assert client.post("/devices", json=payload).status_code == 409
    assert client.get("/devices/unknown").status_code == 404
    assert client.patch(
        "/devices/unknown/status",
        json={"status": "offline"},
    ).status_code == 404
    assert client.post("/devices", json={"device_id": "invalid"}).status_code == 422


def test_offline_transition_emits_one_alert_and_probe_is_read_only(
    client, test_session_factory
):
    payload = device_payload(
        "RTR-101", "Branch Router", "router", "192.168.10.1"
    )
    assert client.post("/devices", json=payload).status_code == 201

    assert client.patch(
        "/devices/RTR-101/status",
        json={"status": "offline"},
    ).status_code == 200
    assert client.patch(
        "/devices/RTR-101/status",
        json={"status": "offline"},
    ).status_code == 200

    alerts = client.get("/alerts").json()
    assert len(alerts) == 1
    assert alerts[0]["device_id"] == "RTR-101"
    assert client.get("/devices/RTR-101/probe").json() == {
        "device_id": "RTR-101",
        "simulated": True,
        "reachable": True,
    }
    assert client.get("/devices/RTR-101").json()["status"] == "offline"
    assert len(client.get("/alerts").json()) == 1
    with test_session_factory() as session:
        device = session.get(DeviceRow, "RTR-101")
        persisted_alerts = session.scalars(select(AlertRow)).all()
        assert device is not None
        assert device.status == "offline"
        assert len(persisted_alerts) == 1
        assert persisted_alerts[0].device_id == "RTR-101"


def test_probe_service_remains_async():
    service = DeviceService(InMemoryDeviceRepository())
    device = service.create_device(
        DeviceCreate(
            device_id="RTR-201",
            name="Probe Router",
            device_type="router",
            ip_address="192.168.20.1",
            status="online",
        )
    )

    result = asyncio.run(service.probe_device(device))

    assert result.simulated is True
    assert result.reachable is True


def test_records_persist_across_app_restart(
    test_app,
):
    payload = device_payload(
        "RTR-101", "Branch Router", "router", "192.168.10.1"
    )
    with TestClient(test_app) as first_client:
        assert first_client.post("/devices", json=payload).status_code == 201
        first_client.patch(
            "/devices/RTR-101/status",
            json={"status": "offline"},
        )

    with TestClient(test_app) as restarted_client:
        assert restarted_client.get("/devices").json()[0]["status"] == "offline"
        assert len(restarted_client.get("/alerts").json()) == 1


def test_registration_and_missing_device_logging(client, app_logs):
    payload = device_payload(
        "RTR-101", "secret-name", "router", "192.168.10.1"
    )

    with structlog.contextvars.bound_contextvars(token="secret-token"):
        assert client.post("/devices", json=payload).status_code == 201
        assert client.post("/devices", json=payload).status_code == 409
        assert client.get("/devices/SW-102").status_code == 404
        assert client.get("/devices/password-token").status_code == 404

    records = [
        record for record in app_logs.records if record.name.startswith("netpulse.")
    ]
    events = [json.loads(record.getMessage()) for record in records]
    events = [event for event in events if event["event"] != "request_completed"]
    assert [(event["event"], event["level"], event["device_id"]) for event in events] == [
        ("device_registration_requested", "info", "RTR-101"),
        ("device_registered", "info", "RTR-101"),
        ("device_registration_requested", "info", "RTR-101"),
        ("domain_error", "warning", "RTR-101"),
        ("domain_error", "warning", "SW-102"),
        ("domain_error", "warning", "[redacted]"),
    ]
    for event in events:
        assert {"event", "level", "timestamp", "device_id", "request_id"} <= set(event)
        assert datetime.fromisoformat(event["timestamp"]).utcoffset().total_seconds() == 0
    assert "secret-name" not in app_logs.text
    assert "password-token" not in app_logs.text
    assert "secret-token" not in app_logs.text


def test_workflow_events_use_request_context_and_skip_noops(client, app_logs):
    payload = device_payload(
        "RTR-101", "Branch Router", "router", "192.168.10.1"
    )
    assert client.post(
        "/devices", json=payload, headers={"X-Request-ID": "create-1"}
    ).status_code == 201
    assert client.patch(
        "/devices/RTR-101/status",
        json={"status": "offline"},
        headers={"X-Request-ID": "update-1"},
    ).status_code == 200
    assert client.patch(
        "/devices/RTR-101/status",
        json={"status": "offline"},
        headers={"X-Request-ID": "update-2"},
    ).status_code == 200

    events = [json.loads(record.getMessage()) for record in app_logs.records]
    events = [event for event in events if event["event"] != "request_completed"]
    assert [(event["event"], event["request_id"]) for event in events] == [
        ("device_registration_requested", "create-1"),
        ("device_registered", "create-1"),
        ("device_status_changed", "update-1"),
        ("offline_alert_created", "update-1"),
    ]
    assert all(event["device_id"] == "RTR-101" for event in events)


def test_online_transition_logs_status_but_no_offline_alert(client, app_logs):
    payload = device_payload("RTR-101", "Router", "router", "192.168.10.1")
    payload["status"] = "offline"
    assert client.post("/devices", json=payload).status_code == 201
    app_logs.clear()

    response = client.patch(
        "/devices/RTR-101/status", json={"status": "online"},
        headers={"X-Request-ID": "restore-1"},
    )

    assert response.status_code == 200
    events = [json.loads(record.getMessage()) for record in app_logs.records]
    events = [event for event in events if event["event"] != "request_completed"]
    assert [(event["event"], event["request_id"]) for event in events] == [
        ("device_status_changed", "restore-1")
    ]
    assert client.get("/alerts").json() == []


def test_failed_alert_staging_does_not_log_success(client, app_logs, monkeypatch):
    payload = device_payload("RTR-101", "Router", "router", "192.168.10.1")
    assert client.post("/devices", json=payload).status_code == 201
    app_logs.clear()

    def fail_alert(repository, device_id, message):
        raise RuntimeError("alert write failed")

    monkeypatch.setattr(SQLAlchemyDeviceRepository, "add_alert", fail_alert)
    with pytest.raises(RuntimeError, match="alert write failed"):
        client.patch("/devices/RTR-101/status", json={"status": "offline"})

    events = [json.loads(record.getMessage()) for record in app_logs.records]
    assert [event["event"] for event in events] == ["request_failed", "request_completed"]
    assert client.get("/devices/RTR-101").json()["status"] == "online"


@pytest.mark.parametrize("request_id", ["abc_123-XYZ", "a" * 64])
def test_request_id_is_returned_and_used_in_logs(client, app_logs, request_id):
    response = client.get("/devices/SW-102", headers={"X-Request-ID": request_id})

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == request_id
    event = json.loads(app_logs.records[-1].getMessage())
    assert event["request_id"] == request_id


@pytest.mark.parametrize("request_id", [None, "", "bad/id", "bad id", "a" * 65])
def test_invalid_or_missing_request_id_is_replaced(client, app_logs, request_id):
    headers = {} if request_id is None else {"X-Request-ID": request_id}
    response = client.get("/devices/SW-102", headers=headers)

    assert response.status_code == 404
    generated_id = response.headers["X-Request-ID"]
    assert len(generated_id) == 32
    assert all(character in "0123456789abcdef" for character in generated_id)
    assert json.loads(app_logs.records[-1].getMessage())["request_id"] == generated_id


@pytest.mark.parametrize("request_id", [None, "client-123", "bad/id"])
def test_request_id_in_rendered_json(client, capsys, monkeypatch, request_id):
    logger = logging.getLogger("netpulse")
    monkeypatch.setattr(logger, "handlers", [logging.StreamHandler(sys.stderr)])
    headers = {} if request_id is None else {"X-Request-ID": request_id}

    response = client.get("/devices/SW-102", headers=headers)

    assert response.status_code == 404
    response_id = response.headers["X-Request-ID"]
    if request_id == "client-123":
        assert response_id == request_id
    else:
        assert len(response_id) == 32
        assert all(character in "0123456789abcdef" for character in response_id)
    events = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    completed = [event for event in events if event["event"] == "request_completed"]
    assert len(completed) == 1
    assert completed[0]["level"] == "info"
    assert completed[0]["request_id"] == response_id
    assert datetime.fromisoformat(completed[0]["timestamp"]).utcoffset().total_seconds() == 0


def test_request_ids_do_not_leak_between_requests(client, app_logs):
    first = client.get("/devices/SW-102", headers={"X-Request-ID": "first-request"})
    second = client.get("/devices/SW-102")

    first_id = first.headers["X-Request-ID"]
    second_id = second.headers["X-Request-ID"]
    events = [json.loads(record.getMessage()) for record in app_logs.records]
    events = [event for event in events if event["event"] == "request_completed"]
    assert first_id == "first-request"
    assert second_id != first_id
    assert [event["request_id"] for event in events] == [first_id, second_id]


def test_request_completion_uses_route_template_and_excludes_query(client, app_logs):
    response = client.get(
        "/devices/SW-102?token=secret-query",
        headers={"X-Request-ID": "request-404"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Device 'SW-102' not found"}
    events = [json.loads(record.getMessage()) for record in app_logs.records]
    warnings = [event for event in events if event["level"] == "warning"]
    assert len(warnings) == 1
    assert warnings[0]["error_type"] == "DeviceNotFoundError"
    assert warnings[0]["device_id"] == "SW-102"
    completed = [event for event in events if event["event"] == "request_completed"]
    assert len(completed) == 1
    assert completed[0]["request_id"] == "request-404"
    assert completed[0]["method"] == "GET"
    assert completed[0]["path"] == "/devices/{device_id}"
    assert completed[0]["status_code"] == 404
    assert completed[0]["duration_ms"] >= 0
    assert "secret-query" not in app_logs.text


def test_duplicate_warning_and_fallback_path(client, app_logs):
    payload = device_payload("RTR-101", "Router", "router", "192.168.10.1")
    assert client.post("/devices", json=payload).status_code == 201
    app_logs.clear()

    duplicate = client.post("/devices", json=payload)
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "Device 'RTR-101' already exists"}
    events = [json.loads(record.getMessage()) for record in app_logs.records]
    warnings = [event for event in events if event["level"] == "warning"]
    assert len(warnings) == 1
    assert warnings[0]["error_type"] == "DuplicateDeviceError"
    assert warnings[0]["device_id"] == "RTR-101"
    assert len([event for event in events if event["event"] == "request_completed"]) == 1

    app_logs.clear()
    assert client.get("/not-a-route?password=secret-query").status_code == 404
    events = [json.loads(record.getMessage()) for record in app_logs.records]
    assert len(events) == 1
    assert events[0]["event"] == "request_completed"
    assert events[0]["path"] == "/not-a-route"
    assert events[0]["status_code"] == 404
    assert "secret-query" not in app_logs.text


def test_unexpected_error_logs_safe_trace_and_one_completion(client, app_logs):
    @client.app.get("/test-secret-error")
    async def secret_error_route():
        raise RuntimeError("postgresql://user:password@host/db token=secret-value")

    with pytest.raises(RuntimeError):
        client.get(
            "/test-secret-error?token=secret-query",
            headers={"X-Request-ID": "request-error"},
        )

    events = [json.loads(record.getMessage()) for record in app_logs.records]
    assert [event["event"] for event in events] == ["request_failed", "request_completed"]
    failed, completed = events
    assert failed["level"] == "error"
    assert failed["error_type"] == "RuntimeError"
    assert failed["request_id"] == "request-error"
    assert failed["stack_trace"]
    assert all(set(frame) == {"file", "line", "function"} for frame in failed["stack_trace"])
    assert completed["status_code"] == 500
    assert completed["path"] == "/test-secret-error"
    assert completed["request_id"] == "request-error"
    assert "secret-query" not in app_logs.text
    assert "secret-value" not in app_logs.text
    assert "postgresql://" not in app_logs.text


def test_request_context_is_cleared_on_exception(test_app, monkeypatch):
    contexts = []
    clear_contextvars = structlog.contextvars.clear_contextvars

    def record_and_clear():
        before = structlog.contextvars.get_contextvars()
        clear_contextvars()
        contexts.append((before, structlog.contextvars.get_contextvars()))

    monkeypatch.setattr(structlog.contextvars, "clear_contextvars", record_and_clear)

    @test_app.get("/test-error")
    async def error_route():
        assert structlog.contextvars.get_contextvars()["request_id"] == "request-1"
        raise RuntimeError("test failure")

    with TestClient(test_app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/test-error", headers={"X-Request-ID": "request-1"})

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert response.headers["X-Request-ID"] == "request-1"
    assert contexts[-1][0]["request_id"] == "request-1"
    assert contexts[-1][1] == {}


def test_failed_registration_commit_does_not_log_success(
    client, app_logs, monkeypatch, test_session_factory
):
    payload = device_payload(
        "RTR-101", "Branch Router", "router", "192.168.10.1"
    )

    def fail_commit(session):
        raise RuntimeError("commit failed")

    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="commit failed"):
            client.post("/devices", json=payload)

    assert not any("device_registered" in record.getMessage() for record in app_logs.records)
    with test_session_factory() as session:
        assert session.get(DeviceRow, "RTR-101") is None


def test_logging_configuration_is_idempotent():
    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_handlers = list(uvicorn_logger.handlers)
    configure_logging()
    app_logger = logging.getLogger("netpulse")
    app_handlers = list(app_logger.handlers)

    configure_logging()

    assert app_logger.level == logging.INFO
    assert app_logger.handlers == app_handlers
    assert uvicorn_logger.handlers == uvicorn_handlers


def test_json_output_is_not_duplicated_with_root_handler():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import logging, structlog; "
            "from app.logging_config import configure_logging; "
            "logging.getLogger().addHandler(logging.StreamHandler()); "
            "configure_logging(); configure_logging(); "
            "structlog.contextvars.bind_contextvars(device_id='RTR-101', token='secret'); "
            "structlog.get_logger('netpulse.test').info('device_registered')",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == ""
    lines = result.stderr.splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert set(event) == {"event", "level", "timestamp", "device_id", "token"}
    assert event["event"] == "device_registered"
    assert event["device_id"] == "RTR-101"
    assert event["token"] == "***"
    assert "secret" not in lines[0]


def test_redaction_processor_matches_exact_names_case_insensitively():
    event = {
        "PASSWORD": "demo",
        "Token": "demo",
        "API_Key": "demo",
        "Authorization": "demo",
        "secret": "demo",
        "token_count": 2,
        "device_id": "RTR-TEST",
    }

    redacted = redact_sensitive_fields(None, None, event)

    assert all(redacted[key] == "***" for key in (
        "PASSWORD", "Token", "API_Key", "Authorization", "secret"
    ))
    assert redacted["token_count"] == 2
    assert redacted["device_id"] == "RTR-TEST"


def test_demo_token_is_masked_in_json_output():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import structlog; "
            "from app.logging_config import configure_logging; "
            "configure_logging(); "
            "structlog.get_logger('netpulse.test').info("
            "'redaction_demo', token='DEMO-DO-NOT-USE', device_id='RTR-TEST')",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    event = json.loads(result.stderr.strip())
    assert event["token"] == "***"
    assert event["device_id"] == "RTR-TEST"
    assert "DEMO-DO-NOT-USE" not in result.stderr