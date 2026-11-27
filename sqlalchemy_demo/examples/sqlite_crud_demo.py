from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class Device(Base):
    __tablename__ = "devices"

    device_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)


def main() -> None:
    print("CRUD actions: Create, Read, Update, Delete")
    print("Create: insert a sample device with session.add().")
    print("Read: query and display the stored device.")
    print("Update: change the device status and display the result.")
    print("Delete: remove the sample device with session.delete().")

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "crud_demo.db"
        engine = create_engine(f"sqlite:///{database_path}")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)

        with SessionLocal() as session:
            device = Device(
                device_id="demo-device",
                name="Sample device",
                status="online",
            )
            session.add(device)
            session.commit()

        with SessionLocal() as session:
            device = session.scalars(select(Device)).one()
            print(f"Read result: {device.device_id} {device.name} {device.status}")
            device.status = "offline"
            session.commit()
            print(f"Update result: {device.device_id} {device.status}")

        with SessionLocal() as session:
            device = session.get(Device, "demo-device")
            if device is not None:
                session.delete(device)
                session.commit()
            print(f"Delete result: {session.get(Device, 'demo-device')}")

        engine.dispose()


if __name__ == "__main__":
    main()