from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select

from app.db import database
from app.db.models import AlertRow, DeviceRow


def test_session_dependency_rolls_back_status_and_alert_together(
    test_session_factory,
):
    with test_session_factory() as setup_session:
        setup_session.add(
            DeviceRow(
                device_id="device-1",
                name="Test device",
                device_type="sensor",
                ip_address="192.0.2.1",
                status="online",
            )
        )
        setup_session.commit()

    session_dependency = database.get_session()
    session = next(session_dependency)
    device = session.get(DeviceRow, "device-1")
    assert device is not None
    device.status = "offline"
    session.add(
        AlertRow(
            device_id=device.device_id,
            message="Device went offline",
            timestamp=datetime.now(timezone.utc),
        )
    )

    with pytest.raises(RuntimeError, match="simulated failure"):
        session_dependency.throw(RuntimeError("simulated failure"))

    with test_session_factory() as verification_session:
        device = verification_session.get(DeviceRow, "device-1")
        alerts = verification_session.scalars(select(AlertRow)).all()

    assert device is not None
    assert device.status == "online"
    assert alerts == []
