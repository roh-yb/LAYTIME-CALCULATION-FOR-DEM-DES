"""정산 대상 송부용 Laytime Statement (Excel).

- 시트 1 'Laytime Statement': 선박/계약 정보 · 정산 요약 · Time Sheet · 서명란 (A4 가로 1페이지 폭 인쇄)
- 시트 2 'Contract': 적용 계약 조건
- 시트 3 'SOF Events': 확정 이벤트 표
일시는 Excel 날짜값, 시간은 [h]:mm 값으로 기록하여 검토자가 수식으로 검산할 수 있다.
"""
import io
from datetime import datetime
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from core.constants import BASIS_LABELS_EN, EVENT_TYPES
from core.timeutil import fmt_dt, fmt_minutes, to_days

from .report import KIND_LABEL, contract_rows

NAVY = "1F3864"
HEADER_FILL = PatternFill("solid", fgColor=NAVY)
LABEL_FILL = PatternFill("solid", fgColor="E7ECF5")
RESULT_FILL = PatternFill("solid", fgColor="FFF2CC")
REVIEW_FILL = PatternFill("solid", fgColor="FFE699")
USER_FILL = PatternFill("solid", fgColor="DDEBF7")
DEM_FILL = PatternFill("solid", fgColor="FCE4D6")
GREY = Font(color="808080")
THIN = Side(style="thin", color="A6A6A6")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
DT_FMT = "yyyy-mm-dd hh:mm"
DUR_FMT = "[h]:mm"
WRAP = Alignment(wrap_text=True, vertical="top")
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)

COLS = ["From", "To", "Duration", "Counted %", "Time Counted", "Cumulative", "Clause (적용 조항)", "Remarks (비고)", "Status"]
WIDTHS = [17, 17, 10, 10, 12, 12, 32, 58, 11]


def _days(minutes) -> float:
    return float(Decimal(str(minutes)) / Decimal(1440))


def _box(ws, row, col, value, *, bold=False, fill=None, fmt=None, align=None, font=None):
    cell = ws.cell(row=row, column=col, value=value)
    cell.border = BORDER
    if bold:
        cell.font = Font(bold=True)
    if font:
        cell.font = font
    if fill:
        cell.fill = fill
    if fmt:
        cell.number_format = fmt
    cell.alignment = align or WRAP
    return cell


def _pair(ws, row, label, value, c_label, c_from, c_to, fill=None, bold_value=False):
    _box(ws, row, c_label, label, bold=True, fill=LABEL_FILL)
    _box(ws, row, c_from, value, fill=fill, bold=bold_value)
    for col in range(c_from + 1, c_to + 1):
        _box(ws, row, col, None, fill=fill)
    ws.merge_cells(start_row=row, start_column=c_from, end_row=row, end_column=c_to)


def _statement_sheet(ws, c: dict, r: dict):
    for i, w in enumerate(WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws.merge_cells("A1:I1")
    ws["A1"] = "LAYTIME STATEMENT"
    ws["A1"].font = Font(bold=True, size=18, color=NAVY)
    ws["A1"].alignment = Alignment(horizontal="center")
    ws.merge_cells("A2:I2")
    port_kind = "Loading Port" if c["port_type"] == "LOAD" else "Discharging Port"
    ws["A2"] = f"Demurrage / Despatch Calculation — {port_kind} · Basis: {BASIS_LABELS_EN[c['basis']]}"
    ws["A2"].alignment = Alignment(horizontal="center")
    ws["A2"].font = Font(italic=True, color="595959")

    # 1) Particulars (좌: A 라벨/B~D 값, 우: F 라벨/G~I 값)
    laytime_terms = (
        f"{float(c['rate_mt_day']):,.0f} MT/day {c['laytime_terms']}" if c["laytime_mode"] == "RATE"
        else f"Fixed {c['fixed_laytime_hours']} hrs {c['laytime_terms']}"
    )
    if c["laytime_terms"] != "SHINC":
        laytime_terms += f" {c['excepted_used']}"
    left = [
        ("Vessel", c.get("vessel") or ""),
        ("Port", c.get("port") or ""),
        ("Counterparty", c.get("counterparty") or ""),  # 정산 대상
        ("Laycan", f"{c.get('laycan_start') or ''} ~ {c.get('laycan_end') or ''}"),
        ("Cargo (MT)", f"{float(c.get('cargo_qty') or 0):,.3f}"),
        ("Laytime terms", laytime_terms),
    ]
    right = [
        ("Demurrage rate", f"USD {r['demurrage_rate']:,.2f} /day pro rata"),
        ("Despatch rate", f"USD {r['despatch_rate']:,.2f} /day pro rata ({c['despatch_basis']})"),
        ("NOR tendered", fmt_dt(r["nor"])),
        ("Laytime commenced", f"{fmt_dt(r['commence'])}\n{r['commence_basis']}"),
        ("Laytime completed", fmt_dt(r["end"])),
        ("Laytime expired", fmt_dt(r["expiry"]) if r["expiry"] else "-"),
    ]
    row = 4
    _box(ws, row, 1, "PARTICULARS", bold=True, font=Font(bold=True, color="FFFFFF"), fill=HEADER_FILL)
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=9)
    row += 1
    for (ll, lv), (rl, rv) in zip(left, right):
        _pair(ws, row, ll, lv, 1, 2, 4)
        _pair(ws, row, rl, rv, 6, 7, 9)
        if "\n" in rv:
            ws.row_dimensions[row].height = 30
        row += 1

    # 2) Result
    row += 1
    _box(ws, row, 1, "RESULT", bold=True, font=Font(bold=True, color="FFFFFF"), fill=HEADER_FILL)
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=9)
    row += 1
    diff_label = "Time on Demurrage" if r["kind"] == "DEMURRAGE" else f"Time Saved ({c['despatch_basis']})"
    results = [
        ("Allowed Laytime", r["allowed"]),
        ("Time Used", r["used"]),
        (diff_label, r["diff"]),
    ]
    for label, minutes in results:
        _box(ws, row, 1, label, bold=True, fill=LABEL_FILL)
        _box(ws, row, 2, _days(minutes), fmt=DUR_FMT, align=CENTER)
        _box(ws, row, 3, f"{fmt_minutes(minutes)}", align=CENTER)
        _box(ws, row, 4, f"{to_days(minutes)} days", align=CENTER)
        row += 1
    _box(ws, row, 1, KIND_LABEL[r["kind"]], bold=True, fill=RESULT_FILL)
    amt = _box(ws, row, 2, float(r["amount"]), fill=RESULT_FILL, fmt='"USD" #,##0.00', align=CENTER)
    amt.font = Font(bold=True, size=13)
    _box(ws, row, 3, None, fill=RESULT_FILL)
    _box(ws, row, 4, None, fill=RESULT_FILL)
    ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=4)
    note = ws.cell(row=row - 3, column=6, value="1 day = 24 hrs · 금액 = 요율 × 시간(일) pro rata · USD 0.01 반올림")
    note.font = Font(italic=True, color="808080", size=9)
    ws.merge_cells(start_row=row - 3, start_column=6, end_row=row - 3, end_column=9)
    if r["review_count"]:
        warn = ws.cell(row=row - 1, column=6, value=f"⚠ 검토 필요 {r['review_count']}건 미확정 — 송부 전 확인 필요")
        warn.font = Font(bold=True, color="C00000")
        ws.merge_cells(start_row=row - 1, start_column=6, end_row=row - 1, end_column=9)
    row += 2

    # 3) Time Sheet
    _box(ws, row, 1, "TIME SHEET", bold=True, font=Font(bold=True, color="FFFFFF"), fill=HEADER_FILL)
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=9)
    row += 1
    header_row = row
    for col, h in enumerate(COLS, start=1):
        cell = _box(ws, row, col, h, fill=LABEL_FILL, align=CENTER)
        cell.font = Font(bold=True)
    row += 1
    first = row
    for item in r["rows"]:
        if item["status"] == "검토 필요":
            fill = REVIEW_FILL
        elif item["status"] == "사용자 판단":
            fill = USER_FILL
        elif item["on_demurrage"]:
            fill = DEM_FILL
        else:
            fill = None
        font = GREY if item["pct"] == 0 and fill is None else None
        remarks = ("[ON DEMURRAGE] " if item["on_demurrage"] else "") + item["remarks"]
        vals = [
            (item["from"], DT_FMT), (item["to"], DT_FMT), (_days(item["duration"]), DUR_FMT),
            (float(item["pct"]) / 100, "0%"), (_days(item["counted"]), DUR_FMT),
            (_days(item["cumulative"]) if item["cumulative"] is not None else None, DUR_FMT),
            (item["clause"], None), (remarks, None), (item["status"], None),
        ]
        for col, (v, fmt) in enumerate(vals, start=1):
            cell = _box(ws, row, col, v, fill=fill, fmt=fmt, align=CENTER if col <= 6 or col == 9 else WRAP)
            if font:
                cell.font = font
        row += 1
    last = row - 1
    _box(ws, row, 1, "TOTAL TIME USED", bold=True, fill=LABEL_FILL)
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
    total = _box(ws, row, 5, f"=SUM(E{first}:E{last})" if last >= first else 0, fmt=DUR_FMT, align=CENTER, fill=LABEL_FILL)
    total.font = Font(bold=True)
    ws.freeze_panes = None
    row += 3

    # 4) 서명란
    for col_from, col_to, title in ((1, 3, "Prepared by"), (4, 6, "Checked by"), (7, 9, "Agreed by (Owner / Supplier)")):
        _box(ws, row, col_from, title, bold=True, fill=LABEL_FILL, align=CENTER)
        for col in range(col_from + 1, col_to + 1):
            _box(ws, row, col, None, fill=LABEL_FILL)
        ws.merge_cells(start_row=row, start_column=col_from, end_row=row, end_column=col_to)
        for col in range(col_from, col_to + 1):
            _box(ws, row + 1, col, None)
        ws.merge_cells(start_row=row + 1, start_column=col_from, end_row=row + 1, end_column=col_to)
    ws.row_dimensions[row + 1].height = 45
    foot = ws.cell(row=row + 3, column=1, value=f"Generated {datetime.now():%Y-%m-%d %H:%M} · Laytime Calculator · Without prejudice")
    foot.font = Font(italic=True, color="808080", size=9)

    # 인쇄 설정: A4 가로, 폭 1페이지, Time Sheet 머리글 반복
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = f"{header_row}:{header_row}"
    ws.page_margins.left = ws.page_margins.right = 0.4
    ws.sheet_view.showGridLines = False


def build_excel(c: dict, r: dict, events: list[dict]) -> bytes:
    wb = Workbook()
    _statement_sheet(wb.active, c, r)
    wb.active.title = "Laytime Statement"

    cs = wb.create_sheet("Contract")
    for col, h in enumerate(["항목", "내용"], start=1):
        _box(cs, 1, col, h, fill=HEADER_FILL, font=Font(bold=True, color="FFFFFF"), align=CENTER)
    for i, (k, v) in enumerate(contract_rows(c), start=2):
        _box(cs, i, 1, k, bold=True, fill=LABEL_FILL)
        _box(cs, i, 2, v)
    cs.column_dimensions["A"].width = 32
    cs.column_dimensions["B"].width = 90

    es = wb.create_sheet("SOF Events")
    for col, h in enumerate(["Start", "End", "Event", "Description (SOF 원문)", "Remarks"], start=1):
        _box(es, 1, col, h, fill=HEADER_FILL, font=Font(bold=True, color="FFFFFF"), align=CENTER)
    for i, e in enumerate(sorted(events, key=lambda x: x["start"]), start=2):
        _box(es, i, 1, e["start"], fmt=DT_FMT, align=CENTER)
        _box(es, i, 2, e.get("end"), fmt=DT_FMT, align=CENTER)
        _box(es, i, 3, EVENT_TYPES.get(e["event_type"], e["event_type"]))
        _box(es, i, 4, e.get("description", ""))
        _box(es, i, 5, e.get("remarks", ""))
    for col, w in zip("ABCDE", (17, 17, 24, 60, 40)):
        es.column_dimensions[col].width = w
    es.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
