"""Laytime 계산 엔진 (규칙 기반, AI 의존성 없음).

- 시간 단위: 분. 1일 = 1,440분.
- 금액: 요율 × 분 / 1,440 (pro rata), 최종 금액에서 1회 USD 0.01 단위 ROUND_HALF_UP.
- 같은 입력 → 항상 같은 결과 (결정적).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from .constants import EVENT_TYPES, EXCEPTION_LABELS, INTERVAL_EVENTS, LAYTIME_TERMS
from .timeutil import fmt_dt, parse_dt, parse_hm

D0 = Decimal(0)
D100 = Decimal(100)
D1440 = Decimal(1440)
CENT = Decimal("0.01")

STATUS_OK = "정상"
STATUS_REVIEW = "검토 필요"
STATUS_USER = "사용자 판단"
STATUS_INFO = "정보"


def _dec(x) -> Decimal:
    return Decimal(str(x or 0))


def _minutes(a: datetime, b: datetime) -> int:
    return int((b - a).total_seconds() // 60)


def segment_key(s: datetime, e: datetime) -> str:
    return f"{s:%Y%m%d%H%M}_{e:%Y%m%d%H%M}"


def allowed_minutes(c: dict) -> Decimal:
    if c["laytime_mode"] == "FIXED":
        raw = _dec(c["fixed_laytime_hours"]) * 60
    else:
        raw = _dec(c["cargo_qty"]) / _dec(c["rate_mt_day"]) * D1440
    mode = c.get("allowed_rounding", "ROUND")
    if mode == "EXACT":
        return raw
    rounding = {"ROUND": ROUND_HALF_UP, "DOWN": ROUND_FLOOR, "UP": ROUND_CEILING}[mode]
    return raw.quantize(Decimal(1), rounding)


def despatch_rate(c: dict) -> Decimal:
    if c["despatch_mode"] == "RATIO":
        return _dec(c["demurrage_rate"]) * _dec(c["despatch_ratio"])
    return _dec(c["despatch_rate"])


def excepted_periods(c: dict, start: datetime, end: datetime) -> list[tuple[datetime, datetime, str]]:
    """주말·휴일 제외 구간 (SHINC 이면 없음)."""
    if c["laytime_terms"] == "SHINC":
        return []
    periods: list[tuple[datetime, datetime, str]] = []
    sd, st_ = int(c["weekend_start_dow"]), parse_hm(c["weekend_start_time"])
    ed, et = int(c["weekend_end_dow"]), parse_hm(c["weekend_end_time"])
    day = (start - timedelta(days=8)).date()
    last = end.date() + timedelta(days=1)
    while day <= last:
        if day.weekday() == sd:
            ps = datetime.combine(day, st_)
            pe = datetime.combine(day + timedelta(days=(ed - sd) % 7), et)
            if pe <= ps:
                pe += timedelta(days=7)
            periods.append((ps, pe, "주말"))
        day += timedelta(days=1)
    for h in c.get("holidays") or []:
        try:
            d = date.fromisoformat(str(h["date"])[:10])
        except (KeyError, ValueError):
            continue
        ps = datetime.combine(d, datetime.min.time())
        periods.append((ps, ps + timedelta(days=1), f"휴일({h.get('name', '')})"))
    return sorted(p for p in periods if p[1] > start and p[0] < end)


def _ats_saved(c: dict, end: datetime, remaining: Decimal) -> Decimal:
    """All time saved: Laytime 종료부터 (남은 Laytime 이 소진되었을) 만료 예정 시점까지의 달력 시간."""
    horizon = end + timedelta(minutes=float(remaining) * 3 + 60 * 24 * 60)
    periods = excepted_periods(c, end, horizon)
    points = sorted({p for per in periods for p in per[:2] if p > end})
    t, rem = end, remaining
    while rem > 0:
        in_exc = any(ps <= t < pe for ps, pe, _ in periods)
        nxt = next((p for p in points if p > t), None)
        if in_exc:
            t = nxt
            continue
        span = Decimal(_minutes(t, nxt)) if nxt else None
        if span is None or span >= rem:
            t = t + timedelta(minutes=float(rem))
            rem = D0
        else:
            rem -= span
            t = nxt
    return Decimal(str((t - end).total_seconds() / 60))


def _first(events, code):
    return next((e for e in events if e["event_type"] == code), None)


def _last(events, code):
    hits = [e for e in events if e["event_type"] == code]
    return hits[-1] if hits else None


def calculate(c: dict, events: list[dict], overrides: dict | None = None) -> dict:
    """Laytime 계산.

    events: [{"start": datetime, "end": datetime|None, "event_type": str, "description": str, "remarks": str}]
    overrides: {segment_key: {"pct": float, "reason": str}}  — "검토 필요" 행에 대한 사용자 판단
    """
    overrides = overrides or {}
    notes: list[tuple[str, str]] = []  # (level: info|warning|error, message)
    evs = sorted((e for e in events if e.get("start")), key=lambda e: e["start"])
    allowed = allowed_minutes(c)
    terms_label = LAYTIME_TERMS.get(c["laytime_terms"], c["laytime_terms"])
    cl_laytime = c.get("clause_laytime") or ""
    cl_nor = c.get("clause_nor") or ""
    cl_dem = c.get("clause_demurrage") or ""

    def ref(clause: str, text: str) -> str:
        return f"{clause} {text}".strip()

    laycan_start = parse_dt(c.get("laycan_start"))
    laycan_end = parse_dt(c.get("laycan_end"))

    # 1) Laytime 개시 ---------------------------------------------------------
    nor = _first(evs, "NOR_TENDERED")["start"]
    extra_review = 0
    nors = [e["start"] for e in evs if e["event_type"] == "NOR_TENDERED"]
    if len(nors) > 1:
        extra_review += 1
        notes.append(("warning", f"NOR 제출이 {len(nors)}건({', '.join(fmt_dt(n) for n in nors)})입니다 — 첫 NOR 기준으로 계산했습니다. "
                                 "재제출 NOR 이 유효한 경우 무효 NOR 행을 표에서 삭제하세요. [검토 필요]"))
    eff_nor = nor
    commence_basis = ref(cl_nor, "NOR 제출")
    early_nor = bool(laycan_start and nor < laycan_start and not c.get("nor_before_laycan_counts"))
    early_mode = c.get("nor_early_mode", "NOT_BEFORE_LAYCAN")
    if early_nor and early_mode == "DEEMED_AT_LAYCAN":
        eff_nor = laycan_start
        commence_basis = ref(cl_nor, "NOR 은 Laycan 개시 시점에 제출된 것으로 간주")
        notes.append(("warning", f"NOR({fmt_dt(nor)})이 Laycan 시작({fmt_dt(laycan_start)}) 이전 제출 → Laycan 시작 시점에 제출된 것으로 보고 Notice time 을 적용했습니다."))
    if laycan_end and nor > laycan_end:
        notes.append(("warning", f"NOR({fmt_dt(nor)})이 Laycan 종료({fmt_dt(laycan_end)}) 이후입니다. 계약 해제/수리 여부를 검토하세요."))
    if c["berth_terms"] == "BERTH":
        af = _first(evs, "ALL_FAST")
        if af and af["start"] > eff_nor:
            eff_nor = af["start"]
            commence_basis = ref(cl_nor, "Berth charter — 접안 완료 시점에 NOR 유효")
            notes.append(("info", "Berth charter 조건으로 접안 완료(All fast) 시점부터 NOR 유효로 처리했습니다."))
        elif not af:
            notes.append(("warning", "Berth charter 조건이나 접안 완료(All fast) 이벤트가 없습니다."))
    if c["berth_terms"] == "WIFPON":
        fp = _first(evs, "FREE_PRATIQUE")
        if fp and fp["start"] > nor:
            notes.append(("warning", "WIFPON 조건: 검역 완료가 NOR 이후입니다. NOR 유효성(검역 조건)을 검토하세요."))

    notice_min = int((_dec(c.get("notice_hours")) * 60).quantize(Decimal(1), ROUND_HALF_UP))
    commence = eff_nor + timedelta(minutes=notice_min)
    commence_basis += f" + Notice time {c.get('notice_hours')}h"
    if early_nor and early_mode == "NOT_BEFORE_LAYCAN":
        if commence < laycan_start:
            commence = laycan_start
            commence_basis = ref(cl_nor, "Laytime 은 Laycan 개시 전 기산 불가 → Laycan 시작")
        notes.append(("warning", f"NOR({fmt_dt(nor)})이 Laycan 시작({fmt_dt(laycan_start)}) 이전 제출 → NOR+Notice time 과 Laycan 시작 중 늦은 시점({fmt_dt(commence)})부터 기산했습니다."))
    ops_start = _first(evs, "COMMENCED")["start"]
    ops_end = _last(evs, "COMPLETED")["start"]
    if c.get("commence_if_sooner") and ops_start < commence:
        floor = laycan_start if (laycan_start and not c.get("nor_before_laycan_counts")) else None
        sooner = max(ops_start, floor) if floor else ops_start
        if sooner < commence:
            commence = sooner
            commence_basis = ref(cl_nor, "Notice time 만료 전 하역 개시 → 실제 개시 시점")
            notes.append(("info", "Notice time 만료 전에 하역이 개시되어 실제 개시 시점부터 기산했습니다 (unless sooner commenced)."))

    # 2) Laytime 종료 ---------------------------------------------------------
    end_ev = _last(evs, c["laytime_end_event"])
    if not end_ev:
        end_ev = _last(evs, "COMPLETED")
        notes.append(("warning", "Laytime 종료 이벤트가 없어 하역 완료 시점으로 종료했습니다."))
    end = end_ev["start"]

    rows: list[dict] = []
    if nor < commence:
        rows.append(_row(nor, commence, Decimal(_minutes(nor, commence)), D0, D0, commence_basis, "Laytime 개시 전 (미반영)", STATUS_INFO))

    intervals = [e for e in evs if e["event_type"] in INTERVAL_EVENTS and e.get("end") and e["end"] > e["start"]]
    periods = excepted_periods(c, commence, end) if end > commence else []

    if end <= commence:
        extra_review += 1
        notes.append(("warning", f"Laytime 종료({fmt_dt(end)})가 Laytime 개시({fmt_dt(commence)}) 이전/동시입니다 — "
                                 "Time used 0 으로 계산했습니다. 계약상 처리(전량 Despatch 여부)를 검토하세요. [검토 필요]"))
    points = {commence, end, ops_start, ops_end}
    for iv in intervals:
        points.update((iv["start"], iv["end"]))
    for ps, pe, _ in periods:
        points.update((ps, pe))
    bounds = sorted(p for p in points if commence <= p <= end)
    segments = list(zip(bounds[:-1], bounds[1:]))

    def is_working(s, e):
        return ops_start <= s and e <= ops_end and not any(iv["start"] <= s and iv["end"] >= e for iv in intervals)

    cum = D0
    expiry: datetime | None = None
    expire_at: datetime | None = None  # 만료 시점으로 분할한 경계
    i = 0
    while i < len(segments):
        s, e = segments[i]
        dur = _minutes(s, e)
        if dur <= 0:
            i += 1
            continue
        on_dem = cum >= allowed
        active = [iv for iv in intervals if iv["start"] <= s and iv["end"] >= e]
        in_exc = [p for p in periods if p[0] <= s and p[1] >= e]

        cands: list[tuple[Decimal, str, str, bool]] = []  # (pct, 조항, 비고, 검토필요)
        for iv in active:
            code = iv["event_type"]
            key = INTERVAL_EVENTS[code]
            desc = iv.get("description") or EVENT_TYPES[code]
            if key is None:
                cands.append((D100, "", f"{desc} — 계약 근거 없음, 반영 여부 판단 필요", True))
                continue
            rule = c["exceptions"][key]
            label = EXCEPTION_LABELS[key]
            if rule.get("applies"):
                cands.append((_dec(rule.get("counted_pct")), rule.get("clause") or label, f"{desc} (예외: {label})", False))
            else:
                cands.append((D100, ref(cl_laytime, terms_label), f"{desc} — 계약상 예외 아님 (계속 반영)", False))
        for ps, pe, plabel in in_exc:
            if c["excepted_used"] == "UU" and is_working(s, e):
                cands.append((D100, ref(cl_laytime, f"{c['laytime_terms']} UU"), f"{plabel} 중 하역 (UU)", False))
            else:
                tag = "EIU" if c["excepted_used"] == "EIU" else "미사용"
                cands.append((D0, ref(cl_laytime, f"{c['laytime_terms']} {tag}"), f"{plabel} 제외", False))

        if cands:
            pct = min(x[0] for x in cands)
            clause = " / ".join(dict.fromkeys(x[1] for x in cands if x[1]))
            remark = " / ".join(x[2] for x in cands)
            review = any(x[3] for x in cands)
            if len(active) > 1:
                review = True
                remark += " — 예외 중복 (이중 공제 방지: 최저 반영률 1회 적용)"
        else:
            pct, clause, remark, review = D100, ref(cl_laytime, terms_label), "", False

        if on_dem and c.get("oodaod"):
            if pct < D100:
                remark = f"OODAOD — 체선 중 예외 미적용 (원래: {remark})"
                if any(iv["event_type"] == "BREAKDOWN_SHIP" for iv in active):
                    review = True
                    remark += " — 선박 귀책 고장은 체선 중에도 제외될 수 있음"
            pct = D100
            clause = ref(cl_dem, "Once on demurrage, always on demurrage")

        auto_pct = pct
        status = STATUS_REVIEW if review else STATUS_OK
        key = segment_key(s, e)
        if key in overrides and overrides[key].get("pct") is not None:
            pct = _dec(overrides[key]["pct"])
            status = STATUS_USER
            reason = overrides[key].get("reason") or ""
            remark = f"{remark} — 사용자 판단 {pct}%" + (f": {reason}" if reason else "")

        counted = Decimal(dur) * pct / D100
        # Laytime 만료 시점에서 구간 분할 (체선 진입 시점 표시 + OODAOD 적용 경계).
        # 만료 시점은 분 단위로 맞추고, 만료까지의 반영시간은 Allowed 와 정확히 같게 한다
        # (비정수 반영률의 반올림 잔차 때문에 체선 진입이 누락되지 않도록).
        if not on_dem and pct > 0 and cum + counted >= allowed:
            split = int(((allowed - cum) * D100 / pct).quantize(Decimal(1), ROUND_HALF_UP))
            if split <= 0:  # 잔여 Laytime 이 1분 미만 → 이 구간 시작 시점에 만료
                cum, expiry = allowed, s
                continue
            if split < dur:
                mid = s + timedelta(minutes=split)
                segments[i : i + 1] = [(s, mid), (mid, e)]
                expire_at = mid
                continue
            expire_at = e
        if expire_at is not None and e == expire_at and not on_dem:
            counted = allowed - cum

        cum += counted
        if expiry is None and cum >= allowed:
            expiry = s if on_dem else e
        row = _row(s, e, Decimal(dur), pct, counted, clause, remark, status, cum=cum, auto_pct=auto_pct)
        row["on_demurrage"] = on_dem
        rows.append(row)
        i += 1

    # 3) 결과 ----------------------------------------------------------------
    used = cum
    dem_rate = _dec(c["demurrage_rate"])
    des_rate = despatch_rate(c)
    if used > allowed:
        kind, diff, rate = "DEMURRAGE", used - allowed, dem_rate
    elif used < allowed:
        kind, rate = "DESPATCH", des_rate
        if c["despatch_basis"] == "ATS":
            diff = _ats_saved(c, end, allowed - used)
        else:
            diff = allowed - used
    else:
        kind, diff, rate = "NIL", D0, D0
    amount = (rate * diff / D1440).quantize(CENT, ROUND_HALF_UP)
    if kind == "DESPATCH" and rate == 0:
        notes.append(("warning", "Despatch 요율이 0 이라 조출료가 USD 0.00 입니다. 계약(free despatch 여부)을 확인하세요."))

    review_count = sum(1 for r in rows if r["status"] == STATUS_REVIEW) + extra_review
    if review_count:
        notes.append(("warning", f"'검토 필요' 항목 {review_count}건 — 사용자 판단 입력 후 확정하세요."))

    return {
        "allowed": allowed,
        "used": used,
        "diff": diff,
        "kind": kind,
        "rate": rate,
        "demurrage_rate": dem_rate,
        "despatch_rate": des_rate,
        "amount": amount,
        "nor": nor,
        "eff_nor": eff_nor,
        "commence": commence,
        "commence_basis": commence_basis,
        "end": end,
        "expiry": expiry,
        "rows": rows,
        "notes": notes,
        "review_count": review_count,
    }


def _row(s, e, dur, pct, counted, clause, remark, status, cum=None, auto_pct=None) -> dict:
    return {
        "from": s,
        "to": e,
        "duration": dur,
        "pct": pct,
        "auto_pct": pct if auto_pct is None else auto_pct,
        "counted": counted,
        "cumulative": cum,
        "clause": clause,
        "remarks": remark,
        "status": status,
        "key": segment_key(s, e),
        "on_demurrage": False,
    }
