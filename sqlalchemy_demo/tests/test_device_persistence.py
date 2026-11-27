from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models import AlertRow, DeviceRow


def test_device_and_alert_persist_across_sessions(test_session_factory):
    with test_session_factory() as session:
        session.add(
            DeviceRow(
                device_id="device-1",
                name="Test device",
                device_type="sensor",
                ip_address="192.0.2.1",
                status="online",
            )
        )
        session.commit()

    with test_session_factory() as session:
        device = session.get(DeviceRow, "device-1")
        assert device is not None
        assert device.status == "online"

        device.status = "offline"
        session.add(
            AlertRow(
                device_id=device.device_id,
                message="Device went offline",
                timestamp=datetime.now(timezone.utc),
            )
        )
        session.commit()

    with test_session_factory() as session:
        device = session.get(DeviceRow, "device-1")
        alerts = session.scalars(select(AlertRow)).all()

    assert device is not None
    assert device.status == "offline"
    assert len(alerts) == 1