"""데모/테스트용 샘플 계약 및 SOF."""
from datetime import datetime

from .contract import normalize_contract


def sample_contract() -> dict:
    return normalize_contract(
        {
            "basis": "CP",
            "port_type": "LOAD",
            "vessel": "MV SAMPLE STAR",
            "port": "Port Hedland",
            "country": "AU",
            "counterparty": "",
            "laycan_start": "2026-03-01 00:00",
            "laycan_end": "2026-03-10 23:59",
            "cargo_qty": 150000.0,
            "laytime_mode": "RATE",
            "rate_mt_day": 32000.0,
            "laytime_terms": "SHINC",
            "demurrage_rate": 20000.0,
            "despatch_mode": "RATIO",
            "despatch_ratio": 0.5,
            "despatch_basis": "WTS",
            "notice_hours": 6.0,
            "commence_if_sooner": True,
            "berth_terms": "WIBON",
            "laytime_end_event": "COMPLETED",
            "oodaod": True,
            "clause_laytime": "Cl.5",
            "clause_nor": "Cl.6",
            "clause_demurrage": "Cl.7",
            "exceptions": {
                "shifting": {"applies": True, "counted_pct": 0.0, "clause": "Cl.8 Shifting"},
                "draft_survey": {"applies": True, "counted_pct": 0.0, "clause": "Cl.9 Draft survey"},
                "weather": {"applies": True, "counted_pct": 0.0, "clause": "Cl.10 WWD"},
                "breakdown_ship": {"applies": True, "counted_pct": 0.0, "clause": "Cl.11"},
                "breakdown_shore": {"applies": False, "counted_pct": 0.0, "clause": ""},
                "strike": {"applies": False, "counted_pct": 0.0, "clause": ""},
            },
        }
    )


CLAUDE_YB_ASSUMPTION = (
    "MV CLAUDE YB: SOF 는 실제 샘플(SOF_MV CLAUDE YB.pdf), 계약 조건은 가정값입니다 "
    "(CP·확정 Laytime Statement 미확보 — 35,000 MT/day SHINC, USD 25,000/day, Despatch 1/2 WTS, NOR+6h, WIBON)."
)


def claude_yb_contract() -> dict:
    """SOF_MV CLAUDE YB 용 가정 계약 조건 (실제 CP 확보 시 교체)."""
    return normalize_contract(
        {
            "basis": "CP",
            "port_type": "DISCH",
            "vessel": "MV CLAUDE YB",
            "port": "Dangjin",
            "country": "KR",
            "counterparty": "",  # CP 미확보 — 화면에서 선사 선택
            "laycan_start": "2026-09-28 00:00",
            "laycan_end": "2026-10-07 23:59",
            "cargo_qty": 175000.0,
            "laytime_mode": "RATE",
            "rate_mt_day": 35000.0,
            "laytime_terms": "SHINC",
            "demurrage_rate": 25000.0,
            "despatch_mode": "RATIO",
            "despatch_ratio": 0.5,
            "despatch_basis": "WTS",
            "notice_hours": 6.0,
            "commence_if_sooner": True,
            "berth_terms": "WIBON",
            "laytime_end_event": "COMPLETED",
            "oodaod": True,
            "nor_condition": "(가정) WIBON, WIPON, WIFPON, WCCON",
        }
    )


def claude_yb_events() -> list[dict]:
    """SOF_MV CLAUDE YB.pdf 수기 전사본 (AI 파싱 정확도 비교 기준으로도 사용)."""
    rows = [
        ("2026-10-01 08:30", None, "ARRIVAL", "Arrived Dangjin outer anchorage (End of Sea Passage)", ""),
        ("2026-10-01 09:12", None, "ANCHORED", "Dropped anchor at Dangjin anchorage", ""),
        ("2026-10-01 09:30", None, "FREE_PRATIQUE", "Free pratique granted by radio", ""),
        ("2026-10-01 10:00", None, "NOR_TENDERED", "Notice of Readiness tendered by Master", ""),
        ("2026-10-01 10:00", None, "NOR_ACCEPTED", "NOR accepted subject to all terms, conditions and exceptions of C/P", ""),
        ("2026-10-01 10:00", None, "OTHER", "Vessel waiting at anchorage for berth (berth occupied / congestion)", "대기 01-Oct 10:00 ~ 03-Oct 10:00 (WIBON: Laytime 반영)"),
        ("2026-10-01 14:00", None, "OTHER", "Inward customs clearance completed", ""),
        ("2026-10-03 10:00", None, "PILOT_ON", "Pilot on board / Commenced heaving up anchor", ""),
        ("2026-10-03 10:00", "2026-10-03 17:00", "SHIFTING", "Shifting anchorage to Raw Material Berth No.1", "Anchor aweigh 10:24, first line 16:30"),
        ("2026-10-03 17:00", None, "ALL_FAST", "All fast alongside Raw Material Berth No.1 / Shifting completed", ""),
        ("2026-10-03 17:00", "2026-10-03 18:00", "DRAFT_SURVEY", "Initial draft survey", ""),
        ("2026-10-03 18:00", None, "COMMENCED", "Commenced discharging", ""),
        ("2026-10-06 15:00", None, "COMPLETED", "Completed discharging", "175,000.000 MT"),
        ("2026-10-06 15:00", "2026-10-06 16:00", "DRAFT_SURVEY", "Final draft survey", ""),
        ("2026-10-06 17:30", None, "DOCS_ON_BOARD", "Cargo documents on board", ""),
        ("2026-10-06 18:30", None, "OTHER", "Pilot on board", ""),
        ("2026-10-06 19:00", None, "OTHER", "Last line let go / Vessel sailed", ""),
    ]
    return [
        {"start": _dt(s), "end": _dt(e) if e else None, "event_type": t, "description": d, "remarks": r}
        for s, e, t, d, r in rows
    ]


def _dt(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M")


def sample_events() -> list[dict]:
    rows = [
        ("2026-03-02 08:00", None, "ARRIVAL", "EOSP / Arrived Port Hedland anchorage"),
        ("2026-03-02 08:00", None, "NOR_TENDERED", "NOR tendered"),
        ("2026-03-02 09:00", None, "ANCHORED", "Dropped anchor"),
        ("2026-03-03 10:00", "2026-03-03 11:30", "SHIFTING", "Anchor aweigh, shifting to berth"),
        ("2026-03-03 11:30", None, "ALL_FAST", "All fast No.3 berth"),
        ("2026-03-03 12:00", "2026-03-03 13:00", "DRAFT_SURVEY", "Initial draft survey"),
        ("2026-03-03 13:30", None, "COMMENCED", "Commenced loading"),
        ("2026-03-04 15:00", "2026-03-04 19:00", "WEATHER", "Rain stopped loading"),
        ("2026-03-05 02:00", "2026-03-05 05:00", "BREAKDOWN_SHORE", "Shiploader breakdown"),
        ("2026-03-07 16:00", "2026-03-07 17:00", "WEATHER", "Rain stopped loading"),
        ("2026-03-07 20:00", None, "COMPLETED", "Completed loading"),
        ("2026-03-07 21:00", None, "DOCS_ON_BOARD", "Documents on board"),
    ]
    return [
        {"start": _dt(s), "end": _dt(e) if e else None, "event_type": t, "description": d, "remarks": ""}
        for s, e, t, d in rows
    ]
