"""계산 엔진 회귀 테스트 — 손계산 값과 분/센트 단위까지 일치해야 한다.

과거 정산 완료 건을 추가할 때는 같은 형식으로 케이스를 늘린다.
"""
from datetime import datetime
from decimal import Decimal

from core.contract import normalize_contract
from core.engine import calculate
from core.sample import sample_contract, sample_events
from core.validator import validate_events


def dt(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M")


def ev(start, code, end=None):
    return {"start": dt(start), "end": dt(end) if end else None, "event_type": code, "description": "", "remarks": ""}


def test_sample_demurrage_with_oodaod():
    # 개시 03-02 14:00 (NOR 08:00 + 6h) ~ 종료 03-07 20:00 = 7,560분
    # 공제: Shifting 90 + Draft 60 + Rain 240 = 390 → 사용 7,170분 (03-07 Rain 은 체선 중 → OODAOD 로 반영)
    # Allowed = 150,000 / 32,000 × 1,440 = 6,750분 → 체선 420분 → 20,000 × 420/1,440 = 5,833.33
    r = calculate(sample_contract(), sample_events())
    assert r["allowed"] == Decimal(6750)
    assert r["commence"] == dt("2026-03-02 14:00")
    assert r["used"] == Decimal(7170)
    assert r["kind"] == "DEMURRAGE"
    assert r["diff"] == Decimal(420)
    assert r["amount"] == Decimal("5833.33")
    assert r["expiry"] == dt("2026-03-07 13:00")
    assert r["review_count"] == 0


def test_sample_without_oodaod():
    c = sample_contract()
    c["oodaod"] = False
    r = calculate(c, sample_events())
    assert r["diff"] == Decimal(360)
    assert r["amount"] == Decimal("5000.00")


def test_despatch_wts():
    c = sample_contract()
    c["laytime_mode"] = "FIXED"
    c["fixed_laytime_hours"] = 144  # 6일 = 8,640분
    r = calculate(c, sample_events())
    assert r["used"] == Decimal(7110)  # 03-07 Rain 60분도 공제
    assert r["kind"] == "DESPATCH"
    assert r["diff"] == Decimal(1530)
    assert r["amount"] == Decimal("10625.00")  # 10,000 × 1,530 / 1,440


def _shex_contract(**kw):
    base = dict(
        laycan_start="2026-03-01 00:00", laycan_end="2026-03-31 00:00",
        laytime_mode="FIXED", fixed_laytime_hours=96, laytime_terms="SHEX",
        weekend_start_dow=6, weekend_start_time="00:00", weekend_end_dow=0, weekend_end_time="00:00",
        demurrage_rate=24000, despatch_ratio=0.5, notice_hours=0, commence_if_sooner=False,
    )
    base.update(kw)
    return normalize_contract(base)


def _shex_events():
    # 2026-03-06 금 18:00 ~ 03-09 월 18:00 (일요일 03-08 포함, 72시간)
    return [ev("2026-03-06 18:00", "NOR_TENDERED"), ev("2026-03-06 18:00", "COMMENCED"), ev("2026-03-09 18:00", "COMPLETED")]


def test_shex_eiu_and_ats():
    r = calculate(_shex_contract(despatch_basis="WTS"), _shex_events())
    assert r["used"] == Decimal(2880)  # 일요일 24h 제외
    assert r["diff"] == Decimal(2880)  # WTS: 5,760 − 2,880
    # ATS: 03-09 18:00 부터 2일 남은 Laytime → 03-11 18:00 만료 (주말 없음) = 2,880
    r = calculate(_shex_contract(despatch_basis="ATS"), _shex_events())
    assert r["diff"] == Decimal(2880)
    # 종료가 금요일이면 ATS 에 일요일이 포함되어 WTS 보다 커진다
    evs = [ev("2026-03-04 18:00", "NOR_TENDERED"), ev("2026-03-04 18:00", "COMMENCED"), ev("2026-03-06 18:00", "COMPLETED")]
    r = calculate(_shex_contract(despatch_basis="ATS"), evs)
    assert r["used"] == Decimal(2880)
    assert r["diff"] == Decimal(2880 + 1440)  # 금18 → 화18 (일요일 포함)


def test_shex_uu_counts_weekend_work():
    r = calculate(_shex_contract(excepted_used="UU"), _shex_events())
    assert r["used"] == Decimal(4320)


def test_overlap_flagged_and_override():
    c = sample_contract()
    evs = sample_events() + [ev("2026-03-04 18:00", "STOPPAGE_OTHER", "2026-03-04 20:00")]
    r = calculate(c, evs)
    review = [x for x in r["rows"] if x["status"] == "검토 필요"]
    assert review
    overrides = {x["key"]: {"pct": 0, "reason": "test"} for x in review}
    r2 = calculate(c, evs, overrides)
    assert r2["review_count"] == 0
    assert any(x["status"] == "사용자 판단" for x in r2["rows"])


# --- SOF_MV CLAUDE YB (실제 SOF + 가정 계약 조건) ---------------------------------
# 확정 Laytime Statement 확보 시 기대값을 확정 금액으로 교체할 것.

def test_claude_yb_shinc_despatch():
    from core.sample import claude_yb_contract, claude_yb_events

    # 개시 10-01 16:00 (NOR 10:00 + 6h) ~ 종료 10-06 15:00 = 7,140분
    # 공제: Shifting 420 + Initial draft survey 60 → 사용 6,660분 (Final survey 는 종료 후라 영향 없음)
    # Allowed 175,000 / 35,000 = 5일 = 7,200분 → Saved 540분 → 12,500 × 540 / 1,440 = 4,687.50
    c, evs = claude_yb_contract(), claude_yb_events()
    errors, _ = validate_events(c, evs)
    assert errors == []
    r = calculate(c, evs)
    assert r["commence"] == dt("2026-10-01 16:00")
    assert r["used"] == Decimal(6660)
    assert r["kind"] == "DESPATCH"
    assert r["diff"] == Decimal(540)
    assert r["amount"] == Decimal("4687.50")
    assert r["review_count"] == 0


def test_claude_yb_shex_with_korean_holidays():
    from core.sample import claude_yb_contract, claude_yb_events

    c = claude_yb_contract()
    c["laytime_terms"] = "SHEX"  # 일 00:00 ~ 월 00:00
    c["holidays"] = [{"date": "2026-10-03", "name": "개천절"}, {"date": "2026-10-05", "name": "개천절 대체 휴일"}]
    # EIU: 7,140 − 10/3 1,440 (Shifting·Draft 중복 공제 없음) − 10/4 1,440 − 10/5 1,440 = 2,820
    r = calculate(c, claude_yb_events())
    assert r["used"] == Decimal(2820)
    # UU: 휴일·일요일 중 하역분 반영 → 10/3 18:00~24:00 360 + 10/4 1,440 + 10/5 1,440 → 6,060
    c["excepted_used"] = "UU"
    r = calculate(c, claude_yb_events())
    assert r["used"] == Decimal(6060)


def test_validator_missing_events():
    errors, _ = validate_events(sample_contract(), [ev("2026-03-02 08:00", "NOR_TENDERED")])
    assert any("하역 개시" in e for e in errors)
    assert any("하역 완료" in e for e in errors)
