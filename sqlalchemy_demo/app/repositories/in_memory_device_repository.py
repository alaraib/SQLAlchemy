from datetime import datetime, timezone

from app.errors import DuplicateDeviceError
from app.schemas import AlertResponse, DeviceCreate, DeviceResponse


class InMemoryDeviceRepository:
    def __init__(self) -> None:
        self._devices: dict[str, DeviceResponse] = {}
        self._alerts: list[AlertResponse] = []

    def get_device(self, device_id: str) -> DeviceResponse | None:
        return self._devices.get(device_id)

    def list_devices(self) -> list[DeviceResponse]:
        return [self._devices[key] for key in sorted(self._devices)]

    def add_device(self, device: DeviceCreate) -> DeviceResponse:
        if device.device_id in self._devices:
            raise DuplicateDeviceError(device.device_id)
        stored_device = DeviceResponse.model_validate(device)
        self._devices[device.device_id] = stored_device
        return stored_device

    def update_status(self, device_id: str, status: str) -> DeviceResponse | None:
        device = self._devices.get(device_id)
        if device is None:
            return None
        updated_device = device.model_copy(update={"status": status})
        self._devices[device_id] = updated_device
        return updated_device

    def add_alert(self, device_id: str, message: str) -> AlertResponse:
        alert = AlertResponse(
            id=len(self._alerts) + 1,
            device_id=device_id,
            message=message,
            timestamp=datetime.now(timezone.utc),
        )
        self._alerts.append(alert)
        return alert

    def list_alerts(self) -> list[AlertResponse]:
        return list(self._alerts)