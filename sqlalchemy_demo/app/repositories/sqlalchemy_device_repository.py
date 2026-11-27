from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import AlertRow, DeviceRow
from app.errors import DuplicateDeviceError
from app.schemas import AlertResponse, DeviceCreate, DeviceResponse


class SQLAlchemyDeviceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_device(self, device_id: str) -> DeviceResponse | None:
        row = self.session.get(DeviceRow, device_id)
        return DeviceResponse.model_validate(row) if row is not None else None

    def list_devices(self) -> list[DeviceResponse]:
        rows = self.session.scalars(
            select(DeviceRow).order_by(DeviceRow.device_id)
        ).all()
        return [DeviceResponse.model_validate(row) for row in rows]

    def add_device(self, device: DeviceCreate) -> DeviceResponse:
        if self.session.get(DeviceRow, device.device_id) is not None:
            raise DuplicateDeviceError(device.device_id)
        row = DeviceRow(**device.model_dump())
        self.session.add(row)
        try:
            self.session.flush()
        except IntegrityError as error:
            raise DuplicateDeviceError(device.device_id) from error
        self.session.info.setdefault("registered_device_ids", []).append(device.device_id)
        return DeviceResponse.model_validate(row)

    def update_status(self, device_id: str, status: str) -> DeviceResponse | None:
        row = self.session.get(DeviceRow, device_id)
        if row is None:
            return None
        row.status = status
        return DeviceResponse.model_validate(row)

    def add_alert(self, device_id: str, message: str) -> AlertResponse:
        row = AlertRow(
            device_id=device_id,
            message=message,
            timestamp=datetime.now(timezone.utc),
        )
        self.session.add(row)
        self.session.flush()
        return AlertResponse.model_validate(row)

    def list_alerts(self) -> list[AlertResponse]:
        rows = self.session.scalars(select(AlertRow).order_by(AlertRow.id)).all()
        return [AlertResponse.model_validate(row) for row in rows]