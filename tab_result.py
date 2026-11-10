"""기능 3. Laytime Calculation 결과 화면."""
import pandas as pd
import streamlit as st

from core.contract import missing_fields
from core.engine import STATUS_REVIEW, STATUS_USER, calculate
from core.timeutil import fmt_dt, fmt_hhmm, fmt_minutes, to_days
from export.excel import build_excel
from export.report import KIND_LABEL, TIMESHEET_COLUMNS, timesheet_rows

from .style import ROW_COLORS, legend, result_hero, section


def _style_rows(df: pd.DataFrame, rows: list[dict]):
    def color(row):
        r = rows[row.name]
        if r["status"] == STATUS_REVIEW:
            css = f"background-color: {ROW_COLORS['review']}"
        elif r["status"] == STATUS_USER:
            css = f"background-color: {ROW_COLORS['user']}"
        elif r["on_demurrage"]:
            css = f"background-color: {ROW_COLORS['dem']}"
        elif r["pct"] == 0:
            css = "color: #8a8a8a"
        else:
            css = ""
        return [css] * len(row)

    return df.style.apply(color, axis=1)


def _review_editor(result: dict) -> bool:
    """검토 필요/사용자 판단 행 편집. 변경 시 True."""
    rows = [r for r in result["rows"] if r["status"] in (STATUS_REVIEW, STATUS_USER)]
    if not rows:
        return False
    overrides = st.session_state["overrides"]
    pending = sum(1 for r in rows if r["status"] == STATUS_REVIEW)
    section(f"⚠️ 검토 필요 — 미확정 {pending}건 / 전체 {len(rows)}건",
            "반영률(%)과 판단 근거를 입력하면 해당 구간에 적용해 바로 재계산합니다. 비워두면 엔진 기본값이 유지되고 '검토 필요'로 남습니다.")
    df = pd.DataFrame(
        [
            {
                "key": r["key"],
                "구간": f"{fmt_dt(r['from'])} ~ {fmt_dt(r['to'])}",
                "경과": fmt_hhmm(r["duration"]),
                "사유": r["remarks"].split(" — 사용자 판단")[0],
                "엔진 반영률(%)": float(r["auto_pct"]),
                "사용자 반영률(%)": overrides.get(r["key"], {}).get("pct"),
                "판단 근거": overrides.get(r["key"], {}).get("reason", ""),
            }
            for r in rows
        ]
    )
    df["사용자 반영률(%)"] = df["사용자 반영률(%)"].astype("float")
    edited = st.data_editor(
        df,
        key="review_editor_" + str(abs(hash(tuple(df["key"])))),
        hide_index=True,
        width="stretch",
        disabled=["구간", "경과", "사유", "엔진 반영률(%)"],
        column_config={
            "key": None,
            "사용자 반영률(%)": st.column_config.NumberColumn(min_value=0, max_value=100, step=10),
            "판단 근거": st.column_config.TextColumn(width="large"),
        },
    )
    changed = False
    for _, row in edited.iterrows():
        k = row["key"]
        pct = row["사용자 반영률(%)"]
        reason = "" if pd.isna(row["판단 근거"]) else str(row["판단 근거"])
        new = {"pct": round(float(pct), 4), "reason": reason} if not pd.isna(pct) else None
        if new != overrides.get(k):
            if new is None:
                overrides.pop(k, None)
            else:
                overrides[k] = new
            changed = True
    return changed


def _blocked(title: str, items: list[str], hint: str):
    with st.container(border=True):
        section(title)
        for it in items:
            st.markdown(f"- {it}")
        st.caption(hint)


def render(contract: dict, events: list[dict], errors: list[str]) -> dict | None:
    missing = missing_fields(contract)
    if missing:
        _blocked("❌ 계약 조건 필수 항목이 누락되어 계산할 수 없습니다", missing, "① 계약 조건 탭에서 입력하세요.")
        return None
    if not events:
        _blocked("SOF 이벤트가 없습니다", ["NOR 제출 · 하역 개시 · 하역 완료 이벤트가 필요합니다."],
                 "② NOR / SOF 탭에서 입력하거나 사이드바의 샘플을 불러오세요.")
        return None
    if errors:
        _blocked("❌ SOF 이벤트 검증 오류로 계산할 수 없습니다", errors, "② NOR / SOF 탭에서 수정하세요.")
        return None

    try:
        result = calculate(contract, events, st.session_state["overrides"])
    except Exception as exc:  # pragma: no cover
        st.exception(exc)
        return None

    kind = result["kind"]
    party = contract.get("counterparty") or "정산 대상"
    if kind == "DEMURRAGE":
        hero_state, direction = "err", f"지급 — 당사 → {party} (Laytime 초과)"
    elif kind == "DESPATCH":
        hero_state, direction = "ok", f"수취 — {party} → 당사 (Laytime 절약, {contract['despatch_basis']})"
    else:
        hero_state, direction = "idle", "Laytime 과 사용 시간이 같습니다"
    if result["review_count"]:
        direction += f" · ⚠️ 검토 필요 {result['review_count']}건 미확정 (금액 변동 가능)"

    left, right = st.columns([1.15, 2], vertical_alignment="center")
    with left:
        result_hero(KIND_LABEL[kind], f"USD {result['amount']:,.2f}", direction, hero_state)
    with right:
        label = "Time on Demurrage" if kind == "DEMURRAGE" else f"Time Saved ({contract['despatch_basis']})"
        metrics = [
            ("Allowed Laytime", fmt_minutes(result["allowed"]), f"{to_days(result['allowed'])} days"),
            ("Time Used", fmt_minutes(result["used"]), f"{to_days(result['used'])} days"),
            (label, fmt_minutes(result["diff"]), f"{to_days(result['diff'])} days"),
            ("적용 요율 (USD/day)", f"{result['rate']:,.2f}", "pro rata"),
        ]
        for row in (metrics[:2], metrics[2:]):
            cols = st.columns(2)
            for col, (lab, val, sub) in zip(cols, row):
                col.metric(lab, val, sub, delta_color="off", delta_arrow="off", border=True)

    st.markdown(
        f"**NOR** {fmt_dt(result['nor'])} → **개시** {fmt_dt(result['commence'])} "
        f"<span class='lt-muted'>({result['commence_basis']})</span> → **종료** {fmt_dt(result['end'])}"
        + (f" · **체선 진입** {fmt_dt(result['expiry'])}" if result["expiry"] else ""),
        unsafe_allow_html=True,
    )
    notes = result["notes"]
    if notes:
        n_warn = sum(1 for lv, _ in notes if lv == "warning")
        with st.expander(f"계산 메모 {len(notes)}건" + (f" · ⚠️ {n_warn}건" if n_warn else ""), expanded=bool(n_warn)):
            for level, msg in notes:
                getattr(st, level if level in ("info", "warning", "error") else "info")(msg)

    if _review_editor(result):
        st.rerun()

    with st.container(border=True):
        section("상세 Time Sheet", "1일 = 24시간 · 금액 = 요율 × 분 / 1,440 (pro rata) · 최종 금액에서 USD 0.01 반올림 1회")
        df = pd.DataFrame(timesheet_rows(result), columns=TIMESHEET_COLUMNS)
        st.dataframe(_style_rows(df, result["rows"]), hide_index=True, width="stretch",
                     height=min(40 + 35 * len(df), 700),
                     column_config={
                         "상태": st.column_config.TextColumn(width=74),
                         "From": st.column_config.TextColumn(width=112),
                         "To": st.column_config.TextColumn(width=112),
                         "경과시간": st.column_config.TextColumn(width=62),
                         "반영률(%)": st.column_config.TextColumn(width=62),
                         "반영시간": st.column_config.TextColumn(width=62),
                         "누적 사용": st.column_config.TextColumn(width=78),
                         "적용 조항": st.column_config.TextColumn(width=165),
                         "비고": st.column_config.TextColumn(width=320),
                     })
        legend()

    with st.container(border=True):
        section("출력")
        name = f"Laytime_Statement_{(contract.get('vessel') or 'vessel').replace(' ', '_')}_{contract['port_type']}"
        b, w = st.columns([1, 2], vertical_alignment="center")
        b.download_button(
            "📊 Excel 다운로드",
            build_excel(contract, result, events),
            file_name=f"{name}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            width="stretch",
        )
        if result["review_count"]:
            w.warning(f"검토 필요 {result['review_count']}건이 남아 있습니다. 출력물에도 '검토 필요'로 표시됩니다.")
        else:
            w.caption("시트 구성: Laytime Statement (송부용 · A4 가로 인쇄) / Contract (적용 계약 조건) / SOF Events (확정 이벤트)")
    return result
