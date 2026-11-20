"""Record numbering: PREFIX-YY-NNNN, continuing the highest number used for that prefix and year."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock


def next_code(db: Session, model, prefix: str, on: date | None = None, width: int = 4) -> str:
    yy = f"{(on or clock.today()):%y}"
    head = f"{prefix}-{yy}-"
    n = 0
    for (code,) in db.execute(select(model.code).where(model.code.like(head + "%"))):
        tail = code[len(head):]
        if tail.isdigit():
            n = max(n, int(tail))
    return f"{head}{n + 1:0{width}d}"
