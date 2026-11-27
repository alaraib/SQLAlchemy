import asyncio

import structlog

from app.errors import DeviceNotFoundError
from app.logging_config import safe_device_id
from app.repositories.device_repository import DeviceRepository
from app.schemas import (
    AlertResponse,
    DeviceCreate,
    DeviceResponse,
    DeviceSummary,
    ProbeResponse,
)


logger = structlog.get_logger("netpulse.device_service")


class DeviceService:
    def __init__(self, repository: DeviceRepository) -> None:
        self.repository = repository

    def create_device(self, device: DeviceCreate) -> DeviceResponse:
        return self.repository.add_device(device)

    def list_devices(self) -> list[DeviceResponse]:
        return self.repository.list_devices()

    def get_device(self, device_id: str) -> DeviceResponse:
        device = self.repository.get_device(device_id)
        if device is None:
            raise DeviceNotFoundError(device_id)
        return device

    def update_status(self, device_id: str, status: str) -> DeviceResponse:
        current = self.get_device(device_id)
        updated = self.repository.update_status(device_id, status)
        if updated is None:
            raise DeviceNotFoundError(device_id)
        if current.status == "online" and status == "offline":
            self.repository.add_alert(
                device_id,
                f"Device {device_id} went offline",
            )
        if current.status != status:
            logger.info("device_status_changed", device_id=safe_device_id(device_id))
        if current.status == "online" and status == "offline":
            logger.info("offline_alert_created", device_id=safe_device_id(device_id))
        return updated

    def get_summary(self) -> DeviceSummary:
        devices = self.repository.list_devices()
        return DeviceSummary(
            total_devices=len(devices),
            online_count=sum(device.status == "online" for device in devices),
            offline_count=sum(device.status == "offline" for device in devices),
            device_types=sorted({device.device_type for device in devices}),
        )

    def list_alerts(self) -> list[AlertResponse]:
        return self.repository.list_alerts()

    async def probe_device(self, device: DeviceResponse) -> ProbeResponse:
        await asyncio.sleep(0)
        return ProbeResponse(
            device_id=device.device_id,
            simulated=True,
            reachable=True,
        )