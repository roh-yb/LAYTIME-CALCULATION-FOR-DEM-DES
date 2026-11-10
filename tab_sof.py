"""기능 2. NOR/SOF 제출 및 데이터 확인."""
from datetime import date

import streamlit as st

from ai import client as ai_client
from ai.extract import file_to_payload
from ai.parsers import parse_sof
from core.calendar_util import country_holidays
from core.constants import EVENT_LABELS, EVENT_TYPES, INTERVAL_EVENTS, event_label
from core.timeutil import parse_dt
from core.validator import validate_events

from .state import df_to_events, holidays_in_use, queue_state, record_ai_error, record_usage
from .style import section


def _ai_section(contract: dict):
    with st.expander("🤖 SOF / NOR 파일로 이벤트 표 자동 생성 (AI)", expanded=st.session_state["events_df"].empty):
        if not ai_client.is_available():
            st.info("OPENAI_API_KEY 가 설정되지 않아 AI 기능을 사용할 수 없습니다. 아래 표에 직접 입력하세요.")
            return
        up = st.file_uploader("SOF 파일 (PDF / 엑셀 / CSV / 이미지 / TXT)", type=["pdf", "xlsx", "xlsm", "csv", "png", "jpg", "jpeg", "webp", "txt"], key="sof_file")
        text = st.text_area("또는 SOF 텍스트 붙여넣기", height=180, key="sof_raw_text")
        mode = st.radio("기존 표 처리", ["교체", "추가"], horizontal=True, key="sof_merge_mode")
        st.caption("⚠️ SOF 내용은 OpenAI API 로 전송됩니다. 스캔본은 비전 모델(OPENAI_VISION_MODEL)로 판독합니다.")
        if st.button("AI 파싱 실행", type="primary", key="btn_ai_sof"):
            images: list[str] = []
            body = text or ""
            try:
                if up is not None:
                    ftext, images = file_to_payload(up.name, up.getvalue())
                    body = (body + "\n\n" + ftext).strip()
                if not body and not images:
                    st.warning("SOF 파일을 업로드하거나 텍스트를 입력하세요.")
                    return
                hint = " ~ ".join(x for x in (contract.get("laycan_start"), contract.get("laycan_end")) if x)
                with st.spinner("조체선료 분석 모델로 SOF 판독 중…"):
                    result = parse_sof(body, images, hint)
            except Exception as exc:
                record_ai_error(exc)
                st.error(f"AI 파싱 실패: {exc}")
                return
            record_usage(result["usage"])
            st.session_state["ai_sof"] = {"summary": result["summary"], "count": len(result["events"])}
            updates = {}
            if result.get("vessel") and not st.session_state.get("c_vessel"):
                updates["c_vessel"] = result["vessel"]
            if result.get("port") and not st.session_state.get("c_port"):
                updates["c_port"] = result["port"]
            if mode == "추가":
                # 편집기의 현재 값(사용자 수정 포함)은 표가 그려진 뒤에야 알 수 있으므로, 표 렌더링 후 병합한다
                st.session_state["_append_events"] = result["events"]
                queue_state(updates)
            else:
                queue_state(updates, events=result["events"])

    info = st.session_state.get("ai_sof")
    if info:
        st.success(f"AI 가 이벤트 {info['count']}건을 추출했습니다. 🚩 표시(AI 확인 필요) 행을 원본과 대조하세요.")
        if info.get("summary"):
            st.caption(f"AI 요약: {info['summary']}")


def _holiday_section(contract: dict):
    years = set()
    for k in ("laycan_start", "laycan_end"):
        dt = parse_dt(contract.get(k))
        if dt:
            years.add(dt.year)
    years = sorted(years) or [date.today().year]
    n_hol = len(holidays_in_use())
    shinc = contract["laytime_terms"] == "SHINC"
    country = (contract.get("country") or "").strip().upper()
    auto_key = f"{country}|{years}"
    if not shinc and n_hol == 0 and country and st.session_state.get("_auto_holidays") != auto_key:
        # PRD §5-2: 해당 항의 공휴일 캘린더 자동 적용 (같은 국가·연도는 한 번만 — 사용자가 비운 표를 다시 채우지 않음)
        st.session_state["_auto_holidays"] = auto_key
        items = country_holidays(country, years)
        if items:
            queue_state({}, holidays=items)
    title = f"④ 휴일 캘린더 — {n_hol}일 적용" + (" (SHINC: 계산 영향 없음)" if shinc else "")
    with st.expander(title, expanded=not shinc and n_hol == 0):
        c1, c2 = st.columns([1, 2], vertical_alignment="center")
        if c1.button(f"{contract.get('country') or '?'} 공휴일 불러오기 ({', '.join(map(str, years))})", key="btn_holidays"):
            items = country_holidays(contract.get("country") or "", years)
            if not items:
                st.warning("해당 국가 코드의 공휴일을 찾지 못했습니다. ① 탭의 국가 코드를 확인하거나 직접 입력하세요.")
            else:
                queue_state({}, holidays=items)
        c2.caption("항만 휴무일·지방 공휴일은 행을 추가하고, 계약상 휴일이 아닌 날은 '적용' 체크를 해제하세요. "
                   "휴일은 해당일 00:00~24:00 로 처리됩니다.")
        return st.data_editor(
            st.session_state["holidays_df"],
            key=f"holidays_editor_{st.session_state['holidays_version']}",
            num_rows="dynamic",
            hide_index=True,
            width="stretch",
            column_config={
                "적용": st.column_config.CheckboxColumn(default=True, width="small"),
                "날짜": st.column_config.DateColumn(format="YYYY-MM-DD"),
                "명칭": st.column_config.TextColumn(width="large"),
            },
        )


def _validation_section(events, errors, warnings):
    if not events:
        section("③ 자동 검증")
        st.info("검증할 이벤트가 없습니다. 위 ① 에서 SOF 를 가져오거나, ② 표에 직접 입력하거나, 사이드바에서 샘플을 불러오세요.")
        return
    if errors:
        head, state = f"❌ 오류 {len(errors)}건 · ⚠️ 경고 {len(warnings)}건 — 오류를 고쳐야 계산됩니다", "err"
    elif warnings:
        head, state = f"⚠️ 경고 {len(warnings)}건 — 계산은 가능하지만 확인이 필요합니다", "warn"
    else:
        head, state = "✅ 검증 통과 — ③ 정산 결과 탭에서 결과를 확인하세요", "ok"
    section("③ 자동 검증")
    with st.expander(head, expanded=state != "ok"):
        if errors:
            st.markdown("**오류 (계산 불가)**")
            for e in errors:
                st.error(e)
        if warnings:
            st.markdown("**경고 (확인 필요)**")
            for w in warnings:
                st.warning(w)
        if state == "ok":
            st.caption("필수 이벤트, 시간 순서, 기간 중복, Laycan 대비 NOR 시점을 확인했습니다.")


def render(contract: dict) -> tuple[list[dict], list[str], list[str]]:
    section("① SOF 가져오기")
    _ai_section(contract)

    with st.container(border=True):
        section("② 이벤트 확인 · 수정",
                "구간 이벤트(Shifting, Draft survey, 악천후, 고장, 파업, 기타 중단)는 시작·종료를 모두, "
                "시점 이벤트(NOR, 하역 개시/완료 등)는 시작만 입력합니다. 시각은 항구 현지시간 · 행 추가는 표 아래 + 버튼")
        edited = st.data_editor(
            st.session_state["events_df"],
            key=f"events_editor_{st.session_state['events_version']}",
            num_rows="dynamic",
            hide_index=False,
            width="stretch",
            height=min(38 + 35 * (len(st.session_state["events_df"]) + 2), 640),
            column_config={
                "start": st.column_config.DatetimeColumn("시작", format="YYYY-MM-DD HH:mm", step=60, required=True),
                "end": st.column_config.DatetimeColumn("종료 (구간)", format="YYYY-MM-DD HH:mm", step=60),
                "event_type": st.column_config.SelectboxColumn("이벤트", options=EVENT_LABELS, required=True, width="medium"),
                "description": st.column_config.TextColumn("SOF 원문", width="large"),
                "remarks": st.column_config.TextColumn("비고", width="medium"),
                "ai_flag": st.column_config.CheckboxColumn("🚩 AI 확인", help="AI 판독이 불확실한 행 — 원본과 대조 후 체크 해제", width="small"),
            },
        )
        events = df_to_events(edited)
        if "_append_events" in st.session_state:  # AI '추가' 결과를 현재 표(사용자 수정 포함) 뒤에 붙인다
            queue_state({}, events=events + st.session_state.pop("_append_events"))
        with st.expander("이벤트 코드 안내"):
            st.markdown(
                "\n".join(
                    f"- **{event_label(c)}**" + (" — 구간 (시작~종료)" if c in INTERVAL_EVENTS else "")
                    for c in EVENT_TYPES
                )
            )

    errors, warnings = validate_events(contract, events)
    if contract["laytime_terms"] != "SHINC" and not holidays_in_use():
        warnings.append(f"{contract['laytime_terms']} 계약인데 적용된 휴일이 0일입니다. ④ 휴일 캘린더에서 항구 공휴일을 확인하세요 "
                        "(누락 시 휴일이 Laytime 에 포함되어 사용 시간이 과대 계산됩니다).")
    flagged = sum(1 for e in events if e.get("ai_flag"))
    if flagged:
        warnings.insert(0, f"🚩 AI 확인 필요 행 {flagged}건이 남아 있습니다. 원본 SOF 와 대조 후 체크를 해제하세요.")
    _validation_section(events, errors, warnings)

    holidays_df = _holiday_section(contract)
    contract["holidays"] = holidays_in_use(holidays_df)
    return events, errors, warnings
