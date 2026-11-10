"""기능 1. 계약 조건 체크리스트."""
import pandas as pd
import streamlit as st

from ai import client as ai_client
from ai.extract import file_to_payload
from ai.parsers import parse_contract
from core.constants import (
    ALLOWED_ROUNDING,
    BASIS_LABELS,
    BERTH_TERMS,
    COUNTERPARTIES,
    DESPATCH_BASIS,
    DOW_KR,
    EXCEPTED_USED,
    EXCEPTION_LABELS,
    LAYTIME_END_EVENTS,
    LAYTIME_TERMS,
    NOR_EARLY_MODES,
    match_counterparty,
)
from core.contract import required_status

from .state import contract_to_state, queue_state, record_ai_error, record_usage, state_to_contract
from .style import section


def _meta(key):
    ai = st.session_state.get("ai_contract") or {}
    return (ai.get("meta") or {}).get(key)


def _lbl(key, text):
    m = _meta(key)
    if m and m.get("needs_review"):
        return f"{text} ⚠️"
    return text


def _help(key):
    m = _meta(key)
    if not m:
        return None
    src = m.get("source_clause") or "(원문에서 찾지 못함)"
    flag = " · 검토 필요" if m.get("needs_review") else ""
    return f"AI 근거: {src}\n\n신뢰도: {m.get('confidence') or '-'}{flag}"


def _ai_section():
    with st.expander("🤖 계약서 원문으로 체크리스트 자동 채우기 (AI)", expanded=False):
        if not ai_client.is_available():
            st.info("OPENAI_API_KEY 가 설정되지 않아 AI 기능을 사용할 수 없습니다. `.env` 또는 Streamlit Secrets 를 확인하세요. (수동 입력은 가능)")
            return
        text = st.text_area("계약서 원문 (CP / 구매계약 Laytime·Demurrage 조항)", height=220, key="contract_raw_text")
        up = st.file_uploader("또는 계약서 파일 (PDF / TXT)", type=["pdf", "txt"], key="contract_file")
        st.caption("⚠️ 입력한 계약서 내용은 OpenAI API 로 전송됩니다.")
        if st.button("AI 분석 실행", type="primary", key="btn_ai_contract"):
            images = []
            body = text or ""
            if up is not None:
                ftext, images = file_to_payload(up.name, up.getvalue())
                body = (body + "\n\n" + ftext).strip()
            if not body and not images:
                st.warning("계약서 원문을 입력하거나 파일을 업로드하세요.")
                return
            try:
                with st.spinner("조체선료 분석 모델로 계약 조항 해석 중…"):
                    result = parse_contract(body, images)
            except Exception as exc:
                record_ai_error(exc)
                st.error(f"AI 분석 실패: {exc}")
                return
            record_usage(result["usage"])
            st.session_state["ai_contract"] = result
            current = state_to_contract()
            current.update(result["values"])
            for ek, rule in result["exceptions"].items():
                current["exceptions"][ek].update(rule)
            queue_state(contract_to_state(current))

    ai = st.session_state.get("ai_contract")
    if ai:
        n_review = sum(1 for m in ai["meta"].values() if m.get("needs_review"))
        st.success(f"AI 가 체크리스트를 채웠습니다. ⚠️ 표시 항목 {n_review}건은 원문과 대조하세요. (항목 옆 ? 아이콘 = 근거 조항)")
        if ai.get("summary"):
            st.caption(f"AI 요약: {ai['summary']}")
        with st.expander(f"AI 추출 근거 ({len(ai['meta'])}개 항목 · 검토 필요 {n_review}건)"):
            rows = sorted(
                (
                    {
                        "검토": "⚠️" if m.get("needs_review") else "",
                        "항목": k,
                        "값": "" if m.get("value") is None else str(m.get("value")),
                        "신뢰도": m.get("confidence") or "",
                        "원문 근거": m.get("source_clause") or "(원문에서 찾지 못함)",
                    }
                    for k, m in ai["meta"].items()
                ),
                key=lambda r: (r["검토"] == "", r["항목"]),
            )
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            if st.button("AI 결과 표시 지우기"):
                st.session_state["ai_contract"] = None
                st.rerun()


def _status_banner(contract: dict):
    filled, total, missing = required_status(contract)
    if missing:
        st.warning(f"필수 항목 {filled}/{total} 입력 — 누락: {', '.join(missing)}. 누락이 있으면 정산을 계산하지 않습니다.")
    else:
        st.success(f"필수 항목 {total}/{total} 입력 완료 — ② NOR / SOF 탭으로 이동하세요.")


def render() -> dict:
    ss = st.session_state
    _status_banner(state_to_contract())
    _ai_section()

    with st.container(border=True):
        section("기본 정보")
        c1, c2, c3, c4 = st.columns(4)
        c1.radio(_lbl("basis", "정산 기준"), list(BASIS_LABELS), key="c_basis", horizontal=True,
                 format_func=BASIS_LABELS.get, help=_help("basis"))
        c2.radio(_lbl("port_type", "항 구분"), ["LOAD", "DISCH"], key="c_port_type", horizontal=True,
                 format_func=lambda x: "선적항" if x == "LOAD" else "양하항", help=_help("port_type"))
        c3.text_input(_lbl("vessel", "선박명"), key="c_vessel", help=_help("vessel"))
        # 정산 기준이 바뀌거나 템플릿·AI 값이 목록에 없으면 목록 항목으로 맞추고, 못 맞추면 비워 다시 선택하게 한다
        options = COUNTERPARTIES[ss["c_basis"]]
        if ss.get("c_counterparty") not in options:
            ss["c_counterparty"] = match_counterparty(ss.get("c_counterparty"), ss["c_basis"])
        c4.selectbox(
            _lbl("counterparty", "정산 대상 (선사)" if ss["c_basis"] == "CP" else "정산 대상 (공급사)"),
            options, key="c_counterparty", placeholder="선택하세요",
            help=_help("counterparty") or ("Charter Party: 선사 중 선택" if ss["c_basis"] == "CP" else "구매계약: 공급사 중 선택"),
        )
        c1, c2, c3, c4 = st.columns(4)
        c1.text_input(_lbl("port", "항구명"), key="c_port", help=_help("port"))
        c2.text_input(_lbl("country", "국가 코드 (휴일 캘린더)"), key="c_country", max_chars=2,
                      help=_help("country") or "ISO 2자리 코드 (KR, AU, BR …)")
        with c3:
            a, b = st.columns([3, 2])
            a.date_input(_lbl("laycan_start", "Laycan 시작 *"), key="c_laycan_start_date", help=_help("laycan_start"))
            b.time_input("시각", key="c_laycan_start_time", step=60)
        with c4:
            a, b = st.columns([3, 2])
            a.date_input(_lbl("laycan_end", "Laycan 종료 *"), key="c_laycan_end_date", help=_help("laycan_end"))
            b.time_input("시각 ", key="c_laycan_end_time", step=60)

    # 주의: 조건에 따라 위젯을 숨기면(if 로 생략) Streamlit 이 그 위젯의 session_state 값을 지운다.
    # 다시 나타날 때 기본값(현재 시각·0·첫 항목)으로 생성되어 계산이 조용히 틀어지므로(REVIEW C1),
    # 조건부 입력칸은 항상 렌더링하고 해당 없을 때 disabled 로만 처리한다.
    with st.container(border=True):
        section("Laytime")
        c1, c2, c3, c4 = st.columns(4)
        c1.radio(_lbl("laytime_mode", "Laytime 산정 방식"), ["RATE", "FIXED"], key="c_laytime_mode", horizontal=True,
                 format_func=lambda x: "하역률" if x == "RATE" else "고정 Laytime", help=_help("laytime_mode"))
        rate_mode = ss["c_laytime_mode"] == "RATE"
        c2.number_input(_lbl("cargo_qty", "화물량 (B/L, MT)" + (" *" if rate_mode else "")), min_value=0.0, step=1000.0,
                        format="%.3f", key="c_cargo_qty", help=_help("cargo_qty"))
        c3.number_input(_lbl("rate_mt_day", "하역률 (MT/day)" + (" *" if rate_mode else "")), min_value=0.0, step=1000.0,
                        format="%.2f", key="c_rate_mt_day", disabled=not rate_mode, help=_help("rate_mt_day"))
        c4.number_input(_lbl("fixed_laytime_hours", "고정 Laytime (시간)" + ("" if rate_mode else " *")), min_value=0.0,
                        step=1.0, key="c_fixed_laytime_hours", disabled=rate_mode, help=_help("fixed_laytime_hours"))

        shinc = ss["c_laytime_terms"] == "SHINC"
        c1, c2, c3, c4 = st.columns(4)
        c1.selectbox(_lbl("laytime_terms", "Laytime 기준"), list(LAYTIME_TERMS), key="c_laytime_terms",
                     format_func=LAYTIME_TERMS.get, help=_help("laytime_terms"))
        c2.selectbox(_lbl("excepted_used", "제외기간 중 하역 시"), list(EXCEPTED_USED), key="c_excepted_used",
                     format_func=EXCEPTED_USED.get, disabled=shinc, help=_help("excepted_used"))
        with c3:
            a, b = st.columns(2)
            a.selectbox("주말 시작 요일", range(7), key="c_weekend_start_dow", format_func=lambda i: DOW_KR[i], disabled=shinc)
            b.time_input("시작 시각", key="c_weekend_start_time", step=60, disabled=shinc)
        with c4:
            a, b = st.columns(2)
            a.selectbox("주말 종료 요일", range(7), key="c_weekend_end_dow", format_func=lambda i: DOW_KR[i], disabled=shinc)
            b.time_input("종료 시각", key="c_weekend_end_time", step=60, disabled=shinc)
        c1, c2 = st.columns([1, 3], vertical_alignment="bottom")
        c1.selectbox("Allowed Laytime 소수점 처리", list(ALLOWED_ROUNDING), key="c_allowed_rounding", format_func=ALLOWED_ROUNDING.get)
        if shinc:
            c2.caption("SHINC — 주말·휴일 모두 Laytime 에 포함 (주말·UU/EIU 설정은 SHEX/SSHEX 에서 사용)")
        else:
            c2.caption("SHEX 예: 일 00:00 ~ 월 00:00 / 토 12:00 ~ 월 08:00 · SSHEX 예: 토 00:00 ~ 월 00:00 · "
                       "휴일은 ② 탭 휴일 캘린더 기준 (해당일 00:00~24:00)")

    with st.container(border=True):
        section("요율")
        ratio_mode = ss["c_despatch_mode"] == "RATIO"
        c1, c2, c3, c4, c5 = st.columns([1.1, 1.3, 1, 1, 1.1])
        c1.number_input(_lbl("demurrage_rate", "Demurrage 요율 (USD/day) *"), min_value=0.0, step=500.0, format="%.2f",
                        key="c_demurrage_rate", help=_help("demurrage_rate"))
        c2.radio(_lbl("despatch_mode", "Despatch 요율 방식"), ["RATIO", "AMOUNT"], key="c_despatch_mode", horizontal=True,
                 format_func=lambda x: "Demurrage 대비 비율" if x == "RATIO" else "금액 직접 입력", help=_help("despatch_mode"))
        c3.number_input(_lbl("despatch_ratio", "Despatch 비율 (0.5 = 1/2)" + (" *" if ratio_mode else "")), min_value=0.0,
                        max_value=1.0, step=0.05, key="c_despatch_ratio", disabled=not ratio_mode, help=_help("despatch_ratio"))
        c4.number_input(_lbl("despatch_rate", "Despatch 요율 (USD/day)" + ("" if ratio_mode else " *")), min_value=0.0,
                        step=500.0, format="%.2f", key="c_despatch_rate", disabled=ratio_mode, help=_help("despatch_rate"))
        c5.selectbox(_lbl("despatch_basis", "Despatch 기준"), list(DESPATCH_BASIS), key="c_despatch_basis",
                     format_func=DESPATCH_BASIS.get, help=_help("despatch_basis"))

    with st.container(border=True):
        section("NOR · Berth · 종료")
        c1, c2, c3, c4 = st.columns(4)
        c1.number_input(_lbl("notice_hours", "Notice time (NOR + 시간) *"), min_value=0.0, step=1.0, key="c_notice_hours",
                        help=_help("notice_hours"))
        c2.selectbox(_lbl("berth_terms", "Berth 조건"), list(BERTH_TERMS), key="c_berth_terms", format_func=BERTH_TERMS.get,
                     help=_help("berth_terms"))
        c3.selectbox(_lbl("laytime_end_event", "Laytime 종료 시점"), list(LAYTIME_END_EVENTS), key="c_laytime_end_event",
                     format_func=LAYTIME_END_EVENTS.get, help=_help("laytime_end_event"))
        c4.text_input(_lbl("nor_condition", "NOR 유효 조건 (메모)"), key="c_nor_condition",
                      help=_help("nor_condition") or "예: ATDNSHINC, WIBON, whether in free pratique or not")
        c1, c2, c3 = st.columns(3)
        c1.checkbox(_lbl("commence_if_sooner", "Notice time 중 하역 개시 시 실제 시점부터 기산 (unless sooner commenced)"),
                    key="c_commence_if_sooner", help=_help("commence_if_sooner"))
        c2.checkbox(_lbl("nor_before_laycan_counts", "Laycan 이전 NOR 시 Laycan 전부터 기산 허용"),
                    key="c_nor_before_laycan_counts", help=_help("nor_before_laycan_counts"))
        c3.checkbox(_lbl("oodaod", "Once on demurrage, always on demurrage"), key="c_oodaod", help=_help("oodaod"))
        st.selectbox(_lbl("nor_early_mode", "Laycan 이전 NOR 제출 시 Laytime 개시"), list(NOR_EARLY_MODES),
                     key="c_nor_early_mode", format_func=NOR_EARLY_MODES.get, disabled=ss["c_nor_before_laycan_counts"],
                     help=_help("nor_early_mode") or "'Laycan 전부터 기산 허용'을 체크하면 사용하지 않습니다.")

    with st.container(border=True):
        section("예외 항목", "체크 = 해당 시간을 Laytime 에서 제외 · 반영률 = 제외 구간 중 여전히 Laytime 으로 계산할 비율 "
                         "(0% = 전부 제외, 50% = 절반 반영)")
        h = st.columns([3, 1.3, 1.2, 3])
        for col, text in zip(h, ("**항목**", "**제외 적용**", "**반영률 %**", "**근거 조항**")):
            col.markdown(text)
        for ek, label in EXCEPTION_LABELS.items():
            cols = st.columns([3, 1.3, 1.2, 3], vertical_alignment="center")
            cols[0].markdown(_lbl(f"exc_{ek}", label), help=_help(f"exc_{ek}"))
            cols[1].checkbox("적용", key=f"x_{ek}_applies", label_visibility="collapsed")
            cols[2].number_input("반영률", min_value=0.0, max_value=100.0, step=10.0, key=f"x_{ek}_pct",
                                 label_visibility="collapsed", disabled=not ss[f"x_{ek}_applies"])
            cols[3].text_input("조항", key=f"x_{ek}_clause", label_visibility="collapsed", placeholder="예: Cl.18")
        st.caption("주말·휴일은 Laytime 기준(SHEX 등)으로, OODAOD 는 위 체크박스로 처리합니다. "
                   "기타 중단(STOPPAGE_OTHER)은 계약 근거가 없으므로 항상 '검토 필요'로 표시됩니다.")

    with st.container(border=True):
        section("근거 조항 번호", "Time Sheet 의 '적용 조항' 칸에 표시됩니다.")
        c1, c2, c3 = st.columns(3)
        c1.text_input(_lbl("clause_laytime", "Laytime 조항"), key="c_clause_laytime", placeholder="예: Cl.5", help=_help("clause_laytime"))
        c2.text_input(_lbl("clause_nor", "NOR 조항"), key="c_clause_nor", placeholder="예: Cl.6", help=_help("clause_nor"))
        c3.text_input(_lbl("clause_demurrage", "Demurrage 조항"), key="c_clause_demurrage", placeholder="예: Cl.7",
                      help=_help("clause_demurrage"))

    st.caption("* 표시 = 필수 항목")
    return state_to_contract()
