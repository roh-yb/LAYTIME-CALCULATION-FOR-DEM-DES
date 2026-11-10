"""계산 엔진 경계 조건 (PRD §6) — 손계산 기대값."""
from datetime import datetime
from decimal import Decimal

import pytest

from core.contract import normalize_contract
from core.engine import allowed_minutes, calculate


def dt(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M")


def ev(start, code, end=None):
    return {"start": dt(start), "end": dt(end) if end else None, "event_type": code, "description": "", "remarks": ""}


def contract(**kw):
    base = dict(
        laycan_start="2026-03-05 00:00", laycan_end="2026-03-20 00:00",
        laytime_mode="FIXED", fixed_laytime_hours=24,  # Allowed 1,440분
        demurrage_rate=24000, despatch_ratio=0.5, notice_hours=6, commence_if_sooner=True,
    )
    base.update(kw)
    return normalize_contract(base)


# --- Laytime 개시 -------------------------------------------------------------

EARLY = [ev("2026-03-04 10:00", "NOR_TENDERED"), ev("2026-03-05 10:00", "COMMENCED"), ev("2026-03-06 10:00", "COMPLETED")]


def test_nor_before_laycan_not_before_laycan_default():
    # NOR 03-04 10:00 + 6h = 03-04 16:00 < Laycan 03-05 00:00 → 03-05 00:00 개시
    r = calculate(contract(), EARLY)
    assert r["commence"] == dt("2026-03-05 00:00")
    assert r["used"] == Decimal(2040)  # 03-05 00:00 ~ 03-06 10:00
    assert r["amount"] == Decimal("10000.00")  # 600분 × 24,000 / 1,440


def test_nor_before_laycan_notice_runs_past_laycan():
    evs = [ev("2026-03-04 22:00", "NOR_TENDERED"), ev("2026-03-05 10:00", "COMMENCED"), ev("2026-03-06 10:00", "COMPLETED")]
    assert calculate(contract(), evs)["commence"] == dt("2026-03-05 04:00")


def test_nor_before_laycan_deemed_at_laycan():
    r = calculate(contract(nor_early_mode="DEEMED_AT_LAYCAN"), EARLY)
    assert r["commence"] == dt("2026-03-05 06:00")
    assert r["amount"] == Decimal("4000.00")


def test_nor_before_laycan_allowed_by_contract():
    r = calculate(contract(nor_before_laycan_counts=True), EARLY)
    assert r["commence"] == dt("2026-03-04 16:00")


def test_berth_charter_nor_valid_from_all_fast():
    evs = [ev("2026-03-06 00:00", "NOR_TENDERED"), ev("2026-03-07 00:00", "ALL_FAST"),
           ev("2026-03-07 12:00", "COMMENCED"), ev("2026-03-08 06:00", "COMPLETED")]
    r = calculate(contract(berth_terms="BERTH"), evs)
    assert r["commence"] == dt("2026-03-07 06:00")
    assert r["kind"] == "NIL"
    # WIBON 이면 NOR 시점부터
    assert calculate(contract(berth_terms="WIBON"), evs)["commence"] == dt("2026-03-06 06:00")


def test_unless_sooner_commenced():
    evs = [ev("2026-03-06 00:00", "NOR_TENDERED"), ev("2026-03-06 02:00", "COMMENCED"), ev("2026-03-07 02:00", "COMPLETED")]
    assert calculate(contract(), evs)["commence"] == dt("2026-03-06 02:00")
    assert calculate(contract(commence_if_sooner=False), evs)["commence"] == dt("2026-03-06 06:00")


def test_completed_before_laytime_commenced_is_review():
    evs = [ev("2026-03-06 00:00", "NOR_TENDERED"), ev("2026-03-06 01:00", "COMMENCED"), ev("2026-03-06 03:00", "COMPLETED")]
    r = calculate(contract(commence_if_sooner=False), evs)
    assert r["used"] == 0
    assert r["review_count"] == 1
    assert not any(level == "error" for level, _ in r["notes"])


# --- 예외 · 반영률 -------------------------------------------------------------

def test_overlapping_exceptions_no_double_deduction():
    # 개시 06:00 ~ 03-07 12:00 = 1,800분. 비 10~14 (0%), 육상고장 12~16 (50%)
    # 12~14 중복 → 최저 0% 1회: 공제 = 비 240 + 고장 14~16 의 50% 60 = 300 → 1,500
    evs = [ev("2026-03-06 00:00", "NOR_TENDERED"), ev("2026-03-06 06:00", "COMMENCED"),
           ev("2026-03-06 10:00", "WEATHER", "2026-03-06 14:00"), ev("2026-03-06 12:00", "BREAKDOWN_SHORE", "2026-03-06 16:00"),
           ev("2026-03-07 12:00", "COMPLETED")]
    c = contract(exceptions={"weather": {"applies": True, "counted_pct": 0}, "breakdown_shore": {"applies": True, "counted_pct": 50}})
    r = calculate(c, evs)
    assert r["used"] == Decimal(1500)
    assert r["review_count"] == 1


PCT33 = [ev("2026-03-06 00:00", "NOR_TENDERED"), ev("2026-03-06 06:00", "COMMENCED"),
         ev("2026-03-06 20:00", "BREAKDOWN_SHORE", "2026-03-07 20:00"), ev("2026-03-07 22:00", "COMPLETED")]


def test_non_integer_pct_expiry_triggers_oodaod():
    # 00:00~20:00 100% = 1,200 → 잔여 240분을 33% 로 → 727분 후 03-07 08:07 만료
    # 이후 OODAOD 100%: 08:07~20:00 713 + 20:00~22:00 120 → 사용 2,273, 체선 833분
    c = contract(notice_hours=0, oodaod=True, exceptions={"breakdown_shore": {"applies": True, "counted_pct": 33}})
    r = calculate(c, PCT33)
    assert r["expiry"] == dt("2026-03-07 08:07")
    assert r["used"] == Decimal(2273)
    assert r["diff"] == Decimal(833)
    assert r["amount"] == Decimal("13883.33")
    dem_rows = [x for x in r["rows"] if x["on_demurrage"]]
    assert dem_rows and all(x["pct"] == 100 for x in dem_rows)


def test_non_integer_pct_without_oodaod():
    # 만료 이후에도 33% 유지: 713 × 0.33 = 235.29 + 120 → 체선 355.29분
    c = contract(notice_hours=0, oodaod=False, exceptions={"breakdown_shore": {"applies": True, "counted_pct": 33}})
    r = calculate(c, PCT33)
    assert r["diff"] == Decimal("355.29")
    assert r["amount"] == Decimal("5921.50")


def test_vessel_breakdown_on_demurrage_flagged():
    evs = [ev("2026-03-06 00:00", "NOR_TENDERED"), ev("2026-03-06 06:00", "COMMENCED"),
           ev("2026-03-07 10:00", "BREAKDOWN_SHIP", "2026-03-07 12:00"), ev("2026-03-07 20:00", "COMPLETED")]
    r = calculate(contract(notice_hours=0), evs)
    flagged = [x for x in r["rows"] if x["status"] == "검토 필요"]
    assert flagged and flagged[0]["on_demurrage"] and flagged[0]["pct"] == 100


def test_exception_not_applied_counts_fully():
    evs = [ev("2026-03-06 00:00", "NOR_TENDERED"), ev("2026-03-06 06:00", "COMMENCED"),
           ev("2026-03-06 10:00", "STRIKE", "2026-03-06 12:00"), ev("2026-03-06 18:00", "COMPLETED")]
    r = calculate(contract(notice_hours=0), evs)  # 파업 예외 기본값 = 적용 안 함
    assert r["used"] == Decimal(1080)


# --- 금액 · 반올림 -------------------------------------------------------------

def test_despatch_amount_mode():
    evs = [ev("2026-03-06 00:00", "NOR_TENDERED"), ev("2026-03-06 06:00", "COMMENCED"), ev("2026-03-06 18:00", "COMPLETED")]
    r = calculate(contract(despatch_mode="AMOUNT", despatch_rate=10000), evs)
    assert r["diff"] == Decimal(720)
    assert r["amount"] == Decimal("5000.00")


@pytest.mark.parametrize("mode,expected", [("ROUND", Decimal(4114)), ("DOWN", Decimal(4114)), ("UP", Decimal(4115))])
def test_allowed_rounding_modes(mode, expected):
    # 100,000 / 35,000 × 1,440 = 4,114.2857…
    c = contract(laytime_mode="RATE", cargo_qty=100000, rate_mt_day=35000, allowed_rounding=mode)
    assert allowed_minutes(c) == expected


def test_allowed_exact_and_final_rounding_once():
    c = contract(laytime_mode="RATE", cargo_qty=100000, rate_mt_day=35000, allowed_rounding="EXACT", demurrage_rate=20000)
    assert allowed_minutes(c).quantize(Decimal("0.0001")) == Decimal("4114.2857")
    evs = [ev("2026-03-06 00:00", "NOR_TENDERED"), ev("2026-03-06 06:00", "COMMENCED"), ev("2026-03-07 06:00", "COMPLETED")]
    r = calculate(c, evs)  # 1,440 사용 → saved 2,674.2857분 × 10,000 / 1,440 = 18,571.428… → 18,571.43
    assert r["amount"] == Decimal("18571.43")


def test_deterministic():
    from core.sample import claude_yb_contract, claude_yb_events

    a = calculate(claude_yb_contract(), claude_yb_events())
    b = calculate(claude_yb_contract(), claude_yb_events())
    assert a == b


# --- REVIEW 반영 (M4 · 0 요율) -------------------------------------------------

def test_multiple_nor_flagged_for_review():
    evs = [ev("2026-03-06 00:00", "NOR_TENDERED"), ev("2026-03-06 08:00", "NOR_TENDERED"),
           ev("2026-03-06 10:00", "COMMENCED"), ev("2026-03-07 10:00", "COMPLETED")]
    r = calculate(contract(), evs)
    assert r["review_count"] == 1
    assert any("NOR 제출이 2건" in msg for _, msg in r["notes"])
    assert r["commence"] == dt("2026-03-06 06:00")  # 첫 NOR 기준 (사용자가 무효 NOR 삭제 전까지)


def test_zero_despatch_rate_warns():
    evs = [ev("2026-03-06 00:00", "NOR_TENDERED"), ev("2026-03-06 06:00", "COMMENCED"), ev("2026-03-06 18:00", "COMPLETED")]
    r = calculate(contract(despatch_ratio=0), evs)
    assert r["kind"] == "DESPATCH" and r["amount"] == 0
    assert any("Despatch 요율이 0" in msg for _, msg in r["notes"])
