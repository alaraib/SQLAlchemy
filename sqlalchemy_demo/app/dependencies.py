from app.db.database import SessionDep
from app.repositories.sqlalchemy_device_repository import SQLAlchemyDeviceRepository
from app.services.device_service import DeviceService


def get_device_service(session: SessionDep) -> DeviceService:
    return DeviceService(SQLAlchemyDeviceRepository(session))