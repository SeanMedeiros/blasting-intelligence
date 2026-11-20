"""Product laboratory, vibration monitoring, QSSE and post-blast analysis."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import true as sa_true
from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base

# ---------------------------------------------------------------- laboratory (06)


class ProductBatch(Base):
    __tablename__ = "product_batch"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    product_code: Mapped[str] = mapped_column(String(20))
    product_name: Mapped[str] = mapped_column(String(120))
    produced_on: Mapped[date] = mapped_column(Date)
    quantity: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(10), default="t")
    status: Mapped[str] = mapped_column(String(20))  # RELEASED | QUARANTINE | REJECTED | PENDING_TESTS


class LabTest(Base):
    __tablename__ = "lab_test"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("product_batch.id"))
    blast_id: Mapped[int | None] = mapped_column(ForeignKey("blast.id"))  # VOD field tests
    test_type: Mapped[str] = mapped_column(String(20))  # VISCOSITY | DENSITY | VOD | FLOWABILITY | NOX
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id"))
    tested_at: Mapped[datetime] = mapped_column(DateTime)
    technician_id: Mapped[int] = mapped_column(ForeignKey("personnel.id"))
    value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(20))
    test_conditions: Mapped[str | None] = mapped_column(Text)
    sample_temperature_c: Mapped[float | None] = mapped_column(Float)
    approved_test_ref: Mapped[str | None] = mapped_column(String(80))
    data_quality: Mapped[str] = mapped_column(String(20))  # VALID | QUESTIONABLE | INVALID
    calibration_valid: Mapped[bool] = mapped_column(default=True)
    limit_id: Mapped[int | None] = mapped_column(ForeignKey("reference_limit.id"))
    limit_min: Mapped[float | None] = mapped_column(Float)  # snapshot at time of evaluation
    limit_max: Mapped[float | None] = mapped_column(Float)
    result: Mapped[str] = mapped_column(String(20))  # PASS | FAIL | NOT_EVALUATED
    notes: Mapped[str | None] = mapped_column(Text)


class NonConformance(Base):
    __tablename__ = "nonconformance"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    lab_test_id: Mapped[int | None] = mapped_column(ForeignKey("lab_test.id"))
    raised_on: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(Text)
    disposition: Mapped[str | None] = mapped_column(String(40))  # RETEST | QUARANTINE | REJECT | USE_AS_IS_ENGINEERING
    status: Mapped[str] = mapped_column(String(20))  # OPEN | CLOSED


# ---------------------------------------------------------------- vibration (07)


class MonitorStation(Base):
    __tablename__ = "monitor_station"
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    station_type: Mapped[str] = mapped_column(String(30))  # RECEPTOR | STRUCTURE | PIT_EDGE
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instrument.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sa_true())


class VibrationEvent(Base):
    __tablename__ = "vibration_event"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    blast_id: Mapped[int | None] = mapped_column(ForeignKey("blast.id"))
    station_id: Mapped[int] = mapped_column(ForeignKey("monitor_station.id"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime)
    distance_m: Mapped[float | None] = mapped_column(Float)
    ppv_mm_s: Mapped[float | None] = mapped_column(Float)
    ppv_transverse: Mapped[float | None] = mapped_column(Float)
    ppv_vertical: Mapped[float | None] = mapped_column(Float)
    ppv_longitudinal: Mapped[float | None] = mapped_column(Float)
    dominant_frequency_hz: Mapped[float | None] = mapped_column(Float)
    air_overpressure_db: Mapped[float | None] = mapped_column(Float)
    data_quality: Mapped[str] = mapped_column(String(20))  # VALID | QUESTIONABLE | NO_TRIGGER | INVALID
    quality_notes: Mapped[str | None] = mapped_column(Text)
    limit_ppv_mm_s: Mapped[float | None] = mapped_column(Float)
    compliance: Mapped[str] = mapped_column(String(20))  # COMPLIANT | EXCEEDANCE | NOT_EVALUATED
    waveform_seed: Mapped[int] = mapped_column(Integer, default=0)


# ---------------------------------------------------------------- QSSE (09)


class Inspection(Base):
    __tablename__ = "inspection"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    inspection_type: Mapped[str] = mapped_column(String(30))  # PRE_TASK | PRE_BLAST | PPE | AREA | EQUIPMENT
    blast_id: Mapped[int | None] = mapped_column(ForeignKey("blast.id"))
    area_id: Mapped[int | None] = mapped_column(ForeignKey("area.id"))
    due_date: Mapped[date] = mapped_column(Date)
    inspected_at: Mapped[datetime | None] = mapped_column(DateTime)
    inspector_id: Mapped[int | None] = mapped_column(ForeignKey("personnel.id"))
    status: Mapped[str] = mapped_column(String(20))  # SCHEDULED | COMPLETED | OVERDUE
    findings: Mapped[str | None] = mapped_column(Text)
    items: Mapped[list["ChecklistItem"]] = relationship(back_populates="inspection")


class ChecklistItem(Base):
    __tablename__ = "checklist_item"
    inspection_id: Mapped[int] = mapped_column(ForeignKey("inspection.id"))
    seq: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(String(240))
    result: Mapped[str | None] = mapped_column(String(10))  # YES | NO | NA | None (not recorded)
    comment: Mapped[str | None] = mapped_column(Text)
    inspection: Mapped[Inspection] = relationship(back_populates="items")


class SafetyObservation(Base):
    __tablename__ = "safety_observation"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    obs_type: Mapped[str] = mapped_column(String(20))  # OBSERVATION | HAZARD | NEAR_MISS | INCIDENT | POSITIVE
    description: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime)
    area_id: Mapped[int | None] = mapped_column(ForeignKey("area.id"))
    location_detail: Mapped[str | None] = mapped_column(String(160))
    reported_by_id: Mapped[int | None] = mapped_column(ForeignKey("personnel.id"))
    responsible_id: Mapped[int | None] = mapped_column(ForeignKey("personnel.id"))
    likelihood: Mapped[int] = mapped_column(Integer)  # 1..5
    severity: Mapped[int] = mapped_column(Integer)  # 1..5
    risk_level: Mapped[str] = mapped_column(String(10))  # LOW | MEDIUM | HIGH | CRITICAL
    corrective_action: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))  # OPEN | IN_PROGRESS | CLOSED
    due_date: Mapped[date | None] = mapped_column(Date)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    closure_evidence: Mapped[str | None] = mapped_column(Text)


class Capa(Base):
    __tablename__ = "capa"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    action_type: Mapped[str] = mapped_column(String(15))  # CORRECTIVE | PREVENTIVE
    source_type: Mapped[str] = mapped_column(String(30))  # OBSERVATION | NONCONFORMANCE | DRILLHOLE | VIBRATION | AUDIT | POST_BLAST
    source_ref: Mapped[str | None] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(Text)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("personnel.id"))
    raised_on: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20))  # OPEN | IN_PROGRESS | CLOSED
    closed_on: Mapped[date | None] = mapped_column(Date)
    closure_evidence: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------- post-blast (10)


class PostBlastReview(Base):
    __tablename__ = "post_blast_review"
    blast_id: Mapped[int] = mapped_column(ForeignKey("blast.id"), unique=True)
    stage: Mapped[str] = mapped_column(String(30))
    # DATA_COLLECTION | VERIFICATION | ANALYSIS | INTERPRETATION | IMPROVEMENT_PROPOSAL | DOCUMENTATION | COMPLETED
    due_date: Mapped[date] = mapped_column(Date)
    completed_on: Mapped[date | None] = mapped_column(Date)
    plan_compliance: Mapped[str | None] = mapped_column(Text)
    fragmentation_observation: Mapped[str | None] = mapped_column(Text)
    fragmentation_rating: Mapped[int | None] = mapped_column(Integer)  # 1..5 visual rating
    oversize_observed: Mapped[bool | None] = mapped_column()
    geology_observation: Mapped[str | None] = mapped_column(Text)
    operational_deviations: Mapped[str | None] = mapped_column(Text)
    lessons_learned: Mapped[str | None] = mapped_column(Text)
    improvement_proposal: Mapped[str | None] = mapped_column(Text)
    engineering_review_status: Mapped[str] = mapped_column(String(20), default="NOT_REQUIRED")
    # NOT_REQUIRED | PENDING | REVIEWED
    engineering_reviewer: Mapped[str | None] = mapped_column(String(120))
    prepared_by_id: Mapped[int | None] = mapped_column(ForeignKey("personnel.id"))
