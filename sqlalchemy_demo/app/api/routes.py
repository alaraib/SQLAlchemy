from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, status

from app.dependencies import get_device_service
from app.logging_config import safe_device_id
from app.schemas import (
    AlertResponse,
    DeviceCreate,
    DeviceResponse,
    DeviceStatusUpdate,
    DeviceSummary,
    ProbeResponse,
)
from app.services.device_service import DeviceService


router = APIRouter()
logger = structlog.get_logger("netpulse.device_routes")
DeviceServiceDep = Annotated[
    DeviceService,
    Depends(get_device_service, scope="function"),
]


@router.post(
    "/devices",
    response_model=DeviceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_device(payload: DeviceCreate, service: DeviceServiceDep) -> DeviceResponse:
    logger.info("device_registration_requested", device_id=safe_device_id(payload.device_id))
    return service.create_device(payload)


@router.get("/devices/summary", response_model=DeviceSummary)
def get_device_summary(service: DeviceServiceDep) -> DeviceSummary:
    return service.get_summary()


@router.get("/devices", response_model=list[DeviceResponse])
def list_devices(service: DeviceServiceDep) -> list[DeviceResponse]:
    return service.list_devices()


@router.get("/devices/{device_id}", response_model=DeviceResponse)
def get_device(device_id: str, service: DeviceServiceDep) -> DeviceResponse:
    return service.get_device(device_id)


@router.patch("/devices/{device_id}/status", response_model=DeviceResponse)
def update_device_status(
    device_id: str,
    payload: DeviceStatusUpdate,
    service: DeviceServiceDep,
) -> DeviceResponse:
    return service.update_status(device_id, payload.status)


def load_probe_device(device_id: str, service: DeviceServiceDep) -> DeviceResponse:
    return service.get_device(device_id)


@router.get("/devices/{device_id}/probe", response_model=ProbeResponse)
async def probe_device(
    device: Annotated[
        DeviceResponse,
        Depends(load_probe_device, scope="function"),
    ],
    service: DeviceServiceDep,
) -> ProbeResponse:
    return await service.probe_device(device)


@router.get("/alerts", response_model=list[AlertResponse])
def list_alerts(service: DeviceServiceDep) -> list[AlertResponse]:
    return service.list_alerts()