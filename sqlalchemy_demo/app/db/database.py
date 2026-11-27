from collections.abc import Generator
from typing import Annotated

import structlog
from fastapi import Depends
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.logging_config import safe_device_id


logger = structlog.get_logger("netpulse.database")

DATABASE_URL = "sqlite:///./netpulse.db"
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
        for device_id in session.info.pop("registered_device_ids", []):
            logger.info("device_registered", device_id=safe_device_id(device_id))
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(get_session, scope="function")]
