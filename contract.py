"""계약 조건(체크리스트) 기본값 및 필수 항목 검증.

계약 조건은 JSON 직렬화 가능한 dict 로 관리한다 (템플릿 저장/불러오기 용이).
"""
import copy

from .constants import EXCEPTION_LABELS
from .timeutil import parse_dt

DEFAULT_EXCEPTIONS = {
    "shifting": {"applies": True, "counted_pct": 0.0, "clause": ""},
    "draft_survey": {"applies": True, "counted_pct": 0.0, "clause": ""},
    "weather": {"applies": False, "counted_pct": 0.0, "clause": ""},
    "breakdown_ship": {"applies": True, "counted_pct": 0.0, "clause": ""},
    "breakdown_shore": {"applies": False, "counted_pct": 0.0, "clause": ""},
    "strike": {"applies": False, "counted_pct": 0.0, "clause": ""},
}

DEFAULT_CONTRACT = {
    # 기본
    "basis": "CP",  # CP / SPA
    "port_type": "LOAD",  # LOAD / DISCH
    "vessel": "",
    "port": "",
    "country": "KR",
    "counterparty": "",
    "laycan_start": None,  # "YYYY-MM-DD HH:MM"
    "laycan_end": None,
    # 물량·Laytime
    "cargo_qty": 0.0,
    "laytime_mode": "RATE",  # RATE / FIXED
    "rate_mt_day": 0.0,
    "fixed_laytime_hours": 0.0,
    "allowed_rounding": "ROUND",
    "laytime_terms": "SHINC",  # SHINC / SHEX / SSHEX
    "excepted_used": "EIU",  # EIU / UU
    "weekend_start_dow": 6,  # 0=월 … 6=일
    "weekend_start_time": "00:00",
    "weekend_end_dow": 0,
    "weekend_end_time": "00:00",
    # 요율
    "demurrage_rate": 0.0,
    "despatch_mode": "RATIO",  # RATIO / AMOUNT
    "despatch_ratio": 0.5,
    "despatch_rate": 0.0,
    "despatch_basis": "WTS",  # WTS / ATS
    # NOR
    "nor_condition": "",
    "notice_hours": 6.0,
    "commence_if_sooner": True,
    "nor_before_laycan_counts": False,
    "nor_early_mode": "NOT_BEFORE_LAYCAN",  # Laycan 이전 NOR 처리 (NOR_EARLY_MODES)
    # Berth / 종료
    "berth_terms": "WIBON",
    "laytime_end_event": "COMPLETED",
    "oodaod": True,
    # 조항 번호 (근거 표시용)
    "clause_laytime": "",
    "clause_nor": "",
    "clause_demurrage": "",
    # 예외
    "exceptions": DEFAULT_EXCEPTIONS,
    # 휴일 [{"date": "YYYY-MM-DD", "name": "..."}]
    "holidays": [],
}


def default_contract() -> dict:
    return copy.deepcopy(DEFAULT_CONTRACT)


def normalize_contract(c: dict) -> dict:
    """누락 키를 기본값으로 채운다 (템플릿/AI 결과 호환)."""
    out = default_contract()
    for k, v in (c or {}).items():
        if k == "exceptions" and isinstance(v, dict):
            for ek, ev in v.items():
                if ek in out["exceptions"] and isinstance(ev, dict):
                    out["exceptions"][ek].update(ev)
        elif k in out:
            out[k] = v
    return out


def required_status(c: dict) -> tuple[int, int, list[str]]:
    """(입력된 필수 항목 수, 필수 항목 총수, 누락 라벨)."""
    # 화물량·하역률(또는 고정 Laytime) + Demurrage + Despatch + Notice + Laycan 시작·종료
    total = (2 if c["laytime_mode"] == "RATE" else 1) + 5
    total += sum(1 for r in c["exceptions"].values() if r.get("applies"))
    missing = missing_fields(c)
    return total - len(missing), total, missing


def missing_fields(c: dict) -> list[str]:
    """계산에 필요한 필수 항목 중 누락된 것의 라벨 목록."""
    missing = []
    if c["laytime_mode"] == "RATE":
        if not c.get("cargo_qty") or float(c["cargo_qty"]) <= 0:
            missing.append("화물량 (B/L MT)")
        if not c.get("rate_mt_day") or float(c["rate_mt_day"]) <= 0:
            missing.append("하역률 (MT/day)")
    else:
        if not c.get("fixed_laytime_hours") or float(c["fixed_laytime_hours"]) <= 0:
            missing.append("고정 Laytime (시간)")
    if not c.get("demurrage_rate") or float(c["demurrage_rate"]) <= 0:
        missing.append("Demurrage 요율 (USD/day)")
    if c["despatch_mode"] == "RATIO":
        if c.get("despatch_ratio") is None or float(c["despatch_ratio"]) < 0:
            missing.append("Despatch 비율")
    elif c.get("despatch_rate") is None or float(c["despatch_rate"]) < 0:
        missing.append("Despatch 요율 (USD/day)")
    if c.get("notice_hours") is None:
        missing.append("Notice time")
    if not parse_dt(c.get("laycan_start")):
        missing.append("Laycan 시작")
    if not parse_dt(c.get("laycan_end")):
        missing.append("Laycan 종료")
    for ek, rule in c["exceptions"].items():
        if rule.get("applies") and rule.get("counted_pct") is None:
            missing.append(f"예외 반영률: {EXCEPTION_LABELS[ek]}")
    return missing
