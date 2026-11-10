"""Excel 출력 · 화면 표 변환."""
import io
from datetime import datetime, timedelta

import pandas as pd
from openpyxl import load_workbook

from core.engine import calculate
from core.sample import claude_yb_contract, claude_yb_events, sample_contract, sample_events
from export.excel import build_excel
from ui.state import df_to_events, events_from_json, events_to_df, events_to_json


def _wb(c, evs):
    r = calculate(c, evs)
    return load_workbook(io.BytesIO(build_excel(c, r, evs))), r


def _find(ws, text):
    for row in ws.iter_rows():
        for cell in row:
            if cell.value == text:
                return cell
    raise AssertionError(text)


def test_excel_statement_structure_and_values():
    wb, r = _wb(claude_yb_contract(), claude_yb_events())
    assert wb.sheetnames == ["Laytime Statement", "Contract", "SOF Events"]
    ws = wb["Laytime Statement"]
    amount_label = _find(ws, "Despatch (조출료)")
    assert ws.cell(row=amount_label.row, column=2).value == 4687.5
    total = _find(ws, "TOTAL TIME USED")
    formula = ws.cell(row=total.row, column=5).value
    assert formula.startswith("=SUM(E")
    # 수식이 합산하는 값 = 엔진 Time used
    first, last = (int(x[1:]) for x in formula[5:-1].split(":"))
    # openpyxl 은 [h]:mm 서식 셀을 timedelta 로 읽는다
    counted = sum((ws.cell(row=i, column=5).value or timedelta(0) for i in range(first, last + 1)), timedelta(0))
    assert abs(counted.total_seconds() / 60 - float(r["used"])) < 1e-6
    assert isinstance(ws.cell(row=first, column=1).value, datetime)
    assert ws.page_setup.orientation == "landscape"
    assert wb["SOF Events"].max_row == len(claude_yb_events()) + 1


def test_excel_marks_demurrage_and_review():
    c, evs = sample_contract(), sample_events()
    evs = evs + [{"start": datetime(2026, 3, 4, 2), "end": datetime(2026, 3, 4, 3), "event_type": "STOPPAGE_OTHER", "description": "x", "remarks": ""}]
    wb, r = _wb(c, evs)
    ws = wb["Laytime Statement"]
    assert r["review_count"] == 1
    assert any(isinstance(cell.value, str) and "검토 필요 1건" in cell.value for row in ws.iter_rows() for cell in row)
    assert any(isinstance(cell.value, str) and cell.value.startswith("[ON DEMURRAGE]") for row in ws.iter_rows() for cell in row)


def test_df_to_events_handles_nat_and_blank_rows():
    df = events_to_df(claude_yb_events())
    assert list(df.index[:2]) == [1, 2]  # 표 행 번호 = 검증 메시지의 'n행'
    df.loc[df.index.max() + 1] = [pd.NaT, pd.NaT, None, None, None, False]  # data_editor 의 빈 행
    events = df_to_events(df)
    assert len(events) == len(claude_yb_events())
    assert all(e["end"] is None or isinstance(e["end"], datetime) for e in events)
    assert events[0]["event_type"] == "ARRIVAL"


def test_events_json_roundtrip():
    evs = claude_yb_events()
    back = events_from_json(events_to_json(evs))
    assert [(e["start"], e["end"], e["event_type"]) for e in back] == [(e["start"], e["end"], e["event_type"]) for e in evs]


def test_parse_dt_nat_and_fmt():
    from core.timeutil import fmt_dt, fmt_minutes, parse_dt

    assert parse_dt(pd.NaT) is None and fmt_dt(pd.NaT) == "" and fmt_dt(None) == ""
    assert parse_dt("2026-10-01T10:00") == datetime(2026, 10, 1, 10, 0)
    assert parse_dt(pd.Timestamp("2026-10-01 10:00:30")) == datetime(2026, 10, 1, 10, 0)
    assert fmt_minutes(1530) == "1일 01:30"
    assert fmt_minutes(timedelta(minutes=1).total_seconds() / 60 * 0.5) == "0일 00:00:30"
