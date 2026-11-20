"""Planning, drilling, blasting, surveys and detonator traceability."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base

# ---------------------------------------------------------------- planning (02)


class WorkOrder(Base):
    __tablename__ = "work_order"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    area_id: Mapped[int] = mapped_column(ForeignKey("area.id"))
    wo_type: Mapped[str] = mapped_column(String(30))  # BLAST | SURVEY_CAMPAIGN | LAB_SAMPLING
    status: Mapped[str] = mapped_column(String(20))  # OPEN | IN_PROGRESS | COMPLETED | CANCELLED
    engineering_forecast_ref: Mapped[str | None] = mapped_column(String(80))
    planned_start: Mapped[date] = mapped_column(Date)
    planned_end: Mapped[date] = mapped_column(Date)
    actual_start: Mapped[date | None] = mapped_column(Date)
    actual_end: Mapped[date | None] = mapped_column(Date)
    forecast_tonnes: Mapped[float | None] = mapped_column(Float)
    actual_tonnes: Mapped[float | None] = mapped_column(Float)


class ScheduleItem(Base):
    __tablename__ = "schedule_item"
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_order.id"))
    activity: Mapped[str] = mapped_column(String(30))
    # DRILLING | FACE_SURVEY | HOLE_VERIFICATION | LOADING | BLAST | POST_BLAST_SURVEY | POST_BLAST_REVIEW
    planned_date: Mapped[date] = mapped_column(Date)
    actual_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20))  # PLANNED | IN_PROGRESS | DONE | DELAYED | CANCELLED
    resources: Mapped[str | None] = mapped_column(String(200))
    responsible_id: Mapped[int | None] = mapped_column(ForeignKey("personnel.id"))


class ScheduleChange(Base):
    __tablename__ = "schedule_change"
    schedule_item_id: Mapped[int] = mapped_column(ForeignKey("schedule_item.id"))
    changed_at: Mapped[datetime] = mapped_column(DateTime)
    old_date: Mapped[date] = mapped_column(Date)
    new_date: Mapped[date] = mapped_column(Date)
    cause_category: Mapped[str] = mapped_column(String(40))
    cause: Mapped[str] = mapped_column(Text)
    changed_by: Mapped[str] = mapped_column(String(120))


class DelayEvent(Base):
    __tablename__ = "delay_event"
    work_order_id: Mapped[int | None] = mapped_column(ForeignKey("work_order.id"))
    occurred_on: Mapped[date] = mapped_column(Date)
    category: Mapped[str] = mapped_column(String(40))
    # WEATHER | EQUIPMENT | PRODUCT_SUPPLY | CLIENT_ACCESS | REDRILL | AUTHORIZATION_WAIT | WILDLIFE_EXCLUSION | OTHER
    hours: Mapped[float] = mapped_column(Float)
    description: Mapped[str] = mapped_column(Text)


class Delivery(Base):
    __tablename__ = "delivery"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    product_name: Mapped[str] = mapped_column(String(120))
    destination_area_id: Mapped[int] = mapped_column(ForeignKey("area.id"))
    planned_date: Mapped[date] = mapped_column(Date)
    actual_date: Mapped[date | None] = mapped_column(Date)
    planned_qty: Mapped[float] = mapped_column(Float)
    delivered_qty: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(10), default="t")
    status: Mapped[str] = mapped_column(String(20))  # SCHEDULED | IN_TRANSIT | DELIVERED | LATE | PARTIAL
    document_ref: Mapped[str | None] = mapped_column(String(80))


# ---------------------------------------------------------------- drilling (04)


class DrillPattern(Base):
    __tablename__ = "drill_pattern"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    bench_id: Mapped[int] = mapped_column(ForeignKey("bench.id"))
    design_document_ref: Mapped[str] = mapped_column(String(80))
    approved_by: Mapped[str] = mapped_column(String(120))
    hole_count: Mapped[int] = mapped_column(Integer)
    hole_diameter_mm: Mapped[float] = mapped_column(Float)
    drilled_on: Mapped[date | None] = mapped_column(Date)
    origin_x: Mapped[float] = mapped_column(Float)
    origin_y: Mapped[float] = mapped_column(Float)
    holes: Mapped[list["Drillhole"]] = relationship(back_populates="pattern", order_by="Drillhole.hole_code")


class Drillhole(Base):
    __tablename__ = "drillhole"
    pattern_id: Mapped[int] = mapped_column(ForeignKey("drill_pattern.id"))
    hole_code: Mapped[str] = mapped_column(String(20))
    row_no: Mapped[int] = mapped_column(Integer)
    col_no: Mapped[int] = mapped_column(Integer)
    planned_x: Mapped[float] = mapped_column(Float)
    planned_y: Mapped[float] = mapped_column(Float)
    planned_z: Mapped[float] = mapped_column(Float)
    planned_depth_m: Mapped[float] = mapped_column(Float)
    planned_dip_deg: Mapped[float] = mapped_column(Float, default=90.0)
    planned_azimuth_deg: Mapped[float] = mapped_column(Float, default=0.0)
    pattern: Mapped[DrillPattern] = relationship(back_populates="holes")
    measurements: Mapped[list["DrillholeMeasurement"]] = relationship(back_populates="drillhole", order_by="DrillholeMeasurement.measured_at")


class DrillholeMeasurement(Base):
    __tablename__ = "drillhole_measurement"
    drillhole_id: Mapped[int] = mapped_column(ForeignKey("drillhole.id"))
    measured_at: Mapped[datetime] = mapped_column(DateTime)
    technician_id: Mapped[int] = mapped_column(ForeignKey("personnel.id"))
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instrument.id"))
    measured_depth_m: Mapped[float] = mapped_column(Float)
    collar_offset_m: Mapped[float] = mapped_column(Float, default=0.0)
    toe_deviation_m: Mapped[float | None] = mapped_column(Float)
    water_present: Mapped[bool] = mapped_column(Boolean, default=False)
    hole_condition: Mapped[str] = mapped_column(String(30), default="OPEN")  # OPEN | PARTIALLY_BLOCKED | COLLAPSED
    inspection_status: Mapped[str] = mapped_column(String(30))  # WITHIN_TOLERANCE | OUT_OF_TOLERANCE | REDRILL_REQUIRED | ACCEPTED_BY_ENGINEER
    notes: Mapped[str | None] = mapped_column(Text)
    drillhole: Mapped[Drillhole] = relationship(back_populates="measurements")


class ApprovedLoadingRecord(Base):
    """Documentary reference to the approved loading parameters.

    The application stores the reference only. It never calculates or prescribes
    explosive quantities or loading instructions.
    """

    __tablename__ = "approved_loading_record"
    pattern_id: Mapped[int] = mapped_column(ForeignKey("drill_pattern.id"))
    document_ref: Mapped[str] = mapped_column(String(80))
    revision: Mapped[str] = mapped_column(String(10))
    approved_by: Mapped[str] = mapped_column(String(120))
    approved_on: Mapped[date] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------- blasting (05)


class Blast(Base):
    __tablename__ = "blast"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_order.id"))
    bench_id: Mapped[int] = mapped_column(ForeignKey("bench.id"))
    pattern_id: Mapped[int] = mapped_column(ForeignKey("drill_pattern.id"))
    approved_plan_ref: Mapped[str] = mapped_column(String(80))
    planned_date: Mapped[date] = mapped_column(Date)
    fired_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(30))
    # PLANNED | IN_PREPARATION | UNDER_INSPECTION | AUTHORIZED | IN_PROGRESS | AWAITING_VERIFICATION | COMPLETED | CLOSED
    supervisor_id: Mapped[int | None] = mapped_column(ForeignKey("personnel.id"))
    blaster_id: Mapped[int | None] = mapped_column(ForeignKey("personnel.id"))
    # External authorization (recorded, never issued by the software)
    authorization_ref: Mapped[str | None] = mapped_column(String(80))
    authorized_by: Mapped[str | None] = mapped_column(String(120))
    authorized_role: Mapped[str | None] = mapped_column(String(80))
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime)
    equipment_codes: Mapped[str | None] = mapped_column(String(200))
    rock_tonnes_forecast: Mapped[float | None] = mapped_column(Float)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)


class BlastStatusHistory(Base):
    __tablename__ = "blast_status_history"
    blast_id: Mapped[int] = mapped_column(ForeignKey("blast.id"))
    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30))
    changed_at: Mapped[datetime] = mapped_column(DateTime)
    changed_by: Mapped[str] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(Text)


class BlastCheckpoint(Base):
    __tablename__ = "blast_checkpoint"
    blast_id: Mapped[int] = mapped_column(ForeignKey("blast.id"))
    stage: Mapped[str] = mapped_column(String(30))  # PREPARATION | LOADING | PRE_BLAST | POST_BLAST
    name: Mapped[str] = mapped_column(String(200))
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_by: Mapped[str | None] = mapped_column(String(120))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    evidence_ref: Mapped[str | None] = mapped_column(String(120))


class InventoryMovement(Base):
    """Administrative product inventory reconciliation (received / used / returned)."""

    __tablename__ = "inventory_movement"
    blast_id: Mapped[int | None] = mapped_column(ForeignKey("blast.id"))
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("product_batch.id"))
    product_name: Mapped[str] = mapped_column(String(120))
    movement_type: Mapped[str] = mapped_column(String(20))  # RECEIVED | USED | RETURNED
    quantity: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(10))
    recorded_at: Mapped[datetime] = mapped_column(DateTime)
    recorded_by: Mapped[str] = mapped_column(String(120))
    document_ref: Mapped[str | None] = mapped_column(String(80))


# ---------------------------------------------------------------- 3D surveys (03)


class Survey(Base):
    __tablename__ = "survey"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    area_id: Mapped[int] = mapped_column(ForeignKey("area.id"))
    bench_id: Mapped[int | None] = mapped_column(ForeignKey("bench.id"))
    blast_id: Mapped[int | None] = mapped_column(ForeignKey("blast.id"))
    survey_type: Mapped[str] = mapped_column(String(30))  # FACE_PROFILE | PRE_BLAST | POST_BLAST | MUCKPILE
    surveyed_at: Mapped[datetime] = mapped_column(DateTime)
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instrument.id"))
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("personnel.id"))
    point_count: Mapped[int] = mapped_column(Integer)
    point_spacing_mm: Mapped[float | None] = mapped_column(Float)
    registration_error_mm: Mapped[float | None] = mapped_column(Float)
    coordinate_system: Mapped[str] = mapped_column(String(60), default="Local mine grid")
    file_path: Mapped[str | None] = mapped_column(String(200))
    file_format: Mapped[str | None] = mapped_column(String(10))
    quality_status: Mapped[str] = mapped_column(String(20))  # ACCEPTED | REVIEW | REJECTED | PENDING
    quality_notes: Mapped[str | None] = mapped_column(Text)


class SurveyComparison(Base):
    __tablename__ = "survey_comparison"
    reference_survey_id: Mapped[int | None] = mapped_column(ForeignKey("survey.id"))
    reference_label: Mapped[str] = mapped_column(String(80), default="")
    computed_by: Mapped[str | None] = mapped_column(String(120))
    compared_survey_id: Mapped[int] = mapped_column(ForeignKey("survey.id"))
    tolerance_m: Mapped[float] = mapped_column(Float)
    mean_m: Mapped[float] = mapped_column(Float)
    std_m: Mapped[float] = mapped_column(Float)
    p05_m: Mapped[float] = mapped_column(Float)
    p95_m: Mapped[float] = mapped_column(Float)
    max_abs_m: Mapped[float] = mapped_column(Float)
    within_tolerance_pct: Mapped[float] = mapped_column(Float)
    histogram: Mapped[dict | None] = mapped_column(JSON)


# ---------------------------------------------------------------- detonators (08)


class DetonatorRecord(Base):
    """Administrative traceability only. No programming, wiring or firing data."""

    __tablename__ = "detonator_record"
    blast_id: Mapped[int] = mapped_column(ForeignKey("blast.id"))
    inventory_lot_ref: Mapped[str] = mapped_column(String(60))
    units_issued: Mapped[int] = mapped_column(Integer)
    units_used: Mapped[int | None] = mapped_column(Integer)
    units_returned: Mapped[int | None] = mapped_column(Integer)
    equipment_ref: Mapped[str | None] = mapped_column(String(80))  # e.g. logger/blasting box asset tag
    authorized_personnel: Mapped[str] = mapped_column(String(200))
    procedure_ref: Mapped[str] = mapped_column(String(80))
    inspection_status: Mapped[str] = mapped_column(String(20))  # PENDING | DONE
    documentation_status: Mapped[str] = mapped_column(String(20))  # INCOMPLETE | COMPLETE
    verified_by: Mapped[str | None] = mapped_column(String(120))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)


class TraceabilityException(Base):
    __tablename__ = "traceability_exception"
    detonator_record_id: Mapped[int] = mapped_column(ForeignKey("detonator_record.id"))
    raised_at: Mapped[datetime] = mapped_column(DateTime)
    description: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(10))  # LOW | MEDIUM | HIGH
    status: Mapped[str] = mapped_column(String(20))  # OPEN | CLOSED
    resolution: Mapped[str | None] = mapped_column(Text)
