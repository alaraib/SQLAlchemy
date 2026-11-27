from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DeviceCreate(BaseModel):
    device_id: str
    name: str
    device_type: str
    ip_address: str
    status: str


class DeviceResponse(DeviceCreate):
    model_config = ConfigDict(from_attributes=True)


class DeviceStatusUpdate(BaseModel):
    status: str


class DeviceSummary(BaseModel):
    total_devices: int
    online_count: int
    offline_count: int
    device_types: list[str]


class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: str
    message: str
    timestamp: datetime


class ProbeResponse(BaseModel):
    device_id: str
    simulated: bool
    reachable: bool