"""Deterministic generator for the fictional "Lac-Boréal Mine" demonstration dataset.

DEMONSTRATION DATA — FICTIONAL SITE.

All names, places, products, values and limits are fictional. Reference limits are
DEMO PLACEHOLDERS and must be replaced with values from authorized documentation.

Planted situations (so the demonstration has something real to find):
  1. Recurring drillhole deviations on bench SP-B275 (Oct–Nov patterns).
  2. Viscometer VISC-02 used after its calibration expired.
  3. Batch of E-100 with out-of-specification viscosity (quarantined, retested).
  4. Recurring density non-conformances on packaged product P-300.
  5. Rising vibration trend at receptor V-03, with one exceedance on 2026-11-24.
  6. Overdue corrective actions and overdue post-blast reviews.
  7. One detonator inventory reconciliation exception (investigated and closed).
  8. Drill D-02 currently down.
"""
from __future__ import annotations

import math
import random
from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from .. import models as m
from ..config import DEMO_TODAY
from ..db import Base
from ..services.templates import DEFAULTS

SEED = 20261204
START = date(2026, 8, 3)  # Monday
HORIZON = DEMO_TODAY + timedelta(days=14)
PLACEHOLDER_SRC = "DEMO PLACEHOLDER — not a company, client or regulatory value. Replace with authorized documentation."


def dt(d: date, h: int = 8, mi: int = 0) -> datetime:
    return datetime.combine(d, time(h, mi))


def daterange(a: date, b: date):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


class Generator:
    def __init__(self, db: Session):
        self.db = db
        self.r = random.Random(SEED)
        self.today = DEMO_TODAY

    # ------------------------------------------------------------ helpers
    def add(self, obj):
        self.db.add(obj)
        return obj

    def flush(self):
        self.db.flush()

    def pick(self, seq):
        return self.r.choice(seq)

    def risk_level(self, likelihood: int, severity: int) -> str:
        s = likelihood * severity
        if s >= 17:
            return "CRITICAL"
        if s >= 10:
            return "HIGH"
        if s >= 5:
            return "MEDIUM"
        return "LOW"

    # ------------------------------------------------------------ run
    def run(self):
        self.reference()
        self.limits_and_targets()
        self.blasting_cycle()
        self.deliveries()
        self.equipment_downtime()
        self.laboratory()
        self.qsse()
        self.db.commit()

    # ------------------------------------------------------------ accounts
    def demo_accounts(self):
        """Demonstration sign-in accounts (one per role). All share BI_DEMO_PASSWORD; replace them in production."""
        from ..config import DEMO_PASSWORD
        from ..services.security import hash_password

        h = hash_password(DEMO_PASSWORD)
        for uname, name, role, pcode in [("admin", "Administrator", "ADMIN", None),
                                         ("jgagnon", "Julie Gagnon", "ENGINEER", "P-02"),
                                         ("eroy", "Émilie Roy", "TECHNICIAN", "P-03"),
                                         ("kbouchard", "Kevin Bouchard", "TECHNICIAN", "P-04"),
                                         ("npelletier", "Nadia Pelletier", "QSSE", "P-06"),
                                         ("iouellet", "Isabelle Ouellet", "VIEWER", "P-14")]:
            self.add(m.AppUser(username=uname, full_name=name, role=role, password_hash=h, must_change_password=False,
                               personnel_id=self.people[pcode].id if pcode else None))
        self.flush()

    # ------------------------------------------------------------ reference
    def reference(self):
        r = self.r
        self.site = self.add(m.Site(code="LBM", name="Lac-Boréal Mine (fictional)", region="Québec, Canada (fictional site)",
                                    client="Boréal Minerals Inc. (fictional client)"))
        self.flush()
        area_defs = [("NP", "North Pit", "OPEN_PIT"), ("SP", "South Pit", "OPEN_PIT"), ("EQ", "East Quarry", "QUARRY")]
        self.areas = {}
        for code, name, t in area_defs:
            self.areas[code] = self.add(m.Area(site_id=self.site.id, code=code, name=name, area_type=t))
        self.flush()
        bench_defs = [("NP", 310, 12, "Granodiorite"), ("NP", 298, 12, "Granodiorite"), ("SP", 287, 11, "Mafic volcanic"),
                      ("SP", 275, 11, "Mafic volcanic (sheared)"), ("EQ", 132, 10, "Granite gneiss"), ("EQ", 122, 10, "Granite gneiss")]
        self.benches = []
        for a, elev, h, rock in bench_defs:
            b = self.add(m.Bench(area_id=self.areas[a].id, code=f"{a}-B{elev}", elevation_m=elev, bench_height_m=h, rock_type=rock))
            self.benches.append(b)
        self.flush()

        people = [
            ("P-01", "Marc-André Tremblay", "Blasting Supervisor", "Certified blaster (fictional cert. QC-BL-1182); Supervisor training"),
            ("P-02", "Julie Gagnon", "Drill & Blast Engineer", "Professional engineer (fictional reg. 5521)"),
            ("P-03", "Émilie Roy", "Mining Technician", "3D scanning; drillhole verification"),
            ("P-04", "Kevin Bouchard", "Mining Technician", "Drillhole verification; vibration monitoring"),
            ("P-05", "Samuel Côté", "Blaster", "Certified blaster (fictional cert. QC-BL-2044)"),
            ("P-06", "Nadia Pelletier", "QSSE Advisor", "OHS coordinator; incident investigation"),
            ("P-07", "Olivier Lavoie", "Laboratory Technician", "Product QC testing"),
            ("P-08", "Sophie Morin", "Laboratory Technician", "Product QC testing; instrument calibration"),
            ("P-09", "David Fortin", "Surveyor / 3D Scanning Technician", "Terrestrial laser scanning; GNSS"),
            ("P-10", "Patrick Gauthier", "Driller", "Production drilling"),
            ("P-11", "Luc Bergeron", "MMU Operator", "Bulk product delivery unit"),
            ("P-12", "Alexandre Girard", "MMU Operator", "Bulk product delivery unit"),
            ("P-13", "Catherine Lefebvre", "Production Planner", "Scheduling; client coordination"),
            ("P-14", "Isabelle Ouellet", "Site Manager", "Client relations; contract management"),
        ]
        self.people = {}
        for code, name, role, q in people:
            self.people[code] = self.add(m.Personnel(code=code, full_name=name, role=role, qualifications=q))
        self.flush()
        self.techs = [self.people["P-03"], self.people["P-04"]]
        self.demo_accounts()
        self.lab_techs = [self.people["P-07"], self.people["P-08"]]

        courses = ["Explosives handling awareness", "Site-specific induction", "Working at heights (bench edges)",
                   "First aid / CPR", "WHMIS 2015", "Ground control awareness"]
        for p in self.people.values():
            for c in r.sample(courses, 4):
                done = START - timedelta(days=r.randint(30, 360))
                self.add(m.TrainingRecord(personnel_id=p.id, course=c, completed_on=done,
                                          expires_on=done + timedelta(days=3 * 365 if c != "First aid / CPR" else 2 * 365),
                                          certificate_ref=f"TR-{p.code}-{r.randint(1000, 9999)}"))
        # planted: one expired, one expiring soon
        self.add(m.TrainingRecord(personnel_id=self.people["P-11"].id, course="First aid / CPR", completed_on=date(2024, 11, 20),
                                  expires_on=date(2026, 11, 20), certificate_ref="TR-P-11-4410"))
        self.add(m.TrainingRecord(personnel_id=self.people["P-04"].id, course="WHMIS 2015", completed_on=date(2023, 12, 18),
                                  expires_on=date(2026, 12, 18), certificate_ref="TR-P-04-2207"))

        eq = [("D-01", "Production drill rig 01", "DRILL"), ("D-02", "Production drill rig 02", "DRILL"),
              ("D-03", "Production drill rig 03", "DRILL"), ("MMU-01", "Mobile manufacturing unit 01", "MMU"),
              ("MMU-02", "Mobile manufacturing unit 02", "MMU"), ("SCN-01", "Terrestrial laser scanner kit", "SCANNER"),
              ("LV-01", "Light vehicle — blasting crew", "VEHICLE"), ("LV-02", "Light vehicle — technicians", "VEHICLE")]
        self.equipment = {}
        for code, name, t in eq:
            self.equipment[code] = self.add(m.Equipment(code=code, name=name, equipment_type=t,
                                                        status="DOWN" if code == "D-02" else "AVAILABLE"))

        inst = [("VISC-01", "Rotational viscometer", "VISCOMETER", "Product laboratory"),
                ("VISC-02", "Rotational viscometer (backup)", "VISCOMETER", "Product laboratory"),
                ("DENS-01", "Density cup and precision balance", "DENSITY", "Product laboratory"),
                ("DENS-02", "Field density cup kit", "DENSITY", "MMU-01"),
                ("FLOW-01", "Flowability test apparatus", "FLOWABILITY", "Product laboratory"),
                ("VOD-01", "Continuous VOD recorder", "VOD", "Technical services"),
                ("NOX-01", "Portable NOx gas analyzer", "NOX", "Technical services"),
                ("SEIS-01", "Blast seismograph 01", "SEISMOGRAPH", "Station V-01"),
                ("SEIS-02", "Blast seismograph 02", "SEISMOGRAPH", "Station V-02"),
                ("SEIS-03", "Blast seismograph 03", "SEISMOGRAPH", "Station V-03"),
                ("SEIS-04", "Blast seismograph 04", "SEISMOGRAPH", "Station V-04"),
                ("TLS-01", "Terrestrial laser scanner", "LASER_SCANNER", "Survey office"),
                ("PRB-01", "Hole depth measuring tape", "DEPTH_PROBE", "Technicians"),
                ("PRB-02", "Hole depth measuring tape", "DEPTH_PROBE", "Technicians"),
                ("DEV-01", "Borehole deviation probe", "DEVIATION_PROBE", "Technicians")]
        self.instruments = {}
        for code, name, t, loc in inst:
            self.instruments[code] = self.add(m.Instrument(code=code, name=name, instrument_type=t,
                                                           serial_number=f"SN-{r.randint(100000, 999999)}", location=loc))
        self.flush()
        for code, ins in self.instruments.items():
            interval = 180 if ins.instrument_type in ("VISCOMETER", "DENSITY", "NOX", "FLOWABILITY") else 365
            last = START - timedelta(days=r.randint(10, 120))
            if code == "VISC-02":  # planted: expires 2026-11-15, not renewed
                last = date(2026, 5, 19)
            if code == "SEIS-04":  # planted: due soon
                last = date(2025, 12, 20)
            self.add(m.Calibration(instrument_id=ins.id, calibrated_on=last, valid_until=last + timedelta(days=interval),
                                   certificate_ref=f"CAL-{code}-{last:%y%m}", performed_by="Accredited calibration lab (fictional)"))
            nxt = last + timedelta(days=interval)
            while nxt <= self.today and code not in ("VISC-02", "SEIS-04"):
                self.add(m.Calibration(instrument_id=ins.id, calibrated_on=nxt - timedelta(days=3),
                                       valid_until=nxt - timedelta(days=3) + timedelta(days=interval),
                                       certificate_ref=f"CAL-{code}-{nxt:%y%m}", performed_by="Accredited calibration lab (fictional)"))
                nxt = nxt - timedelta(days=3) + timedelta(days=interval)

        stations = [("V-01", "Chemin du Lac residence (fictional receptor)", "RECEPTOR", 1850, 900, "SEIS-01"),
                    ("V-02", "Process water pump house", "STRUCTURE", 650, -420, "SEIS-02"),
                    ("V-03", "Rang Nord farm (fictional receptor)", "RECEPTOR", 2400, -300, "SEIS-03"),
                    ("V-04", "North Pit east crest", "PIT_EDGE", 300, 380, "SEIS-04")]
        self.stations = {}
        for code, name, t, x, y, ins in stations:
            self.stations[code] = self.add(m.MonitorStation(code=code, name=name, station_type=t, x=x, y=y,
                                                            instrument_id=self.instruments[ins].id))
        self.add(m.AppSetting(key="risk_matrix", value={
            "likelihood": ["Rare", "Unlikely", "Possible", "Likely", "Almost certain"],
            "severity": ["Negligible", "Minor", "Moderate", "Major", "Catastrophic"],
            "levels": [{"name": "LOW", "max_score": 4}, {"name": "MEDIUM", "max_score": 9},
                       {"name": "HIGH", "max_score": 16}, {"name": "CRITICAL", "max_score": 25}],
            "source_document": PLACEHOLDER_SRC}))
        self.add(m.AppSetting(key="site", value={"name": self.site.name, "client": self.site.client,
                                                  "disclaimer": "DEMONSTRATION DATA — FICTIONAL SITE"}))
        self.flush()

    def limits_and_targets(self):
        eff = date(2026, 1, 1)
        L = [
            ("VISCOSITY", "E-100", 18000, 42000, "mPa·s"),
            ("VISCOSITY", "P-300", 25000, 60000, "mPa·s"),
            ("DENSITY", "E-100", 1.30, 1.40, "g/cm³"),
            ("DENSITY", "G-200", 1.10, 1.25, "g/cm³"),
            ("DENSITY", "P-300", 1.15, 1.25, "g/cm³"),
            ("FLOWABILITY", "E-100", None, 45.0, "s"),
            ("VOD", "G-200", 4500, None, "m/s"),
            ("NOX", "*", None, 40.0, "ppm"),
            ("PPV", "*", None, 10.0, "mm/s"),
            ("DEPTH_TOL", "*", -0.30, 0.30, "m"),
            ("DEVIATION_TOL", "*", None, 0.50, "m"),
            ("FACE_TOL", "*", -0.50, 0.50, "m"),
            ("FRONT_DIST_MIN", "*", 2.50, None, "m"),
            ("TOE_DIST_MAX", "*", None, 7.20, "m"),
        ]
        self.limits = {}
        for p, scope, lo, hi, u in L:
            self.limits[(p, scope)] = self.add(m.ReferenceLimit(parameter=p, scope=scope, min_value=lo, max_value=hi, unit=u,
                                                                source_document=PLACEHOLDER_SRC, effective_from=eff,
                                                                owner="To be confirmed (authorized engineer / QSSE)"))
        targets = [("schedule_adherence", 90, "HIGHER"), ("activity_completion", 95, "HIGHER"),
                   ("drillhole_inspection_compliance", 98, "HIGHER"), ("drillhole_deviation_rate", 5, "LOWER"),
                   ("survey_completion", 95, "HIGHER"), ("product_qaqc_compliance", 98, "HIGHER"),
                   ("lab_testing_completion", 95, "HIGHER"), ("vibration_monitoring_compliance", 100, "HIGHER"),
                   ("post_blast_report_completion", 90, "HIGHER"), ("capa_closure_rate", 85, "HIGHER"),
                   ("equipment_availability", 85, "HIGHER"), ("operational_downtime_h", 40, "LOWER"),
                   ("documentation_completeness", 95, "HIGHER")]
        for k, t, d in targets:
            self.add(m.KpiTarget(kpi_key=k, target=t, direction=d))
        self.flush()

    # ------------------------------------------------------------ blasting cycle
    def blast_dates(self):
        out = []
        for d in daterange(START, HORIZON):
            if d.weekday() in (1, 4):  # Tuesday / Friday
                out.append(d)
        return out

    def blasting_cycle(self):
        r = self.r
        self.blasts = []
        self.fired = []
        self._last_hist = {}
        self._exceed_blasts = set()
        self.capa_seq = 0
        self.obs_seq = 0
        dates = self.blast_dates()
        delay_causes = {
            "WEATHER": ["Freezing rain — bench access suspended", "Lightning within exclusion radius — activities paused",
                        "Heavy fog — visibility below site requirement"],
            "EQUIPMENT": ["Drill D-02 hydraulic hose failure", "MMU-02 pump fault", "Scanner battery failure — rescan required"],
            "PRODUCT_SUPPLY": ["Bulk product delivery arrived late", "Partial delivery — balance next day"],
            "CLIENT_ACCESS": ["Client haul road maintenance — access restricted", "Client shovel relocation in progress"],
            "REDRILL": ["Holes collapsed — redrill required before loading", "Short holes found at verification — redrill"],
            "AUTHORIZATION_WAIT": ["Waiting for client blast clearance window"],
            "WILDLIFE_EXCLUSION": ["Moose observed inside exclusion zone — blast delayed until clear"],
        }
        for i, d in enumerate(dates):
            bench = self.benches[i % len(self.benches)]
            area = next(a for a in self.areas.values() if a.id == bench.area_id)
            code_n = 401 + i
            rows, cols = r.randint(3, 5), r.randint(8, 12)
            burden, spacing, sub = 3.5, 4.0, 1.0
            depth = bench.bench_height_m + sub
            forecast_t = round(rows * cols * burden * spacing * bench.bench_height_m * 2.7, -1)
            past = d < self.today
            fired_today = d == self.today
            wo_status = "COMPLETED" if d < self.today - timedelta(days=6) else ("IN_PROGRESS" if d <= self.today + timedelta(days=5) else "OPEN")
            wo = self.add(m.WorkOrder(code=f"WO-26-{code_n:04d}", title=f"Production blast {bench.code} — pattern {code_n}",
                                      area_id=area.id, wo_type="BLAST", status=wo_status,
                                      engineering_forecast_ref=f"ENG-FC-{d:%Y-%W}",
                                      planned_start=d - timedelta(days=5), planned_end=d + timedelta(days=5),
                                      actual_start=(d - timedelta(days=5)) if d - timedelta(days=5) <= self.today else None,
                                      actual_end=(d + timedelta(days=5 + r.choice([0, 0, 0, 1, 2]))) if wo_status == "COMPLETED" else None,
                                      forecast_tonnes=forecast_t,
                                      actual_tonnes=round(forecast_t * r.gauss(0.985, 0.035), -1) if past else None))
            self.flush()
            pattern = self.add(m.DrillPattern(code=f"PT-{bench.code}-{code_n}", bench_id=bench.id,
                                              design_document_ref=f"DBP-{code_n}-RevA (approved design — fictional)",
                                              approved_by="J. Gagnon, Eng. (fictional)", hole_count=rows * cols,
                                              hole_diameter_mm=115.0 if area.code == "EQ" else 140.0,
                                              drilled_on=(d - timedelta(days=5)) if d - timedelta(days=5) <= self.today else None,
                                              origin_x=1000 + 120 * (i % 6) + r.uniform(-20, 20), origin_y=500 + 80 * (i % 3)))
            self.flush()
            self.add(m.ApprovedLoadingRecord(pattern_id=pattern.id, document_ref=f"ALP-{code_n}", revision="A",
                                             approved_by="J. Gagnon, Eng. (fictional)", approved_on=d - timedelta(days=6),
                                             notes="Approved loading parameters held in the referenced engineering document. "
                                                   "Not reproduced or calculated by this application."))
            planted_dev = bench.code == "SP-B275" and d >= date(2026, 10, 1)
            holes = []
            for rr in range(rows):
                for cc in range(cols):
                    h = self.add(m.Drillhole(pattern_id=pattern.id, hole_code=f"R{rr + 1}-{cc + 1:02d}", row_no=rr + 1, col_no=cc + 1,
                                             planned_x=round(pattern.origin_x + cc * spacing + (spacing / 2 if rr % 2 else 0), 2),
                                             planned_y=round(pattern.origin_y + rr * burden, 2), planned_z=bench.elevation_m,
                                             planned_depth_m=depth))
                    holes.append(h)
            self.flush()

            # ---- drillhole measurements
            meas_day = d - timedelta(days=3)
            if d > self.today and pattern.drilled_on is not None:
                meas_day = min(meas_day, self.today)  # verification under way today
            if meas_day <= self.today:
                fraction = 1.0
                if d > self.today:  # blast still in preparation
                    fraction = 0.62
                elif d < self.today and r.random() < 0.18:
                    fraction = r.uniform(0.85, 0.97)
                for h in holes:
                    if r.random() > fraction:
                        continue
                    if planted_dev:
                        dd = r.gauss(-0.32, 0.22)
                        dev = abs(r.gauss(0.42, 0.18))
                    else:
                        dd = r.gauss(-0.04, 0.13)
                        dev = abs(r.gauss(0.18, 0.12))
                    water = r.random() < (0.25 if area.code == "SP" else 0.08)
                    cond = "OPEN"
                    if planted_dev and r.random() < 0.18:
                        cond = "PARTIALLY_BLOCKED"
                    out = abs(dd) > 0.30 or dev > 0.50
                    status = "OUT_OF_TOLERANCE" if out else "WITHIN_TOLERANCE"
                    note = None
                    if out and dd < -0.6:
                        status, note = "REDRILL_REQUIRED", "Short hole — redrill requested to driller"
                    elif out and r.random() < 0.4 and past:
                        status, note = "ACCEPTED_BY_ENGINEER", "Deviation reviewed and accepted by drill & blast engineer"
                    tech = self.pick(self.techs)
                    self.add(m.DrillholeMeasurement(drillhole_id=h.id, measured_at=dt(meas_day, r.randint(7, 15), r.randint(0, 59)),
                                                    technician_id=tech.id,
                                                    instrument_id=self.instruments[self.pick(["PRB-01", "PRB-02"])].id,
                                                    measured_depth_m=round(depth + dd, 2), collar_offset_m=round(abs(r.gauss(0.08, 0.06)), 2),
                                                    toe_deviation_m=round(dev, 2), water_present=water, hole_condition=cond,
                                                    inspection_status=status, notes=note))
            # ---- blast record
            if d < self.today - timedelta(days=10):
                status = "CLOSED"
            elif d < self.today - timedelta(days=3):
                status = "COMPLETED"
            elif d < self.today:
                status = "AWAITING_VERIFICATION"
            elif fired_today:
                status = "AUTHORIZED"
            elif d <= self.today + timedelta(days=4):
                status = "IN_PREPARATION"
            else:
                status = "PLANNED"
            fired_at = dt(d, 12, r.choice([0, 5, 10, 30])) if past else None
            authorized = past or fired_today
            blast = self.add(m.Blast(code=f"BL-26-{code_n:04d}", work_order_id=wo.id, bench_id=bench.id, pattern_id=pattern.id,
                                     approved_plan_ref=f"DBP-{code_n}-RevA", planned_date=d, fired_at=fired_at, status=status,
                                     supervisor_id=self.people["P-01"].id, blaster_id=self.people[self.pick(["P-01", "P-05"])].id,
                                     authorization_ref=f"AUTH-{code_n}-{d:%m%d}" if authorized else None,
                                     authorized_by="Site blasting authority (per company procedure)" if authorized else None,
                                     authorized_role="Blaster in charge / client clearance" if authorized else None,
                                     authorized_at=dt(d, 7, 40) if authorized else None,
                                     equipment_codes=f"{self.pick(['D-01', 'D-02', 'D-03'])}, {self.pick(['MMU-01', 'MMU-02'])}",
                                     rock_tonnes_forecast=forecast_t,
                                     closed_at=dt(d + timedelta(days=9), 16) if status == "CLOSED" else None))
            self.flush()
            self.blasts.append((blast, wo, pattern, bench, area, holes, d))
            if past:
                self.fired.append((blast, wo, pattern, bench, area, holes, d))
            self.status_history(blast, d, status)
            self.checkpoints(blast, d, status)
            self.schedule(wo, d, delay_causes, planted_dev)
            self.surveys(blast, bench, area, d, i)
            if past or fired_today:
                self.inventory(blast, d, len(holes), returns=past)
            if past or fired_today:
                self.detonators(blast, d, len(holes), i)
            if past:
                self.vibration(blast, bench, area, d, i)
                self.post_blast(blast, d, planted_dev, bench)
            self.pre_blast_inspection(blast, area, d, status)
        # drillhole CAPA for the recurring deviation
        self.capa("CORRECTIVE", "DRILLHOLE", "PT-SP-B275-*", "Recurring short holes and toe deviation on bench SP-B275. "
                  "Review collaring practice and rod guide wear with driller; confirm sheared zone conditions with engineering.",
                  "P-02", date(2026, 11, 13), date(2026, 11, 27), "IN_PROGRESS")

    def status_history(self, blast, d, final):
        order = ["PLANNED", "IN_PREPARATION", "UNDER_INSPECTION", "AUTHORIZED", "IN_PROGRESS", "AWAITING_VERIFICATION", "COMPLETED", "CLOSED"]
        offsets = [(-7, 9), (-5, 7), (-1, 15), (0, 7), (0, 11), (0, 13), (3, 10), (9, 16)]
        prev = None
        for st, (od, hh) in zip(order, offsets):
            note = None
            if st == "AUTHORIZED":
                note = "Authorization issued externally under company procedure; reference recorded."
            self._last_hist[blast.id] = self.add(m.BlastStatusHistory(blast_id=blast.id, from_status=prev, to_status=st, changed_at=dt(d + timedelta(days=od), hh, 40 if st == "AUTHORIZED" else 0),
                                          changed_by="M.-A. Tremblay" if st in ("AUTHORIZED", "IN_PROGRESS") else "É. Roy", note=note))
            prev = st
            if st == final:
                break

    CHECKPOINTS = [tuple(x) for x in DEFAULTS["blast_checkpoints"]]

    def checkpoints(self, blast, d, status):
        done_stages = {"PLANNED": set(), "IN_PREPARATION": {"PREPARATION_PARTIAL"},
                       "AUTHORIZED": {"PREPARATION", "LOADING", "PRE_BLAST"}}
        for idx, (stage, name) in enumerate(self.CHECKPOINTS):
            if status in done_stages:
                ds = done_stages[status]
                completed = stage in ds or ("PREPARATION_PARTIAL" in ds and stage == "PREPARATION" and idx in (0, 3))
            else:
                completed = True
                if status == "AWAITING_VERIFICATION" and stage == "POST_BLAST" and idx >= 13:
                    completed = False
            when = {"PREPARATION": -3, "LOADING": 0, "PRE_BLAST": 0, "POST_BLAST": 1}[stage]
            self.add(m.BlastCheckpoint(blast_id=blast.id, stage=stage, name=name, required=True, completed=completed,
                                       completed_by=self.pick(["É. Roy", "K. Bouchard", "M.-A. Tremblay"]) if completed else None,
                                       completed_at=dt(d + timedelta(days=when), 9 + idx % 6) if completed else None,
                                       evidence_ref=f"DOC-{blast.code}-{idx + 1:02d}" if completed else None))

    def schedule(self, wo, d, causes, planted_dev):
        r = self.r
        acts = [("DRILLING", -5, "P-10", "D-01/D-03"), ("FACE_SURVEY", -4, "P-09", "TLS-01"),
                ("HOLE_VERIFICATION", -3, "P-03", "PRB-01, DEV-01"), ("LOADING", 0, "P-01", "MMU-01"),
                ("BLAST", 0, "P-01", "Blasting crew"), ("POST_BLAST_SURVEY", 1, "P-09", "TLS-01"),
                ("POST_BLAST_REVIEW", 5, "P-04", "—")]
        for act, off, resp, res in acts:
            planned = d + timedelta(days=off)
            slip = 0
            if planted_dev and act == "HOLE_VERIFICATION":
                slip = 1
            elif r.random() < 0.12:
                slip = r.choice([1, 1, 2])
            actual = planned + timedelta(days=slip)
            if actual > self.today:
                status, actual_v = ("DELAYED" if planned < self.today else "PLANNED"), None
                if planned == self.today or (planned < self.today and slip == 0):
                    status = "IN_PROGRESS"
            else:
                status, actual_v = "DONE", actual
            if act == "BLAST" and planned == self.today:
                status, actual_v = "PLANNED", None  # firing window later today
            si = self.add(m.ScheduleItem(work_order_id=wo.id, activity=act, planned_date=planned, actual_date=actual_v,
                                         status=status, resources=res, responsible_id=self.people[resp].id))
            if slip:
                self.flush()
                weights = {"WEATHER": 4, "EQUIPMENT": 3, "PRODUCT_SUPPLY": 2, "CLIENT_ACCESS": 2, "REDRILL": 1,
                           "AUTHORIZATION_WAIT": 1, "WILDLIFE_EXCLUSION": 1}
                cat = "REDRILL" if (planted_dev and act == "HOLE_VERIFICATION") else r.choices(list(weights), list(weights.values()))[0]
                desc = self.pick(causes[cat])
                self.add(m.ScheduleChange(schedule_item_id=si.id, changed_at=dt(min(planned, self.today), 7, 30), old_date=planned,
                                          new_date=planned + timedelta(days=slip), cause_category=cat, cause=desc,
                                          changed_by="C. Lefebvre"))
                if planned <= self.today:
                    self.add(m.DelayEvent(work_order_id=wo.id, occurred_on=planned, category=cat,
                                          hours=round(r.uniform(2, 6) + 8 * (slip - 1), 1), description=desc))

    def surveys(self, blast, bench, area, d, i):
        r = self.r
        pre_day = d - timedelta(days=4)
        if pre_day <= self.today:
            rejected = i == 9
            self.add(m.Survey(code=f"SV-{blast.code[3:]}-PRE", area_id=area.id, bench_id=bench.id, blast_id=blast.id,
                              survey_type="FACE_PROFILE", surveyed_at=dt(pre_day, 9, 30), instrument_id=self.instruments["TLS-01"].id,
                              operator_id=self.people[self.pick(["P-09", "P-03"])].id, point_count=r.randint(850_000, 2_400_000),
                              point_spacing_mm=r.choice([20, 25, 30]), registration_error_mm=round(r.uniform(18, 34) if rejected else r.uniform(3, 9), 1),
                              file_format="LAS", quality_status="REJECTED" if rejected else "ACCEPTED",
                              quality_notes="Registration error above acceptance — rescanned next day" if rejected else None))
            if rejected:
                self.add(m.Survey(code=f"SV-{blast.code[3:]}-PRE-R1", area_id=area.id, bench_id=bench.id, blast_id=blast.id,
                                  survey_type="FACE_PROFILE", surveyed_at=dt(pre_day + timedelta(days=1), 8, 45),
                                  instrument_id=self.instruments["TLS-01"].id, operator_id=self.people["P-09"].id,
                                  point_count=r.randint(900_000, 2_000_000), point_spacing_mm=25,
                                  registration_error_mm=round(r.uniform(3, 7), 1), file_format="LAS", quality_status="ACCEPTED"))
        post_day = d + timedelta(days=1)
        if post_day <= self.today and i not in (5, 17) and d != date(2026, 11, 20):  # planted: blasts without post-blast survey
            self.add(m.Survey(code=f"SV-{blast.code[3:]}-POST", area_id=area.id, bench_id=bench.id, blast_id=blast.id,
                              survey_type="POST_BLAST", surveyed_at=dt(post_day, 10, 0), instrument_id=self.instruments["TLS-01"].id,
                              operator_id=self.people["P-09"].id, point_count=r.randint(1_200_000, 3_100_000), point_spacing_mm=30,
                              registration_error_mm=round(r.uniform(3, 9), 1), file_format="LAS",
                              quality_status="PENDING" if post_day >= self.today - timedelta(days=1) else "ACCEPTED"))

    def inventory(self, blast, d, n_holes, returns=True):
        r = self.r
        received = round(n_holes * r.uniform(0.095, 0.12), 2)
        returned = round(received * r.uniform(0.0, 0.04), 2)
        used = round(received - returned, 2)
        moves = (("RECEIVED", received, 7), ("USED", used, 11), ("RETURNED", returned, 14))
        for t, q, h in (moves if returns else moves[:2]):
            self.add(m.InventoryMovement(blast_id=blast.id, product_name="G-200 Gassed bulk emulsion (fictional)", movement_type=t,
                                         quantity=q, unit="t", recorded_at=dt(d, h), recorded_by="L. Bergeron",
                                         document_ref=f"INV-{blast.code}-{t[:3]}"))

    def detonators(self, blast, d, n_holes, i):
        issued = n_holes + 4
        used = n_holes if blast.status not in ("AUTHORIZED",) else None
        returned = 4 if used is not None else None
        planted = i == 21
        if planted:
            returned = 3
        rec = self.add(m.DetonatorRecord(blast_id=blast.id, inventory_lot_ref=f"LOT-EDT-{2600 + i // 4}", units_issued=issued,
                                         units_used=used, units_returned=returned, equipment_ref=f"BLB-0{1 + i % 2} (asset tag)",
                                         authorized_personnel="M.-A. Tremblay; S. Côté", procedure_ref="PRO-EDT-001 (company procedure — fictional ref.)",
                                         inspection_status="DONE" if used is not None else "PENDING",
                                         documentation_status="COMPLETE" if (used is not None and blast.status in ("CLOSED", "COMPLETED")) else "INCOMPLETE",
                                         verified_by="N. Pelletier" if blast.status in ("CLOSED", "COMPLETED") else None,
                                         verified_at=dt(d + timedelta(days=2), 10) if blast.status in ("CLOSED", "COMPLETED") else None))
        if planted:
            self.flush()
            self.add(m.TraceabilityException(detonator_record_id=rec.id, raised_at=dt(d, 15), severity="HIGH", status="CLOSED",
                                             description="Reconciliation difference of 1 unit (issued − used − returned ≠ 0).",
                                             resolution="Unit located in magazine return box; magazine log corrected and countersigned. "
                                                        "Reported to QSSE per procedure."))

    def vibration(self, blast, bench, area, d, i):
        r = self.r
        bx = blast.pattern_id and (1000 + 120 * (i % 6))
        by = 500 + 80 * (i % 3)
        for code, st in self.stations.items():
            if code == "V-04" and area.code != "NP":
                continue
            dist = math.hypot(st.x - bx, st.y - by) + r.uniform(-60, 60)
            station_mean = {"V-01": 2.4, "V-02": 1.5, "V-03": 2.5, "V-04": 3.6}[code]
            ppv = station_mean * (900 / max(dist, 200)) ** 0.35 * math.exp(r.gauss(0, 0.25))
            if code == "V-03":
                days = (d - date(2026, 10, 1)).days
                if days > 0:
                    ppv *= 1 + days * 0.034  # planted rising trend
                ppv = min(ppv, 9.3)
                if d == date(2026, 11, 24):
                    ppv = 10.8  # planted single exceedance
            ppv = round(min(ppv, 10.8 if code == "V-03" else 8.9), 2)
            quality, notes = "VALID", None
            if code == "V-02" and r.random() < 0.12:
                quality, notes = "QUESTIONABLE", "Geophone coupling suspect (sandbag displaced)"
            if r.random() < 0.03:
                quality, notes = "NO_TRIGGER", "Instrument did not trigger — trigger level review requested"
            limit = 10.0
            if quality in ("VALID", "QUESTIONABLE"):
                compliance = "EXCEEDANCE" if ppv > limit else "COMPLIANT"
                if quality == "QUESTIONABLE":
                    compliance = "NOT_EVALUATED"
            else:
                compliance, ppv = "NOT_EVALUATED", None
            comps = None
            if ppv:
                comps = sorted([ppv, ppv * r.uniform(0.5, 0.9), ppv * r.uniform(0.4, 0.85)], reverse=True)
                r.shuffle(comps)
            self.add(m.VibrationEvent(code=f"VE-{blast.code[3:]}-{code}", blast_id=blast.id, station_id=st.id,
                                      instrument_id=st.instrument_id, recorded_at=blast.fired_at, distance_m=round(dist, 0),
                                      ppv_mm_s=ppv, ppv_transverse=round(comps[0], 2) if comps else None,
                                      ppv_vertical=round(comps[1], 2) if comps else None,
                                      ppv_longitudinal=round(comps[2], 2) if comps else None,
                                      dominant_frequency_hz=round(r.uniform(9, 45), 1) if ppv else None,
                                      air_overpressure_db=round(r.uniform(104, 124), 1) if ppv else None,
                                      data_quality=quality, quality_notes=notes, limit_ppv_mm_s=limit, compliance=compliance,
                                      waveform_seed=r.randint(1, 10 ** 6)))
            if compliance == "EXCEEDANCE":
                self._exceed_blasts.add(blast.id)
                self.capa("CORRECTIVE", "VIBRATION", f"VE-{blast.code[3:]}-{code}",
                          "PPV above configured reference value at receptor V-03. Notify client and QSSE per procedure; "
                          "engineering review of blast design for eastern benches requested.",
                          "P-02", d, d + timedelta(days=10), "IN_PROGRESS")
                self.observation("HAZARD", f"Vibration reference value exceeded at V-03 ({ppv} mm/s) during {blast.code}.",
                                 d, area, "P-02", 3, 3, "OPEN", "Engineering review of eastern bench blasts; client notified.")

    def post_blast(self, blast, d, planted_dev, bench):
        r = self.r
        due = d + timedelta(days=7)
        age = (self.today - d).days
        if age >= 12:
            stage, completed = "COMPLETED", due - timedelta(days=r.randint(0, 3))
            if r.random() < 0.08:
                completed = due + timedelta(days=r.randint(1, 4))  # some late completions
        elif age >= 8:
            stage, completed = "INTERPRETATION", None  # planted overdue
        elif age >= 3:
            stage, completed = r.choice(["VERIFICATION", "ANALYSIS"]), None
        else:
            stage, completed = "DATA_COLLECTION", None
        if blast.status == "CLOSED" and stage != "COMPLETED":
            # a blast cannot be closed while its post-blast review is open
            blast.status, blast.closed_at = "COMPLETED", None
            last = self._last_hist.get(blast.id)
            if last is not None and last.to_status == "CLOSED":
                self.db.expunge(last)
        rating = r.choice([3, 4, 4, 4, 5]) if not planted_dev else r.choice([2, 3])
        frag = {5: "Uniform fragmentation; no visible oversize.", 4: "Good fragmentation; minor oversize at back row.",
                3: "Acceptable fragmentation; some oversize along the crest.", 2: "Coarse fragmentation in the toe zone; oversize requiring secondary breakage."}[rating]
        proposal = None
        review = "NOT_REQUIRED"
        if planted_dev:
            proposal = "Propose to engineering: review collaring and hole verification timing on SP-B275 sheared zone; consider re-verification closer to loading."
            review = "PENDING" if stage != "COMPLETED" or r.random() < 0.5 else "REVIEWED"
        self.add(m.PostBlastReview(blast_id=blast.id, stage=stage, due_date=due, completed_on=completed,
                                   plan_compliance="Executed per approved plan reference; deviations listed below." if stage != "DATA_COLLECTION" else None,
                                   fragmentation_observation=frag if stage != "DATA_COLLECTION" else None,
                                   fragmentation_rating=rating if stage != "DATA_COLLECTION" else None,
                                   oversize_observed=rating <= 3,
                                   geology_observation=f"{bench.rock_type}; " + ("water-bearing sheared zone along east wall." if planted_dev else "competent rock mass."),
                                   operational_deviations=("Short holes / toe deviation recorded at verification (see drillhole report)." if planted_dev else
                                                           ("PPV above the configured reference value at receptor V-03; client and QSSE notified (CAPA open)."
                                                            if blast.id in self._exceed_blasts else "None significant.")),
                                   lessons_learned=("Re-verify holes in sheared zone within 24 h of loading." if planted_dev else None),
                                   improvement_proposal=proposal, engineering_review_status=review,
                                   engineering_reviewer="J. Gagnon, Eng. (fictional)" if review == "REVIEWED" else None,
                                   prepared_by_id=self.pick(self.techs).id))

    PRE_BLAST_ITEMS = DEFAULTS["pre_blast_checklist"]

    def pre_blast_inspection(self, blast, area, d, status):
        done = status not in ("PLANNED", "IN_PREPARATION")
        insp = self.add(m.Inspection(code=f"IN-PB-{blast.code[3:]}", inspection_type="PRE_BLAST", blast_id=blast.id, area_id=area.id,
                                     due_date=d, inspected_at=dt(d, 10, 15) if done else None,
                                     inspector_id=blast.blaster_id if done else None, status="COMPLETED" if done else "SCHEDULED"))
        self.flush()
        for k, t in enumerate(self.PRE_BLAST_ITEMS):
            self.add(m.ChecklistItem(inspection_id=insp.id, seq=k + 1, text=t, result="YES" if done else None))

    # ------------------------------------------------------------ deliveries & equipment
    def deliveries(self):
        r = self.r
        n = 0
        for d in daterange(START, HORIZON):
            if d.weekday() not in (0, 3):
                continue
            n += 1
            planned = round(r.uniform(16, 24), 1)
            dest = self.areas[self.pick(["NP", "SP", "EQ"])]
            if d > self.today:
                status, actual, qty = "SCHEDULED", None, None
            else:
                late = r.random() < 0.12 or d == date(2026, 11, 19)
                partial = r.random() < 0.07
                actual = d + timedelta(days=1) if late else d
                qty = round(planned * (r.uniform(0.6, 0.85) if partial else r.uniform(0.98, 1.0)), 1)
                status = "PARTIAL" if partial else ("LATE" if late else "DELIVERED")
            self.add(m.Delivery(code=f"DL-26-{n:03d}", product_name=self.pick(["E-100 Bulk emulsion matrix (fictional)"] * 3 + ["P-300 Packaged emulsion (fictional)"]),
                                destination_area_id=dest.id, planned_date=d, actual_date=actual, planned_qty=planned,
                                delivered_qty=qty, status=status, document_ref=f"BOL-{n:05d}" if actual else None))

    def equipment_downtime(self):
        r = self.r
        causes = {"DRILL": ["Hydraulic hose failure", "Bit changer fault", "Compressor overheating", "Planned 500 h service"],
                  "MMU": ["Product pump fault", "Hose reel leak", "Planned inspection"],
                  "SCANNER": ["Battery failure", "Annual calibration"], "VEHICLE": ["Flat tire", "Planned service"]}
        for eq in self.equipment.values():
            n = {"DRILL": 7, "MMU": 4, "SCANNER": 2, "VEHICLE": 2}[eq.equipment_type]
            for _ in range(n):
                d = START + timedelta(days=r.randint(0, (self.today - START).days - 3))
                c = self.pick(causes[eq.equipment_type])
                cat = "PLANNED_MAINTENANCE" if c.startswith(("Planned", "Annual")) else "BREAKDOWN"
                self.add(m.EquipmentDowntime(equipment_id=eq.id, started_at=dt(d, r.randint(6, 16)), hours=round(r.uniform(2, 14), 1),
                                             cause=c, category=cat))
        self.add(m.EquipmentDowntime(equipment_id=self.equipment["D-02"].id, started_at=dt(self.today - timedelta(days=1), 14),
                                     hours=26.0, cause="Hydraulic leak — main boom cylinder (ongoing)", category="BREAKDOWN"))

    # ------------------------------------------------------------ laboratory
    def laboratory(self):
        r = self.r
        self.test_seq = 0
        self.nc_seq = 0
        products = {"E-100": "E-100 Bulk emulsion matrix (fictional)", "G-200": "G-200 Gassed bulk emulsion (fictional)",
                    "P-300": "P-300 Packaged emulsion (fictional)"}
        bseq = 0
        for d in daterange(START, self.today):
            if d.weekday() >= 5:
                continue
            # E-100 matrix batch every working day except Wednesday
            if d.weekday() != 2:
                bseq += 1
                b = self.add(m.ProductBatch(code=f"E100-{d:%y%m%d}", product_code="E-100", product_name=products["E-100"],
                                            produced_on=d, quantity=round(r.uniform(18, 26), 1), status="RELEASED"))
                self.flush()
                visc_instr = "VISC-02" if (d >= date(2026, 11, 16) and d.weekday() in (0, 3)) else "VISC-01"
                v = r.gauss(29500, 3800)
                if d == date(2026, 11, 20):
                    v = 47800  # planted OOS
                t = self.lab_test(b, None, "VISCOSITY", visc_instr, d, round(v, -1), "mPa·s", ("VISCOSITY", "E-100"),
                                  "Spindle/speed per lab procedure LAB-PR-01 (fictional); sample at 25 °C", 25.0)
                if t.result == "FAIL":
                    b.status = "QUARANTINE"
                    nc = self.nc(t, d, "E-100 viscosity above configured specification. Batch quarantined; retest ordered.", "RETEST")
                    rt = self.lab_test(b, None, "VISCOSITY", "VISC-01", d + timedelta(days=1), 40100, "mPa·s", ("VISCOSITY", "E-100"),
                                       "Retest — fresh sample, VISC-01", 25.0)
                    if rt.result == "PASS":
                        b.status = "RELEASED"
                        nc.status = "CLOSED"
                    self.capa("CORRECTIVE", "NONCONFORMANCE", nc.code, "Investigate E-100 emulsification parameters for batch "
                              f"{b.code} with production; confirm retest result and release decision by QC lead.", "P-08", d,
                              d + timedelta(days=7), "CLOSED", closed=d + timedelta(days=5),
                              evidence="Retest PASS on VISC-01; production log reviewed; batch released by QC lead.")
                self.lab_test(b, None, "DENSITY", "DENS-01", d, round(r.gauss(1.355, 0.012), 3), "g/cm³", ("DENSITY", "E-100"),
                              "Cup method, 25 °C", 25.0)
                if d.weekday() == 0:
                    self.lab_test(b, None, "FLOWABILITY", "FLOW-01", d, round(r.gauss(31, 4.5), 1), "s", ("FLOWABILITY", "E-100"),
                                  "Funnel flow time per LAB-PR-04 (fictional); sample at 20 °C", 20.0)
            # P-300 packaged product weekly (Thursday)
            if d.weekday() == 3:
                b = self.add(m.ProductBatch(code=f"P300-{d:%y%m%d}", product_code="P-300", product_name=products["P-300"],
                                            produced_on=d, quantity=round(r.uniform(4, 7), 1), status="RELEASED"))
                self.flush()
                dens = r.gauss(1.20, 0.015)
                if d >= date(2026, 10, 15) and r.random() < 0.6:
                    dens = r.gauss(1.262, 0.008)  # planted recurring NC
                t = self.lab_test(b, None, "DENSITY", "DENS-01", d, round(dens, 3), "g/cm³", ("DENSITY", "P-300"), "Cartridge density, 20 °C", 20.0)
                self.lab_test(b, None, "VISCOSITY", "VISC-01", d, round(r.gauss(41000, 5000), -1), "mPa·s", ("VISCOSITY", "P-300"),
                              "Spindle/speed per LAB-PR-01 (fictional); 25 °C", 25.0)
                if t.result == "FAIL":
                    b.status = "QUARANTINE"
                    is_open = d > self.today - timedelta(days=21)
                    self.nc(t, d, "P-300 cartridge density above configured specification. Batch quarantined pending disposition.",
                            "QUARANTINE" if is_open else "REJECT", status="OPEN" if is_open else "CLOSED")
                    if not is_open:
                        b.status = "REJECTED"
        # G-200 field density at each blast (cup test on MMU), VOD and NOx tests
        for blast, wo, pattern, bench, area, holes, d in self.fired:
            self.lab_test(None, blast, "DENSITY", "DENS-02", d, round(r.gauss(1.17, 0.025), 3), "g/cm³", ("DENSITY", "G-200"),
                          "Field cup density after gassing, sampled at MMU", None)
        vod_blasts = self.fired[2::4]
        for blast, wo, pattern, bench, area, holes, d in vod_blasts:
            q = "VALID" if r.random() > 0.15 else "QUESTIONABLE"
            self.lab_test(None, blast, "VOD", "VOD-01", d, round(r.gauss(5250, 260), -1), "m/s", ("VOD", "G-200"),
                          "In-hole continuous resistance method; approved test plan TST-VOD-26 (fictional)", None,
                          quality=q, approved_ref="TST-VOD-26")
        for blast, wo, pattern, bench, area, holes, d in self.fired[1::5]:
            self.lab_test(None, blast, "NOX", "NOX-01", d, round(abs(r.gauss(14, 6)), 1), "ppm", ("NOX", "*"),
                          "Post-blast fume measurement at muckpile edge after re-entry clearance", None, approved_ref="TST-NOX-26")

    def lab_test(self, batch, blast, ttype, instr_code, d, value, unit, limit_key, cond, temp, quality="VALID", approved_ref=None):
        self.test_seq += 1
        instr = self.instruments[instr_code]
        cal_ok = any(c.calibrated_on <= d <= c.valid_until for c in instr.calibrations) if instr.calibrations else True
        lim = self.limits.get(limit_key)
        if not cal_ok:
            quality = "QUESTIONABLE"
        result = "NOT_EVALUATED"
        if quality == "VALID" and lim is not None and value is not None:
            ok = (lim.min_value is None or value >= lim.min_value) and (lim.max_value is None or value <= lim.max_value)
            result = "PASS" if ok else "FAIL"
        t = self.add(m.LabTest(code=f"LT-26-{self.test_seq:05d}", batch_id=batch.id if batch else None, blast_id=blast.id if blast else None,
                               test_type=ttype, instrument_id=instr.id, tested_at=dt(d, self.r.randint(7, 15), self.r.randint(0, 59)),
                               technician_id=self.pick(self.lab_techs if ttype in ("VISCOSITY", "DENSITY", "FLOWABILITY") and instr_code != "DENS-02" else self.techs).id,
                               value=value, unit=unit, test_conditions=cond, sample_temperature_c=temp, approved_test_ref=approved_ref,
                               data_quality=quality, calibration_valid=cal_ok, limit_id=lim.id if lim else None,
                               limit_min=lim.min_value if lim else None, limit_max=lim.max_value if lim else None, result=result,
                               notes=None if cal_ok else "Instrument calibration expired on test date — result not evaluated; retest required."))
        self.flush()
        return t

    def nc(self, test, d, desc, disposition, status="OPEN"):
        self.nc_seq += 1
        n = self.add(m.NonConformance(code=f"NC-26-{self.nc_seq:03d}", lab_test_id=test.id, raised_on=d, description=desc,
                                      disposition=disposition, status=status))
        self.flush()
        return n

    # ------------------------------------------------------------ QSSE
    def capa(self, atype, src, ref, desc, owner, raised, due, status, closed=None, evidence=None):
        self.capa_seq += 1
        return self.add(m.Capa(code=f"CA-26-{self.capa_seq:03d}", action_type=atype, source_type=src, source_ref=ref, description=desc,
                               owner_id=self.people[owner].id, raised_on=raised, due_date=due, status=status, closed_on=closed,
                               closure_evidence=evidence))

    def observation(self, otype, desc, d, area, resp, lik, sev, status, action, closed=None, evidence=None, loc=None):
        self.obs_seq += 1
        o = self.add(m.SafetyObservation(code=f"SO-26-{self.obs_seq:03d}", obs_type=otype, description=desc, observed_at=dt(d, self.r.randint(7, 16)),
                                         area_id=area.id, location_detail=loc, reported_by_id=self.pick(list(self.people.values())).id,
                                         responsible_id=self.people[resp].id, likelihood=lik, severity=sev,
                                         risk_level=self.risk_level(lik, sev), corrective_action=action, status=status,
                                         due_date=d + timedelta(days=14), closed_at=dt(closed, 15) if closed else None,
                                         closure_evidence=evidence))
        self.flush()
        return o

    def qsse(self):
        r = self.r
        templates = [
            ("HAZARD", "Loose material on bench crest near drill pattern", 3, 3, "Scale crest and install berm before drilling resumes"),
            ("OBSERVATION", "Barricade tape damaged at bench access ramp", 2, 2, "Replace barricade and verify daily"),
            ("NEAR_MISS", "Light vehicle entered bench without radio contact", 3, 4, "Reinforce radio protocol at toolbox meeting"),
            ("OBSERVATION", "Hole cover missing on several drilled holes", 3, 2, "Install hole covers immediately after drilling"),
            ("HAZARD", "Ice accumulation on access ramp", 4, 3, "Apply abrasive material; add to winter inspection checklist"),
            ("POSITIVE", "Crew completed pre-task inspection thoroughly with photos", 1, 1, None),
            ("OBSERVATION", "Fire extinguisher inspection tag out of date on LV-02", 2, 2, "Replace/inspect extinguisher"),
            ("NEAR_MISS", "Water hose crossing travel path at MMU loading point", 3, 3, "Route hoses with crossing protectors"),
            ("HAZARD", "Unstable face observed at south wall after rain", 3, 4, "Restrict access; request geotechnical inspection"),
            ("OBSERVATION", "PPE: hearing protection not worn near drill", 3, 2, "Coaching on the spot; PPE reminder at toolbox"),
        ]
        areas = list(self.areas.values())
        for d in daterange(START, self.today):
            if d.weekday() >= 5:
                continue
            # pre-task inspection every working day
            overdue = d > self.today - timedelta(days=10) and r.random() < 0.15
            self.add(m.Inspection(code=f"IN-PT-{d:%y%m%d}", inspection_type="PRE_TASK", area_id=self.pick(areas).id, due_date=d,
                                  inspected_at=None if overdue else dt(d, 6, 45), inspector_id=None if overdue else self.pick(self.techs).id,
                                  status="OVERDUE" if overdue else "COMPLETED", findings=None if overdue else "No critical findings"))
            if d.day <= 7 and d.weekday() == 0:
                self.add(m.Inspection(code=f"IN-PPE-{d:%y%m}", inspection_type="PPE", due_date=d, inspected_at=dt(d, 13),
                                      inspector_id=self.people["P-06"].id, status="COMPLETED", findings="2 hard hats replaced (UV damage)"))
            if r.random() < 0.55:
                t = self.pick(templates)
                age = (self.today - d).days
                if age > 30 or (age > 10 and r.random() < 0.75):
                    st, closed = "CLOSED", d + timedelta(days=r.randint(1, 12))
                    ev = "Photo evidence and supervisor sign-off attached"
                else:
                    st, closed, ev = r.choice(["OPEN", "IN_PROGRESS"]), None, None
                if t[0] == "POSITIVE":
                    st, closed, ev = "CLOSED", d, "Recognized at toolbox meeting"
                o = self.observation(t[0], t[1], d, self.pick(areas), self.pick(["P-01", "P-03", "P-04", "P-06", "P-13"]), t[2], t[3],
                                     st, t[4], closed, ev, loc=self.pick(self.benches).code)
                if o.risk_level in ("HIGH", "CRITICAL") and t[0] != "POSITIVE":
                    cl = closed if st == "CLOSED" else None
                    self.capa("CORRECTIVE", "OBSERVATION", o.code, t[4], o_resp_code(self.people, o.responsible_id), d,
                              d + timedelta(days=14), "CLOSED" if cl else r.choice(["OPEN", "IN_PROGRESS"]), cl, ev)
        # planned preventive actions, some overdue
        self.capa("PREVENTIVE", "AUDIT", "QSSE-AUD-26-03", "Update winter operations checklist (ice on ramps, cold-weather product handling records).",
                  "P-06", date(2026, 10, 20), date(2026, 11, 20), "IN_PROGRESS")
        self.capa("PREVENTIVE", "POST_BLAST", "Lessons learned Q3", "Add 24 h re-verification step for holes in water-bearing zones to technician routine.",
                  "P-03", date(2026, 10, 28), date(2026, 11, 25), "OPEN")
        self.capa("CORRECTIVE", "AUDIT", "CAL-VISC-02", "Remove VISC-02 from service until recalibrated; retest affected samples.",
                  "P-08", date(2026, 12, 1), date(2026, 12, 8), "OPEN")


def o_resp_code(people, pid):
    return next(k for k, p in people.items() if p.id == pid)


def reset_and_seed() -> dict:
    """Deletes EVERY table and regenerates the fictional site. Refused unless BI_MODE=demo."""
    from ..config import DATABASE_URL, IS_DEMO
    from ..db import SessionLocal, init_db

    if not IS_DEMO:
        raise RuntimeError(f"Refused: the demonstration reset only runs with BI_MODE=demo (database {DATABASE_URL.split('@')[-1]})")

    import shutil

    from ..config import FILE_DIRS

    from ..migrate import drop_everything

    drop_everything()
    for folder in FILE_DIRS.values():  # imported point clouds and attachments belong to the previous dataset
        shutil.rmtree(folder, ignore_errors=True)
    init_db()
    with SessionLocal() as db:
        Generator(db).run()
        counts = {t: db.execute(Base.metadata.tables[t].select()).fetchall().__len__() for t in Base.metadata.tables}
    return counts


if __name__ == "__main__":
    c = reset_and_seed()
    for k in sorted(c):
        print(f"{k:28s} {c[k]}")
