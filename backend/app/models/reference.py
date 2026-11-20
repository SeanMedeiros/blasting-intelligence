"""Reference data: site, areas, people, equipment, instruments and configuration."""
from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import false as sa_false
from sqlalchemy import true as sa_true
from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


class Site(Base):
    __tablename__ = "site"
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    region: Mapped[str | None] = mapped_column(String(120))
    client: Mapped[str | None] = mapped_column(String(120))


class Area(Base):
    __tablename__ = "area"
    site_id: Mapped[int] = mapped_column(ForeignKey("site.id"))
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    area_type: Mapped[str] = mapped_column(String(30))  # OPEN_PIT | QUARRY
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sa_true())
    benches: Mapped[list["Bench"]] = relationship(back_populates="area")


class Bench(Base):
    __tablename__ = "bench"
    area_id: Mapped[int] = mapped_column(ForeignKey("area.id"))
    code: Mapped[str] = mapped_column(String(30), unique=True)
    elevation_m: Mapped[float] = mapped_column(Float)
    bench_height_m: Mapped[float] = mapped_column(Float)
    rock_type: Mapped[str | None] = mapped_column(String(80))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sa_true())
    area: Mapped[Area] = relationship(back_populates="benches")


class Personnel(Base):
    __tablename__ = "personnel"
    code: Mapped[str] = mapped_column(String(20), unique=True)
    full_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(60))
    qualifications: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class TrainingRecord(Base):
    __tablename__ = "training_record"
    personnel_id: Mapped[int] = mapped_column(ForeignKey("personnel.id"))
    course: Mapped[str] = mapped_column(String(160))
    completed_on: Mapped[date] = mapped_column(Date)
    expires_on: Mapped[date | None] = mapped_column(Date)
    certificate_ref: Mapped[str | None] = mapped_column(String(80))


class Equipment(Base):
    __tablename__ = "equipment"
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    equipment_type: Mapped[str] = mapped_column(String(40))  # DRILL | MMU | SCANNER | VEHICLE
    status: Mapped[str] = mapped_column(String(20), default="AVAILABLE")  # AVAILABLE | DOWN | MAINTENANCE
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sa_true())


class EquipmentDowntime(Base):
    __tablename__ = "equipment_downtime"
    equipment_id: Mapped[int] = mapped_column(ForeignKey("equipment.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime)
    hours: Mapped[float] = mapped_column(Float)
    cause: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(30))  # BREAKDOWN | PLANNED_MAINTENANCE | STANDBY


class Instrument(Base):
    __tablename__ = "instrument"
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    instrument_type: Mapped[str] = mapped_column(String(40))
    serial_number: Mapped[str] = mapped_column(String(60))
    location: Mapped[str | None] = mapped_column(String(80))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sa_true())
    calibrations: Mapped[list["Calibration"]] = relationship(back_populates="instrument", order_by="Calibration.calibrated_on")


class Calibration(Base):
    __tablename__ = "calibration"
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id"))
    calibrated_on: Mapped[date] = mapped_column(Date)
    valid_until: Mapped[date] = mapped_column(Date)
    certificate_ref: Mapped[str] = mapped_column(String(80))
    performed_by: Mapped[str] = mapped_column(String(120))
    instrument: Mapped[Instrument] = relationship(back_populates="calibrations")


class ReferenceLimit(Base):
    """Configurable acceptance / reference limits.

    Values must come from authorized company, client or regulatory documentation.
    Demonstration values are flagged with is_demo_placeholder=True.
    """

    __tablename__ = "reference_limit"
    parameter: Mapped[str] = mapped_column(String(40))  # VISCOSITY | DENSITY | VOD | FLOWABILITY | NOX | PPV | DEPTH_TOL | DEVIATION_TOL | FACE_TOL
    scope: Mapped[str] = mapped_column(String(80), default="*")  # product code, station code or '*'
    min_value: Mapped[float | None] = mapped_column(Float)
    max_value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(20))
    source_document: Mapped[str] = mapped_column(String(200))
    effective_from: Mapped[date] = mapped_column(Date)
    owner: Mapped[str] = mapped_column(String(120))
    is_demo_placeholder: Mapped[bool] = mapped_column(Boolean, default=True)


class KpiTarget(Base):
    __tablename__ = "kpi_target"
    kpi_key: Mapped[str] = mapped_column(String(60), unique=True)
    target: Mapped[float] = mapped_column(Float)
    direction: Mapped[str] = mapped_column(String(10))  # HIGHER | LOWER
    is_demo_placeholder: Mapped[bool] = mapped_column(Boolean, default=True)


class AppSetting(Base):
    __tablename__ = "app_setting"
    key: Mapped[str] = mapped_column(String(60), unique=True)
    value: Mapped[dict] = mapped_column(JSON)


class AuditLog(Base):
    __tablename__ = "audit_log"
    entity: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[int] = mapped_column()
    action: Mapped[str] = mapped_column(String(20))  # CREATE | UPDATE | DELETE | STATUS
    performed_by: Mapped[str] = mapped_column(String(120))
    user_id: Mapped[int | None] = mapped_column(index=True)  # app_user.id (plain reference so history survives account removal)
    performed_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))
    changes: Mapped[dict | None] = mapped_column(JSON)


class Attachment(Base):
    """Evidence file linked to any record (entity + id). Never deleted: voided with a reason, kept for audit."""

    __tablename__ = "attachment"
    entity: Mapped[str] = mapped_column(String(40), index=True)
    entity_id: Mapped[int] = mapped_column(index=True)
    filename: Mapped[str] = mapped_column(String(200))  # original name, sanitized
    stored_name: Mapped[str] = mapped_column(String(80), unique=True)  # yyyy/mm/<uuid>.<ext> under data/attachments
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column()
    sha256: Mapped[str] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(String(300))
    uploaded_by: Mapped[str] = mapped_column(String(120))
    user_id: Mapped[int | None] = mapped_column()
    voided: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    void_reason: Mapped[str | None] = mapped_column(String(300))
    voided_by: Mapped[str | None] = mapped_column(String(120))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime)
