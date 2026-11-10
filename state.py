"""Streamlit session_state ↔ 계약 dict / 이벤트 표 변환."""
from datetime import time

import pandas as pd
import streamlit as st

from core.constants import EVENT_TYPES, code_from_label, event_label
from core.contract import DEFAULT_CONTRACT, default_contract, normalize_contract
from core.timeutil import fmt_dt, fmt_hm, parse_dt, parse_hm

SIMPLE_KEYS = [
    k
    for k in DEFAULT_CONTRACT
    if k not in ("exceptions", "holidays", "laycan_start", "laycan_end", "weekend_start_time", "weekend_end_time")
]
FLOAT_KEYS = {"cargo_qty", "rate_mt_day", "fixed_laytime_hours", "demurrage_rate", "despatch_ratio", "despatch_rate", "notice_hours"}
EVENT_COLUMNS = ["start", "end", "event_type", "description", "remarks", "ai_flag"]


def contract_to_state(c: dict) -> dict:
    c = normalize_contract(c)
    s = {}
    for k in SIMPLE_KEYS:
        v = c[k]
        s[f"c_{k}"] = float(v or 0) if k in FLOAT_KEYS else v
    for side in ("start", "end"):
        dt = parse_dt(c[f"laycan_{side}"])
        s[f"c_laycan_{side}_date"] = dt.date() if dt else None
        s[f"c_laycan_{side}_time"] = dt.time() if dt else (time(0, 0) if side == "start" else time(23, 59))
        s[f"c_weekend_{side}_time"] = parse_hm(c[f"weekend_{side}_time"])
    for ek, rule in c["exceptions"].items():
        s[f"x_{ek}_applies"] = bool(rule.get("applies"))
        s[f"x_{ek}_pct"] = float(rule.get("counted_pct") or 0)
        s[f"x_{ek}_clause"] = rule.get("clause") or ""
    return s


def state_to_contract() -> dict:
    ss = st.session_state
    c = default_contract()
    for k in SIMPLE_KEYS:
        c[k] = ss.get(f"c_{k}", c[k])
    for side in ("start", "end"):
        d = ss.get(f"c_laycan_{side}_date")
        t = ss.get(f"c_laycan_{side}_time") or time(0, 0)
        c[f"laycan_{side}"] = f"{d.isoformat()} {fmt_hm(t)}" if d else None
        c[f"weekend_{side}_time"] = fmt_hm(ss.get(f"c_weekend_{side}_time") or time(0, 0))
    for ek in c["exceptions"]:
        c["exceptions"][ek] = {
            "applies": bool(ss.get(f"x_{ek}_applies")),
            "counted_pct": float(ss.get(f"x_{ek}_pct") or 0),
            "clause": ss.get(f"x_{ek}_clause") or "",
        }
    c["holidays"] = holidays_in_use()
    return c


def holidays_in_use(df: pd.DataFrame | None = None) -> list[dict]:
    if df is None:
        df = st.session_state.get("holidays_df")
    if df is None or df.empty:
        return []
    out = []
    for _, row in df.iterrows():
        if not row.get("적용", True) or pd.isna(row.get("날짜")):
            continue
        d = pd.to_datetime(row["날짜"]).date()
        out.append({"date": d.isoformat(), "name": str(row.get("명칭") or "")})
    return out


def empty_events_df() -> pd.DataFrame:
    df = pd.DataFrame(columns=EVENT_COLUMNS)
    df["start"] = pd.to_datetime(df["start"])
    df["end"] = pd.to_datetime(df["end"])
    df["ai_flag"] = df["ai_flag"].astype(bool)
    return df


def events_to_df(events: list[dict]) -> pd.DataFrame:
    if not events:
        return empty_events_df()
    rows = [
        {
            "start": e.get("start"),
            "end": e.get("end"),
            "event_type": event_label(e["event_type"]),
            "description": e.get("description", ""),
            "remarks": e.get("remarks", ""),
            "ai_flag": bool(e.get("ai_flag", False)),
        }
        for e in events
    ]
    df = pd.DataFrame(rows, columns=EVENT_COLUMNS)
    df["start"] = pd.to_datetime(df["start"])
    df["end"] = pd.to_datetime(df["end"])
    df.index = range(1, len(df) + 1)  # 표의 행 번호 = 검증 메시지의 'n행'
    return df


def df_to_events(df: pd.DataFrame) -> list[dict]:
    events = []
    if df is None:
        return events
    for _, row in df.iterrows():
        code = code_from_label(row.get("event_type"))
        start = parse_dt(row.get("start"))
        if code is None and start is None:
            continue  # 빈 행
        events.append(
            {
                "start": start,
                "end": parse_dt(row.get("end")),
                "event_type": code,
                "description": "" if pd.isna(row.get("description")) else str(row.get("description") or ""),
                "remarks": "" if pd.isna(row.get("remarks")) else str(row.get("remarks") or ""),
                "ai_flag": bool(row.get("ai_flag")) if not pd.isna(row.get("ai_flag")) else False,
            }
        )
    return events


def events_to_json(events: list[dict]) -> list[dict]:
    return [{**e, "start": fmt_dt(e["start"]), "end": fmt_dt(e.get("end")) or None} for e in events]


def events_from_json(items: list[dict]) -> list[dict]:
    return [
        {**e, "start": parse_dt(e.get("start")), "end": parse_dt(e.get("end"))}
        for e in items
        if e.get("event_type") in EVENT_TYPES
    ]


def queue_state(updates: dict, events: list[dict] | None = None, holidays: list[dict] | None = None):
    """위젯 생성 전(다음 실행 시작 시)에 적용할 상태를 예약하고 재실행."""
    pending = st.session_state.setdefault("_pending", {})
    pending.update(updates)
    if events is not None:
        st.session_state["_pending_events"] = events
    if holidays is not None:
        st.session_state["_pending_holidays"] = holidays
    st.rerun()


def apply_pending():
    ss = st.session_state
    if "_pending" in ss:
        for k, v in ss.pop("_pending").items():
            ss[k] = v
    if "_pending_events" in ss:
        ss["events_df"] = events_to_df(ss.pop("_pending_events"))
        ss.pop("events_editor", None)
        ss["events_version"] = ss.get("events_version", 0) + 1
        ss["overrides"] = {}
    if "_pending_holidays" in ss:
        items = ss.pop("_pending_holidays")
        if not items:  # 샘플·템플릿으로 휴일이 비워지면 자동 불러오기를 다시 허용
            ss.pop("_auto_holidays", None)
        ss["holidays_df"] = holidays_to_df(items)
        ss["holidays_version"] = ss.get("holidays_version", 0) + 1


def holidays_to_df(items: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(
        [{"적용": True, "날짜": pd.to_datetime(h["date"]).date(), "명칭": h.get("name", "")} for h in items],
        columns=["적용", "날짜", "명칭"],
    )
    return df


def init_state():
    ss = st.session_state
    for k, v in contract_to_state(DEFAULT_CONTRACT).items():
        ss.setdefault(k, v)
    ss.setdefault("events_df", empty_events_df())
    ss.setdefault("events_version", 0)
    ss.setdefault("holidays_df", holidays_to_df([]))
    ss.setdefault("holidays_version", 0)
    ss.setdefault("overrides", {})
    ss.setdefault("ai_contract", None)
    ss.setdefault("ai_sof", None)
    ss.setdefault("sample_note", None)
    ss.setdefault("ai_error", None)
    ss.setdefault("ai_usage", {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0})


def record_ai_error(exc: Exception):
    st.session_state["ai_error"] = str(exc)


def record_usage(usage: dict):
    st.session_state["ai_error"] = None
    u = st.session_state["ai_usage"]
    u["calls"] += 1
    u["prompt_tokens"] += usage.get("prompt_tokens", 0)
    u["completion_tokens"] += usage.get("completion_tokens", 0)
