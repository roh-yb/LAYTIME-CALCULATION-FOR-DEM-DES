"""결과 표 데이터 (화면/Excel 공통)."""
from core.constants import BASIS_LABELS, BERTH_TERMS, DESPATCH_BASIS, EXCEPTION_LABELS, LAYTIME_END_EVENTS, LAYTIME_TERMS, NOR_EARLY_MODES
from core.timeutil import fmt_dt, fmt_hhmm, fmt_minutes

KIND_LABEL = {"DEMURRAGE": "Demurrage (체선료)", "DESPATCH": "Despatch (조출료)", "NIL": "해당 없음"}


# 상태를 맨 앞에 둔다 (좁은 화면에서도 가로 스크롤 없이 검토 필요 여부가 보이도록)
TIMESHEET_COLUMNS = ["상태", "From", "To", "경과시간", "반영률(%)", "반영시간", "누적 사용", "적용 조항", "비고"]


def timesheet_rows(r: dict) -> list[list]:
    out = []
    for row in r["rows"]:
        out.append(
            [
                row["status"],
                fmt_dt(row["from"]),
                fmt_dt(row["to"]),
                fmt_hhmm(row["duration"]),
                f"{row['pct']:g}",
                fmt_hhmm(row["counted"]),
                fmt_minutes(row["cumulative"]) if row["cumulative"] is not None else "",
                row["clause"],
                ("[DEMURRAGE] " if row["on_demurrage"] else "") + row["remarks"],
            ]
        )
    return out


def contract_rows(c: dict) -> list[tuple[str, str]]:
    rows = [
        ("정산 기준", BASIS_LABELS[c["basis"]]),
        ("정산 대상", c.get("counterparty") or ""),
        ("항 구분", c["port_type"]),
        ("Laytime 기준", LAYTIME_TERMS[c["laytime_terms"]] + ("" if c["laytime_terms"] == "SHINC" else f" / {c['excepted_used']}")),
        ("Despatch 기준", DESPATCH_BASIS[c["despatch_basis"]]),
        ("Notice time (h)", str(c["notice_hours"])),
        ("Unless sooner commenced", "Yes" if c["commence_if_sooner"] else "No"),
        ("Laycan 이전 기산 허용", "Yes" if c["nor_before_laycan_counts"] else "No"),
        ("Laycan 이전 NOR 처리", NOR_EARLY_MODES.get(c.get("nor_early_mode"), "")),
        ("Berth 조건", BERTH_TERMS[c["berth_terms"]]),
        ("Laytime 종료", LAYTIME_END_EVENTS[c["laytime_end_event"]]),
        ("OODAOD", "Yes" if c["oodaod"] else "No"),
        ("NOR 조건", c.get("nor_condition") or ""),
    ]
    for k, rule in c["exceptions"].items():
        txt = f"제외 (반영 {rule['counted_pct']:g}%) {rule.get('clause') or ''}" if rule["applies"] else "예외 아님 (계속 반영)"
        rows.append((f"예외: {EXCEPTION_LABELS[k]}", txt))
    if c.get("holidays"):
        rows.append(("적용 휴일", ", ".join(f"{h['date']} {h.get('name', '')}" for h in c["holidays"])))
    return rows
