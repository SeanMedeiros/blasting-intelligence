"""Record templates applied when a blast or a work order is created.

Defaults are generic documentation steps; each site replaces them with its own procedure through
Settings (stored in app_setting). The application never adds technical content to them: checkpoints
record that something was done and where it is documented, nothing more.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..i18n import N_, _, translate

AUTH_CHECKPOINT = N_("External authorization reference recorded")
TEST_TYPES = ("VISCOSITY", "DENSITY", "VOD", "FLOWABILITY", "NOX")


def auth_names() -> set[str]:
    """The workflow's authorization checkpoint, recognised in every language a template may use."""
    return {AUTH_CHECKPOINT, translate(AUTH_CHECKPOINT, "fr")}


def is_auth(name: str) -> bool:
    return name in auth_names()


STAGES = ("PREPARATION", "LOADING", "PRE_BLAST", "POST_BLAST")

DEFAULTS: dict[str, list] = {
    "blast_checkpoints": [
        ["PREPARATION", N_("Approved blast plan reference recorded")],
        ["PREPARATION", N_("Pre-blast 3D face profile completed and accepted")],
        ["PREPARATION", N_("Drillhole verification completed and documented")],
        ["PREPARATION", N_("Work order, crew and equipment confirmed")],
        ["LOADING", N_("Ground and access preparation recorded")],
        ["LOADING", N_("Product issue recorded in inventory")],
        ["LOADING", N_("Loading recorded against approved plan (document reference)")],
        ["LOADING", N_("Stemming completion recorded against approved plan")],
        ["PRE_BLAST", N_("Pre-blast verification checklist completed")],
        ["PRE_BLAST", N_("Exclusion zone confirmed by blaster in charge")],
        ["PRE_BLAST", N_("Vibration monitors deployed and armed")],
        ["PRE_BLAST", AUTH_CHECKPOINT],
        ["POST_BLAST", N_("Post-blast inspection recorded by blaster in charge")],
        ["POST_BLAST", N_("Inventory reconciliation completed")],
        ["POST_BLAST", N_("Post-blast 3D survey completed")],
        ["POST_BLAST", N_("Vibration records retrieved and validated")],
    ],
    "pre_blast_checklist": [
        N_("Approved blast plan and authorization references available on site"),
        N_("Blast area signage and barricades in place"),
        N_("Exclusion zone and guard positions confirmed by blaster in charge"),
        N_("Personnel and equipment cleared from exclusion zone"),
        N_("Client notified of blast window"),
        N_("Vibration monitors deployed at required stations"),
        N_("Communication check completed (radio channel)"),
        N_("Weather conditions recorded"),
    ],
    # activity, offset in days from the blast date
    "standard_schedule": [
        ["DRILLING", -5], ["FACE_SURVEY", -4], ["HOLE_VERIFICATION", -3], ["LOADING", 0], ["BLAST", 0],
        ["POST_BLAST_SURVEY", 1], ["POST_BLAST_REVIEW", 5],
    ],
    # laboratory sampling plan used by the "laboratory testing completion" KPI: [scope, test type]
    # scope BATCH = every product batch produced in the period; BLAST = every blast fired in the period
    "lab_sampling_plan": [["BATCH", "VISCOSITY"], ["BATCH", "DENSITY"], ["BLAST", "DENSITY"]],
}
ACTIVITIES = ("DRILLING", "FACE_SURVEY", "HOLE_VERIFICATION", "LOADING", "BLAST", "POST_BLAST_SURVEY", "POST_BLAST_REVIEW")


def default(name: str) -> list:
    """Default template in the site language (BI_DEFAULT_LANGUAGE)."""
    from ..config import DEFAULT_LANGUAGE

    items = DEFAULTS[name]
    if name == "blast_checkpoints":
        return [[st, translate(txt, DEFAULT_LANGUAGE)] for st, txt in items]
    if name == "pre_blast_checklist":
        return [translate(txt, DEFAULT_LANGUAGE) for txt in items]
    return [list(x) for x in items]


def get(db: Session, name: str) -> list:
    s = db.scalars(select(m.AppSetting).where(m.AppSetting.key == f"template:{name}")).first()
    return s.value["items"] if s else default(name)


def validate(name: str, items: list) -> list:
    if name not in DEFAULTS:
        raise ValueError(_("Unknown template '{name}'", name=name))
    if not items or len(items) > 60:
        raise ValueError(_('between 1 and 60 lines are required'))
    out = []
    if name == "blast_checkpoints":
        for it in items:
            if not (isinstance(it, list) and len(it) == 2 and it[0] in STAGES and isinstance(it[1], str) and 3 <= len(it[1].strip()) <= 200):
                raise ValueError(_('each line needs a stage ({v}) and a text of 3–200 characters', v=', '.join(STAGES)))
            out.append([it[0], it[1].strip()])
        if not auth_names() & {x[1] for x in out}:
            raise ValueError(_("the checkpoint '{name}' is required by the workflow and cannot be removed", name=_(AUTH_CHECKPOINT)))
    elif name == "pre_blast_checklist":
        for it in items:
            if not (isinstance(it, str) and 3 <= len(it.strip()) <= 240):
                raise ValueError(_('each item must be 3–240 characters'))
            out.append(it.strip())
    elif name == "lab_sampling_plan":
        for it in items:
            if not (isinstance(it, list) and len(it) == 2 and it[0] in ("BATCH", "BLAST") and it[1] in TEST_TYPES):
                raise ValueError(_("each line needs a scope (BATCH or BLAST) and a test type ({types})", types=", ".join(TEST_TYPES)))
            if it not in out:
                out.append(it)
    else:
        for it in items:
            if not (isinstance(it, list) and len(it) == 2 and it[0] in ACTIVITIES and isinstance(it[1], int) and -60 <= it[1] <= 60):
                raise ValueError(_('each line needs an activity ({v}) and a day offset between -60 and 60', v=', '.join(ACTIVITIES)))
            out.append(it)
    return out


def save(db: Session, name: str, items: list) -> None:
    s = db.scalars(select(m.AppSetting).where(m.AppSetting.key == f"template:{name}")).first()
    if s is None:
        db.add(m.AppSetting(key=f"template:{name}", value={"items": items}))
    else:
        s.value = {"items": items}
