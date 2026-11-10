"""계약서/SOF AI 파싱 → 검증·정규화된 구조 데이터.

AI 출력은 그대로 계산에 사용하지 않는다. 화면에서 사용자 확인 후 확정한다.
"""
from core.constants import (
    BERTH_TERMS,
    DESPATCH_BASIS,
    EVENT_TYPES,
    EXCEPTED_USED,
    INTERVAL_EVENTS,
    LAYTIME_END_EVENTS,
    LAYTIME_TERMS,
    NOR_EARLY_MODES,
)
from core.contract import DEFAULT_CONTRACT
from core.timeutil import fmt_dt, parse_dt

from .client import chat_json
from .prompts import CONTRACT_SYSTEM, SOF_SYSTEM

MAX_TEXT_CHARS = 60000

_ENUMS = {
    "basis": {"CP", "SPA"},
    "port_type": {"LOAD", "DISCH"},
    "laytime_mode": {"RATE", "FIXED"},
    "laytime_terms": set(LAYTIME_TERMS),
    "excepted_used": set(EXCEPTED_USED),
    "despatch_mode": {"RATIO", "AMOUNT"},
    "despatch_basis": set(DESPATCH_BASIS),
    "berth_terms": set(BERTH_TERMS),
    "laytime_end_event": set(LAYTIME_END_EVENTS),
    "nor_early_mode": set(NOR_EARLY_MODES),
}
_NUMBERS = {"cargo_qty", "rate_mt_day", "fixed_laytime_hours", "demurrage_rate", "despatch_ratio", "despatch_rate", "notice_hours"}
_INTS = {"weekend_start_dow", "weekend_end_dow"}
_BOOLS = {"commence_if_sooner", "nor_before_laycan_counts", "oodaod"}
_TIMES = {"weekend_start_time", "weekend_end_time"}
_DATETIMES = {"laycan_start", "laycan_end"}


def _to_number(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _coerce(key, v):
    """AI 값을 계약 dict 형식으로 변환. 변환 실패 시 None."""
    if v is None:
        return None
    if key in _ENUMS:
        s = str(v).strip().upper()
        return s if s in _ENUMS[key] else None
    if key in _NUMBERS:
        return _to_number(v)
    if key in _INTS:
        n = _to_number(v)
        return int(n) if n is not None and 0 <= n <= 6 else None
    if key in _BOOLS:
        if isinstance(v, bool):
            return v
        s = str(v).strip().lower()
        return True if s in ("true", "yes", "y") else False if s in ("false", "no", "n") else None
    if key in _TIMES:
        s = str(v).strip()
        try:
            h, m = s.split(":")[:2]
            return f"{int(h):02d}:{int(m):02d}"
        except ValueError:
            return None
    if key in _DATETIMES:
        dt = parse_dt(v)
        return fmt_dt(dt) if dt else None
    return str(v).strip()


def parse_contract(text: str, images: list[str] | None = None) -> dict:
    """반환: {"values": {key: value}, "exceptions": {key: rule}, "meta": {key: {...}}, "summary": str, "usage": {...}}"""
    user = "Contract text:\n\n" + (text or "")[:MAX_TEXT_CHARS]
    data, usage = chat_json(CONTRACT_SYSTEM, user, images)

    values, meta = {}, {}
    for key, item in (data.get("fields") or {}).items():
        if key not in DEFAULT_CONTRACT or key in ("exceptions", "holidays"):
            continue
        item = item if isinstance(item, dict) else {"value": item}
        raw = item.get("value")
        val = _coerce(key, raw)
        review = bool(item.get("needs_review")) or str(item.get("confidence", "")).lower() == "low"
        if raw is not None and val is None:
            review = True  # 형식 변환 실패
        meta[key] = {
            "value": val if val is not None else raw,
            "source_clause": item.get("source_clause"),
            "confidence": item.get("confidence"),
            "needs_review": review or val is None,
        }
        if val is not None:
            values[key] = val  # 검토 필요 항목도 값은 채우고 화면에서 표시

    exceptions = {}
    for key, item in (data.get("exceptions") or {}).items():
        if key not in DEFAULT_CONTRACT["exceptions"] or not isinstance(item, dict):
            continue
        rule = {}
        if isinstance(item.get("applies"), bool):
            rule["applies"] = item["applies"]
        pct = _to_number(item.get("counted_pct"))
        if pct is not None and 0 <= pct <= 100:
            rule["counted_pct"] = pct
        if item.get("clause"):
            rule["clause"] = str(item["clause"])
        if rule:
            exceptions[key] = rule
        meta[f"exc_{key}"] = {
            "value": rule or None,
            "source_clause": item.get("source_clause"),
            "confidence": item.get("confidence"),
            "needs_review": bool(item.get("needs_review")) or not rule or str(item.get("confidence", "")).lower() == "low",
        }

    return {"values": values, "exceptions": exceptions, "meta": meta, "summary": data.get("summary", ""), "usage": usage}


def parse_sof(text: str, images: list[str] | None = None, year_hint: str = "") -> dict:
    """반환: {"events": [ {start, end, event_type, description, remarks, ai_flag} ], "summary", "usage", "vessel", "port"}"""
    hint = f"Context hint: laycan / voyage period around {year_hint}.\n\n" if year_hint else ""
    user = hint + "SOF document:\n\n" + ((text or "")[:MAX_TEXT_CHARS] if text else "(see attached images)")
    data, usage = chat_json(SOF_SYSTEM, user, images)

    events = []
    for item in data.get("events") or []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("event_type", "")).strip().upper()
        flag = bool(item.get("ai_flag"))
        remarks = str(item.get("remarks") or "")
        if code not in EVENT_TYPES:
            remarks = f"[원래 분류: {code}] {remarks}".strip()
            code, flag = "OTHER", True
        start, end = parse_dt(item.get("start")), parse_dt(item.get("end"))
        if start is None:
            flag = True
        if code in INTERVAL_EVENTS and end is None:
            flag = True
            remarks = (remarks + " 종료 시각 확인 필요").strip()
        if code not in INTERVAL_EVENTS:
            end = None
        events.append(
            {
                "start": start,
                "end": end,
                "event_type": code,
                "description": str(item.get("description") or ""),
                "remarks": remarks,
                "ai_flag": flag,
            }
        )
    events.sort(key=lambda e: (e["start"] is None, e["start"] or 0))
    return {
        "events": events,
        "summary": data.get("summary", ""),
        "vessel": data.get("vessel"),
        "port": data.get("port"),
        "usage": usage,
    }
