"""SOF 자동 검증 (PRD §5 기능 2)."""
from datetime import datetime

from core.sample import claude_yb_contract, claude_yb_events
from core.validator import validate_events


def dt(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M")


def ev(start, code, end=None):
    return {"start": dt(start) if start else None, "end": dt(end) if end else None, "event_type": code, "description": "", "remarks": ""}


BASE = [ev("2026-10-01 10:00", "NOR_TENDERED"), ev("2026-10-03 18:00", "COMMENCED"), ev("2026-10-06 15:00", "COMPLETED")]


def check(extra=(), base=BASE, **kw):
    c = claude_yb_contract()
    c.update(kw)
    return validate_events(c, list(base) + list(extra))


def test_sample_passes():
    errors, warnings = validate_events(claude_yb_contract(), claude_yb_events())
    assert errors == [] and warnings == []


def test_missing_required_events():
    errors, _ = check(base=[ev("2026-10-01 10:00", "NOR_TENDERED")])
    assert any("하역 개시" in e for e in errors) and any("하역 완료" in e for e in errors)


def test_interval_without_end_or_reversed():
    errors, _ = check([ev("2026-10-04 10:00", "WEATHER")])
    assert any("종료 일시가 필요" in e for e in errors)
    errors, _ = check([ev("2026-10-04 10:00", "WEATHER", "2026-10-04 09:00")])
    assert any("종료가 시작보다" in e for e in errors)


def test_missing_start_and_type():
    errors, _ = check([ev(None, "OTHER"), {"start": dt("2026-10-02 00:00"), "end": None, "event_type": None}])
    assert any("시작 일시가 없습니다" in e for e in errors)
    assert any("이벤트 종류가 비어" in e for e in errors)


def test_order_errors():
    errors, _ = check(base=[ev("2026-10-01 10:00", "NOR_TENDERED"), ev("2026-10-03 18:00", "COMMENCED"), ev("2026-10-03 12:00", "COMPLETED")])
    assert any("하역 완료가 하역 개시보다" in e for e in errors)


def test_overlap_warning():
    _, warnings = check([ev("2026-10-04 10:00", "WEATHER", "2026-10-04 14:00"), ev("2026-10-04 12:00", "BREAKDOWN_SHORE", "2026-10-04 16:00")])
    assert any("기간 중복" in w for w in warnings)


def test_laycan_warnings():
    _, warnings = check(laycan_start="2026-10-02 00:00")
    assert any("Laycan 시작" in w and "이전에 제출" in w for w in warnings)
    _, warnings = check(laycan_end="2026-09-30 23:59")
    assert any("Laycan 종료" in w for w in warnings)


def test_berth_charter_needs_all_fast_and_docs_order():
    _, warnings = check(berth_terms="BERTH")
    assert any("All fast" in w for w in warnings)
    _, warnings = check([ev("2026-10-06 14:00", "DOCS_ON_BOARD")])
    assert any("서류 선적" in w for w in warnings)


def test_multiple_nor_warning():
    _, warnings = check([ev("2026-10-01 14:00", "NOR_TENDERED")])
    assert any("NOR 제출 이벤트가 2건" in w for w in warnings)
