"""SOF 이벤트 및 계약 조건 자동 검증."""
from .constants import EVENT_TYPES, INTERVAL_EVENTS, LAYTIME_END_EVENTS
from .timeutil import fmt_dt, parse_dt


def validate_events(c: dict, events: list[dict]) -> tuple[list[str], list[str]]:
    """(errors, warnings). errors 가 있으면 계산 불가."""
    errors: list[str] = []
    warnings: list[str] = []

    for idx, e in enumerate(events, start=1):
        code = e.get("event_type")
        if not code:
            errors.append(f"{idx}행: 이벤트 종류가 비어 있습니다.")
            continue
        if not e.get("start"):
            errors.append(f"{idx}행 ({EVENT_TYPES.get(code, code)}): 시작 일시가 없습니다.")
            continue
        if code in INTERVAL_EVENTS:
            if not e.get("end"):
                errors.append(f"{idx}행 ({EVENT_TYPES[code]}): 구간 이벤트는 종료 일시가 필요합니다.")
            elif e["end"] <= e["start"]:
                errors.append(f"{idx}행 ({EVENT_TYPES[code]}): 종료가 시작보다 빠르거나 같습니다.")

    valid = [e for e in events if e.get("event_type") and e.get("start")]
    codes = {e["event_type"] for e in valid}
    for req in ("NOR_TENDERED", "COMMENCED", "COMPLETED"):
        if req not in codes:
            errors.append(f"필수 이벤트 누락: {EVENT_TYPES[req]}")
    end_code = c.get("laytime_end_event", "COMPLETED")
    if end_code not in codes and end_code != "COMPLETED":
        warnings.append(f"Laytime 종료 이벤트({LAYTIME_END_EVENTS.get(end_code, end_code)})가 없어 하역 완료로 대체됩니다.")
    if c.get("berth_terms") == "BERTH" and "ALL_FAST" not in codes:
        warnings.append("Berth charter 조건이나 접안 완료(All fast) 이벤트가 없습니다.")

    def first(code):
        hits = sorted(e["start"] for e in valid if e["event_type"] == code)
        return hits[0] if hits else None

    def last(code):
        hits = sorted(e["start"] for e in valid if e["event_type"] == code)
        return hits[-1] if hits else None

    nor, ops_s, ops_e = first("NOR_TENDERED"), first("COMMENCED"), last("COMPLETED")
    n_nor = sum(1 for e in valid if e["event_type"] == "NOR_TENDERED")
    if n_nor > 1:
        warnings.append(f"NOR 제출 이벤트가 {n_nor}건입니다 (재제출). 계산은 첫 NOR 기준이므로, 무효 NOR 행은 표에서 삭제하거나 "
                        "이벤트를 '기타'로 바꾸세요. — 검토 필요")
    if nor and ops_e and ops_e < nor:
        errors.append("시간 순서 오류: 하역 완료가 NOR 제출보다 빠릅니다.")
    if ops_s and ops_e and ops_e <= ops_s:
        errors.append("시간 순서 오류: 하역 완료가 하역 개시보다 빠르거나 같습니다.")
    if nor and ops_s and ops_s < nor:
        warnings.append("하역 개시가 NOR 제출보다 빠릅니다. NOR 유효성을 검토하세요.")
    docs = last("DOCS_ON_BOARD")
    if docs and ops_e and docs < ops_e:
        warnings.append("서류 선적 완료가 하역 완료보다 빠릅니다.")

    laycan_s, laycan_e = parse_dt(c.get("laycan_start")), parse_dt(c.get("laycan_end"))
    if nor and laycan_s and nor < laycan_s:
        msg = "허용(계약)" if c.get("nor_before_laycan_counts") else (
            "Laycan 시작에 제출 간주" if c.get("nor_early_mode") == "DEEMED_AT_LAYCAN" else "Laycan 시작 전 기산 불가"
        )
        warnings.append(f"NOR({fmt_dt(nor)})이 Laycan 시작({fmt_dt(laycan_s)}) 이전에 제출됨 → {msg}")
    if nor and laycan_e and nor > laycan_e:
        warnings.append(f"NOR({fmt_dt(nor)})이 Laycan 종료({fmt_dt(laycan_e)}) 이후에 제출됨 — 검토 필요")

    intervals = sorted(
        (e for e in valid if e["event_type"] in INTERVAL_EVENTS and e.get("end") and e["end"] > e["start"]),
        key=lambda e: e["start"],
    )
    for i, a in enumerate(intervals):
        for b in intervals[i + 1 :]:
            if b["start"] >= a["end"]:
                break
            warnings.append(
                f"기간 중복: {EVENT_TYPES[a['event_type']]}({fmt_dt(a['start'])}~{fmt_dt(a['end'])}) ↔ "
                f"{EVENT_TYPES[b['event_type']]}({fmt_dt(b['start'])}~{fmt_dt(b['end'])}) — 이중 공제 방지 적용, 검토 필요"
            )
    return errors, warnings
