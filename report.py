"""REPORTLAB PDF EXPORT — LISTERS H&S ISSUES REPORT (A4 LANDSCAPE)

Pure rendering: it knows nothing about HTTP or how the CSV was uploaded.
Feed it the aggregate dict core.parse_issues_csv() produces and it returns
PDF bytes — a masthead, a KPI strip, then the same three charts the
dashboard shows, hand-drawn with reportlab shapes so they read crisply at
print size and match the on-screen palette exactly.
"""

import io
import os
from datetime import datetime
from typing import Dict, List, Sequence

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
)
from reportlab.graphics.shapes import Drawing, Rect, String, Line

from core import OTHER_CATEGORY

# ---- Page geometry -----------------------------------------------------
PAGE_SIZE = landscape(A4)
MARGIN = 16 * mm
FOOTER_RESERVE = 26

# ---- Listers brand tokens (mirrors export.html's :root palette) --------
NAVY   = colors.HexColor("#0F2752")
BLUE   = colors.HexColor("#20448C")
BLUE_L = colors.HexColor("#3E63B0")
BLUE_050 = colors.HexColor("#EAF0FA")
GOLD   = colors.HexColor("#F1C300")
INK    = colors.HexColor("#1A1F2B")
MUTED  = colors.HexColor("#5B6472")
LINE   = colors.HexColor("#E2E6EE")
PANEL  = colors.HexColor("#F4F6FA")
BAD    = colors.HexColor("#C0374A")   # Open
OK     = colors.HexColor("#1E7A5C")   # Resolved

CATEGORY_COLOURS = {
    "PVC":       "#20448C",
    "Warehouse": "#F1C300",
    "Yard":      "#1E7A5C",
    "Aluminium": "#5B6472",
    "Office":    "#7C5CBF",
    OTHER_CATEGORY: "#C7CDD9",
}

# ---- Fonts: Listers' own Archivo / Hanken Grotesk, embedded ------------
FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
_FONT_FILES = {
    "Archivo-Black":     "Archivo-Black.ttf",
    "Archivo-ExtraBold": "Archivo-ExtraBold.ttf",
    "Archivo-Bold":      "Archivo-Bold.ttf",
    "Archivo-SemiBold":  "Archivo-SemiBold.ttf",
    "Hanken-Regular":    "HankenGrotesk-Regular.ttf",
    "Hanken-Medium":     "HankenGrotesk-Medium.ttf",
    "Hanken-SemiBold":   "HankenGrotesk-SemiBold.ttf",
    "Hanken-Bold":       "HankenGrotesk-Bold.ttf",
}


def _register_fonts():
    for name, fname in _FONT_FILES.items():
        path = os.path.join(FONT_DIR, fname)
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(name, path))
            except Exception:
                pass


_register_fonts()


def _font(name: str, fallback: str) -> str:
    return name if name in pdfmetrics.getRegisteredFontNames() else fallback


F_BLACK, F_XBOLD, F_BOLD, F_SEMI = (
    _font("Archivo-Black", "Helvetica-Bold"),
    _font("Archivo-ExtraBold", "Helvetica-Bold"),
    _font("Archivo-Bold", "Helvetica-Bold"),
    _font("Archivo-SemiBold", "Helvetica-Bold"),
)
H_REG, H_MED, H_SEMI, H_BOLD = (
    _font("Hanken-Regular", "Helvetica"),
    _font("Hanken-Medium", "Helvetica"),
    _font("Hanken-SemiBold", "Helvetica-Bold"),
    _font("Hanken-Bold", "Helvetica-Bold"),
)


# ---------------------------------------------------------------------
# Page furniture
# ---------------------------------------------------------------------

class ReportLabNumberedCanvas(canvas.Canvas):
    """Two-pass canvas for dynamic page numbers and a running footer."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_footer(num_pages)
            super().showPage()
        super().save()

    def draw_footer(self, page_count):
        self.saveState()
        page_width = self._pagesize[0]
        margin = MARGIN
        footer_y = 22.0

        self.setStrokeColor(LINE)
        self.setLineWidth(1.1)
        self.line(margin, footer_y + 14, page_width - margin, footer_y + 14)

        self.setFont(H_BOLD, 9)
        self.setFillColor(BLUE)
        self.drawString(margin, footer_y, "LISTERS • HEALTH & SAFETY ISSUES REPORT")

        self.setFont(H_BOLD, 9)
        self.setFillColor(MUTED)
        self.drawRightString(page_width - margin, footer_y,
                             f"PAGE {self._pageNumber} OF {page_count}")
        self.restoreState()


def _styles() -> Dict[str, ParagraphStyle]:
    P = ParagraphStyle
    return {
        "title":    P("t",  fontName=F_BLACK, fontSize=24, leading=27, textColor=NAVY),
        "subtitle": P("st", fontName=H_SEMI, fontSize=10.5, leading=14, textColor=MUTED),
        "brand":    P("br", fontName=F_XBOLD, fontSize=15, leading=17, textColor=colors.white, alignment=1),
        "brandsub": P("brs", fontName=H_BOLD, fontSize=8, leading=10, textColor=MUTED, alignment=2),
        "label":    P("lb", fontName=H_BOLD, fontSize=9, leading=11, textColor=MUTED),
        "value_lg": P("vlg", fontName=F_XBOLD, fontSize=22, leading=24, textColor=BLUE),
        "panel_h":  P("ph", fontName=H_BOLD, fontSize=10.5, leading=13, textColor=NAVY),
        "empty":    P("em", fontName=H_SEMI, fontSize=13, leading=17, textColor=MUTED, alignment=1),
    }


def _field(label: str, value: str, S) -> List:
    return [Paragraph(label, S["label"]), Spacer(1, 3), Paragraph(value, S["value_lg"])]


def _panel(inner, width: float, S, title: str) -> Table:
    """Wrap a Drawing/legend stack in a titled, bordered panel."""
    t = Table([[Paragraph(title, S["panel_h"])], [inner]], colWidths=[width])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1, LINE),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, 0), 10),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 1), (-1, 1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 12),
    ]))
    return t


def _empty_panel(width: float, height: float, S, text: str) -> Drawing:
    d = Drawing(width, height)
    d.add(Rect(0, 0, width, height, fillColor=PANEL, strokeColor=LINE))
    d.add(String(width / 2.0, height / 2.0 - 5, text,
                 fontName=H_SEMI, fontSize=12, fillColor=MUTED, textAnchor="middle"))
    return d


# ---------------------------------------------------------------------
# Chart 1 — issues by month (simple column chart)
# ---------------------------------------------------------------------

def _month_bar_chart(by_month: Sequence[Dict], width: float, height: float) -> Drawing:
    if not by_month:
        return _empty_panel(width, height, None, "NO ISSUES IN THIS DATA")

    d = Drawing(width, height)
    axis_pad_l, axis_pad_b, top_pad = 6, 24, 18
    plot_w = width - axis_pad_l - 6
    plot_h = height - axis_pad_b - top_pad
    plot_x, plot_y = axis_pad_l, axis_pad_b

    counts = [m["count"] for m in by_month]
    max_c = max(counts) or 1
    n = len(by_month)
    gap = 8
    bar_w = min(34.0, (plot_w - gap * (n - 1)) / n if n else plot_w)
    total_w = bar_w * n + gap * (n - 1)
    start_x = plot_x + (plot_w - total_w) / 2.0

    d.add(Line(plot_x, plot_y, plot_x + plot_w, plot_y, strokeColor=LINE, strokeWidth=1))

    for i, m in enumerate(by_month):
        x = start_x + i * (bar_w + gap)
        h = (m["count"] / max_c) * plot_h if max_c else 0
        d.add(Rect(x, plot_y, bar_w, h, fillColor=BLUE, strokeColor=None))
        d.add(String(x + bar_w / 2.0, plot_y + h + 5, str(m["count"]),
                     fontName=H_BOLD, fontSize=9, fillColor=INK, textAnchor="middle"))
        d.add(String(x + bar_w / 2.0, plot_y - 14, m["label"].upper(),
                     fontName=H_SEMI, fontSize=7.5, fillColor=MUTED, textAnchor="middle"))
    return d


# ---------------------------------------------------------------------
# Chart 2 — category counts per month (stacked column chart)
# ---------------------------------------------------------------------

def _category_legend(categories: Sequence[str], width: float) -> Table:
    cells = []
    for cat in categories:
        colour = CATEGORY_COLOURS.get(cat, "#C7CDD9")
        cells.append(Paragraph(
            f'<font name="Helvetica-Bold" color="{colour}">&#9632;</font>&nbsp; {cat}',
            ParagraphStyle("leg", fontName=H_SEMI, fontSize=9, textColor=INK)))
    n = max(len(cells), 1)
    legend = Table([cells or [""]], colWidths=[width / n] * n)
    legend.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return legend


def _stacked_month_chart(months: Sequence[str], categories: Sequence[str],
                          series: Dict[str, List[int]], width: float, height: float) -> Drawing:
    if not months:
        return _empty_panel(width, height, None, "NO ISSUES IN THIS DATA")

    d = Drawing(width, height)
    axis_pad_l, axis_pad_b, top_pad = 6, 24, 12
    plot_w = width - axis_pad_l - 6
    plot_h = height - axis_pad_b - top_pad
    plot_x, plot_y = axis_pad_l, axis_pad_b

    totals = [sum(series[c][i] for c in categories) for i in range(len(months))]
    max_c = max(totals) or 1
    n = len(months)
    gap = 8
    bar_w = min(34.0, (plot_w - gap * (n - 1)) / n if n else plot_w)
    total_w = bar_w * n + gap * (n - 1)
    start_x = plot_x + (plot_w - total_w) / 2.0

    d.add(Line(plot_x, plot_y, plot_x + plot_w, plot_y, strokeColor=LINE, strokeWidth=1))

    for i, label in enumerate(months):
        x = start_x + i * (bar_w + gap)
        y = plot_y
        for cat in categories:
            c = series[cat][i]
            if not c:
                continue
            h = (c / max_c) * plot_h if max_c else 0
            d.add(Rect(x, y, bar_w, h, fillColor=colors.HexColor(CATEGORY_COLOURS.get(cat, "#C7CDD9")),
                       strokeColor=colors.white, strokeWidth=0.5))
            y += h
        if totals[i]:
            d.add(String(x + bar_w / 2.0, y + 5, str(totals[i]),
                         fontName=H_BOLD, fontSize=9, fillColor=INK, textAnchor="middle"))
        d.add(String(x + bar_w / 2.0, plot_y - 14, label.upper(),
                     fontName=H_SEMI, fontSize=7.5, fillColor=MUTED, textAnchor="middle"))
    return d


# ---------------------------------------------------------------------
# Chart 3 — status by assignee (horizontal stacked bars)
# ---------------------------------------------------------------------

ROW_H = 20.0


def _assignee_chart(assignees: Sequence[str], open_c: Sequence[int], resolved_c: Sequence[int],
                     width: float) -> Drawing:
    n = len(assignees)
    if n == 0:
        return _empty_panel(width, 60, None, "NO ISSUES IN THIS DATA")

    name_w = min(150.0, width * 0.28)
    count_w = 34.0
    plot_x = name_w
    plot_w = width - name_w - count_w
    height = n * ROW_H + 6

    max_total = max((o + r for o, r in zip(open_c, resolved_c)), default=0) or 1

    d = Drawing(width, height)
    for i, name in enumerate(assignees):
        y = height - (i + 1) * ROW_H + 4
        o, r = open_c[i], resolved_c[i]
        total = o + r
        d.add(String(name_w - 8, y + 5, name if len(name) <= 22 else name[:21] + "…",
                     fontName=H_SEMI, fontSize=8.5, fillColor=INK, textAnchor="end"))
        d.add(Rect(plot_x, y, plot_w, ROW_H - 6, fillColor=PANEL, strokeColor=None))
        x = plot_x
        ow = (o / max_total) * plot_w if max_total else 0
        rw = (r / max_total) * plot_w if max_total else 0
        if ow:
            d.add(Rect(x, y, ow, ROW_H - 6, fillColor=BAD, strokeColor=None))
            x += ow
        if rw:
            d.add(Rect(x, y, rw, ROW_H - 6, fillColor=OK, strokeColor=None))
        d.add(String(plot_x + plot_w + count_w - 4, y + 5, str(total),
                     fontName=H_BOLD, fontSize=9, fillColor=INK, textAnchor="end"))
    return d


def _status_legend() -> Table:
    cells = [
        Paragraph('<font name="Helvetica-Bold" color="#C0374A">&#9632;</font>&nbsp; Open',
                  ParagraphStyle("legO", fontName=H_SEMI, fontSize=9, textColor=INK)),
        Paragraph('<font name="Helvetica-Bold" color="#1E7A5C">&#9632;</font>&nbsp; Resolved',
                  ParagraphStyle("legR", fontName=H_SEMI, fontSize=9, textColor=INK)),
    ]
    legend = Table([cells], colWidths=[70, 90])
    legend.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return legend


# ---------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------

def generate_report_pdf(data: Dict) -> bytes:
    S = _styles()
    summary = data["summary"]
    by_month = data["by_month"]
    cbm = data["category_by_month"]
    sba = data["status_by_assignee"]

    buffer = io.BytesIO()
    margin = MARGIN
    doc = SimpleDocTemplate(
        buffer,
        pagesize=PAGE_SIZE,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin + FOOTER_RESERVE,
        title="Health & Safety Issues Report",
        author="Listers",
        subject="Health & Safety issues — monthly and category breakdown",
    )

    usable_width = PAGE_SIZE[0] - (2 * margin)
    u = usable_width / 12.0
    story: List = []

    # ---- Masthead ------------------------------------------------
    brand_box = Table([[Paragraph("LISTERS", S["brand"])]], colWidths=[u * 2.6], rowHeights=[28])
    brand_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    header_table = Table([[
        [Paragraph("HEALTH & SAFETY ISSUES REPORT", S["title"]),
         Paragraph("MONTHLY VOLUME • CATEGORY BREAKDOWN • STATUS BY ASSIGNEE", S["subtitle"])],
        [brand_box, Spacer(1, 5),
         Paragraph(f"ISSUED {datetime.now().strftime('%d %b %Y %H:%M')}", S["brandsub"])],
    ]], colWidths=[u * 9, u * 3])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(header_table)

    gold_bar = Drawing(usable_width, 4)
    gold_bar.add(Rect(0, 0, usable_width, 4, fillColor=GOLD, strokeColor=None))
    story.append(Spacer(1, 8))
    story.append(gold_bar)
    story.append(Spacer(1, 12))

    # ---- KPI strip -------------------------------------------------
    site_label = ", ".join(summary["sites"]) if summary["sites"] else "All sites"
    range_label = f"{summary['date_from']} – {summary['date_to']}"
    kpi = Table([[
        _field("DATE RANGE", range_label.upper(), S),
        _field("SITE(S)", site_label.upper(), S),
        _field("TOTAL ISSUES", str(summary["total"]), S),
        _field("OPEN", str(summary["open"]), S),
        _field("RESOLVED", str(summary["resolved"]), S),
    ]], colWidths=[u * 3.4, u * 3.0, u * 1.9, u * 1.8, u * 1.9])
    kpi.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.75, LINE),
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    story.append(kpi)
    story.append(Spacer(1, 14))

    # ---- Chart 1: issues by month -----------------------------------
    chart1_inner_w = usable_width - 28
    chart1 = _month_bar_chart(by_month, chart1_inner_w, 120)
    story.append(_panel(chart1, usable_width, S, "ISSUES BY MONTH"))
    story.append(Spacer(1, 12))

    # ---- Chart 2: category by month (stacked) ------------------------
    chart2_inner_w = usable_width - 28
    chart2 = _stacked_month_chart(cbm["months"], cbm["categories"], cbm["series"],
                                   chart2_inner_w, 130)
    legend2 = _category_legend(cbm["categories"], chart2_inner_w)
    panel2 = Table([[Paragraph("CATEGORY BREAKDOWN BY MONTH", S["panel_h"])], [chart2], [legend2]],
                   colWidths=[usable_width])
    panel2.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1, LINE),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, 0), 10),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 1), (-1, 2), 4),
        ("BOTTOMPADDING", (0, 2), (-1, 2), 12),
    ]))
    story.append(panel2)
    story.append(Spacer(1, 12))

    # ---- Chart 3: status by assignee ---------------------------------
    chart3_inner_w = usable_width - 28
    chart3 = _assignee_chart(sba["assignees"], sba["open"], sba["resolved"], chart3_inner_w)
    legend3 = _status_legend()
    panel3 = Table([[Paragraph("STATUS BY ASSIGNEE", S["panel_h"])], [legend3], [chart3]],
                   colWidths=[usable_width])
    panel3.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1, LINE),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, 0), 10),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
        ("TOPPADDING", (0, 1), (-1, 2), 2),
        ("BOTTOMPADDING", (0, 2), (-1, 2), 12),
    ]))
    story.append(panel3)

    doc.build(story, canvasmaker=ReportLabNumberedCanvas)
    buffer.seek(0)
    return buffer.getvalue()
