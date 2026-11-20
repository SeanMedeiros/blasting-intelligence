"""PDF building blocks (ReportLab platypus + matplotlib charts). Letter size, light print theme."""
from __future__ import annotations

import io
import re

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.enums import TA_LEFT  # noqa: E402
from reportlab.lib.pagesizes import letter  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle  # noqa: E402

from .. import clock
from ..i18n import _, code_label, get_lang, num
from ..config import APP_NAME  # noqa: E402

NAVY = colors.HexColor("#0b1220")
ORANGE = colors.HexColor("#e8742c")
GREY = colors.HexColor("#52514e")
LINE = colors.HexColor("#d8d6cf")
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]
GOOD, WARN, CRIT, MUTED = "#0ca30c", "#c98500", "#d03b3b", "#898781"

_ss = getSampleStyleSheet()
STY = {
    "h1": ParagraphStyle("h1", parent=_ss["Heading1"], fontName="Helvetica-Bold", fontSize=16, textColor=NAVY, spaceAfter=2),
    "h2": ParagraphStyle("h2", parent=_ss["Heading2"], fontName="Helvetica-Bold", fontSize=11.5, textColor=NAVY, spaceBefore=10, spaceAfter=4),
    "body": ParagraphStyle("body", parent=_ss["BodyText"], fontName="Helvetica", fontSize=9, leading=12, alignment=TA_LEFT),
    "small": ParagraphStyle("small", parent=_ss["BodyText"], fontName="Helvetica", fontSize=7.5, leading=9.5, textColor=GREY),
    "cell": ParagraphStyle("cell", parent=_ss["BodyText"], fontName="Helvetica", fontSize=7.5, leading=9.2),
    "note": ParagraphStyle("note", parent=_ss["BodyText"], fontName="Helvetica-Oblique", fontSize=8, leading=10, textColor=GREY),
}


def esc(s) -> str:
    return "" if s is None else str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fmt(v, d=1):
    """Number in the request language (1,234.5 / 1 234,5)."""
    if v is None:
        return "—"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return num(v, d)
    return str(v)


_CODE = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)+$|^[A-Z]{4,}$")


def _cell(v):
    """Codes (IN_PROGRESS, PASS…) are shown with their UI label in the request language."""
    return code_label(v) if isinstance(v, str) and _CODE.match(v) else v


class Report:
    def __init__(self, title: str, subtitle: str, generated_by: str):
        self.title, self.subtitle, self.by = title, subtitle, generated_by
        self.story: list = []
        self.story += [Paragraph(esc(title), STY["h1"]), Paragraph(esc(subtitle), STY["small"]), Spacer(1, 4)]
        self.disclaimer = _(clock.banner()) if clock.banner() else ""  # demonstration mode only
        if self.disclaimer:
            banner = Table([[self.disclaimer]], colWidths=[180 * mm])
            banner.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), ORANGE), ("TEXTCOLOR", (0, 0), (-1, -1), NAVY),
                                        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8),
                                        ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
            self.story += [banner, Spacer(1, 6)]
        else:
            self.story.append(Spacer(1, 4))

    def h2(self, t):
        self.story.append(Paragraph(esc(t), STY["h2"]))

    def p(self, t, style="body"):
        self.story.append(Paragraph(t, STY[style]))

    def bullets(self, items):
        for it in items:
            self.story.append(Paragraph(f"• {it}", STY["body"]))

    def kv(self, pairs, cols=2):
        rows, row = [], []
        for k, v in pairs:
            row += [Paragraph(f"<font color='#52514e'>{esc(k)}</font>", STY["cell"]), Paragraph(esc(v), STY["cell"])]
            if len(row) == cols * 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row + [""] * (cols * 2 - len(row)))
        w = 180 * mm / cols
        t = Table(rows, colWidths=[w * 0.42, w * 0.58] * cols)
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.25, LINE),
                               ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
        self.story.append(t)

    def table(self, header, rows, widths=None, status_col=None, max_rows=None):
        if max_rows and len(rows) > max_rows:
            note = _("{n} more rows in the CSV export", n=len(rows) - max_rows)
            rows = rows[:max_rows]
        else:
            note = None
        data = [[Paragraph(f"<b>{esc(h[:1].upper() + h[1:])}</b>", STY["cell"]) for h in header]]
        data += [[Paragraph(esc(_cell(c)), STY["cell"]) for c in r] for r in rows]
        if not rows:
            data.append([Paragraph(_("No records"), STY["cell"])] + [""] * (len(header) - 1))
        t = Table(data, colWidths=widths, repeatRows=1)
        style = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef0f3")), ("LINEBELOW", (0, 0), (-1, -1), 0.25, LINE),
                 ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]
        if status_col is not None:
            for i, r in enumerate(rows, start=1):
                v = str(r[status_col]).upper()
                c = CRIT if any(k in v for k in ("FAIL", "OFF", "EXCEED", "OUT_OF", "OVERDUE", "EXPIRED", "REDRILL")) else (
                    GOOD if any(k in v for k in ("PASS", "ON_TARGET", "COMPLIANT", "WITHIN", "VALID", "ACCEPTED")) else None)
                if c:
                    style.append(("TEXTCOLOR", (status_col, i), (status_col, i), colors.HexColor(c)))
        t.setStyle(TableStyle(style))
        self.story.append(t)
        if note:
            self.p(note, "small")

    def figure(self, fig, width_mm=180, title: str | None = None):
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=160, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        w, h = fig.get_size_inches()
        head = [Paragraph(esc(title), STY["h2"])] if title else []
        self.story.append(KeepTogether(head + [Image(buf, width=width_mm * mm, height=width_mm * mm * h / w), Spacer(1, 4)]))

    def draft_notice(self):
        self.p(_("Narrative drafted automatically from recorded data by deterministic rules. It must be reviewed and "
                 "approved by the responsible person before issue. Engineering and safety decisions remain under qualified human control."), "note")

    def build(self) -> bytes:
        buf = io.BytesIO()
        gen = clock.now().strftime("%Y-%m-%d %H:%M")
        footer = _("{title} · generated {when} by {who}", title=self.title, when=gen, who=self.by) + (f" · {self.disclaimer}" if self.disclaimer else "")
        page_word = _("Page")
        demo_word = _("DEMONSTRATION DATA")

        def deco(c, doc):
            c.saveState()
            c.setFillColor(NAVY)
            c.rect(0, letter[1] - 9 * mm, letter[0], 9 * mm, fill=1, stroke=0)
            c.setFillColor(colors.white)
            c.setFont("Helvetica-Bold", 8)
            c.drawString(15 * mm, letter[1] - 6 * mm, APP_NAME.upper())
            if self.disclaimer:
                c.setFillColor(ORANGE)
                c.drawRightString(letter[0] - 15 * mm, letter[1] - 6 * mm, demo_word)
            c.setFillColor(GREY)
            c.setFont("Helvetica", 7)
            c.drawString(15 * mm, 9 * mm, footer)
            c.drawRightString(letter[0] - 15 * mm, 9 * mm, f"{page_word} {doc.page}")
            c.restoreState()

        doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=16 * mm,
                                title=self.title, author=APP_NAME + (" (demo)" if self.disclaimer else ""), lang=get_lang())
        doc.build(self.story, onFirstPage=deco, onLaterPages=deco)
        return buf.getvalue()


def ax_style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#c3c2b7")
    ax.tick_params(colors="#52514e", labelsize=7)
    ax.grid(axis="y", color="#e1e0d9", linewidth=0.6)
    ax.set_axisbelow(True)
