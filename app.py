"""벌크선 조체선료(Demurrage/Despatch) 자동 정산 TOOL — Streamlit 진입점.

실행: streamlit run app.py
"""
import hmac
import json
from datetime import datetime

import streamlit as st

import config
from ai import client as ai_client
from core.contract import normalize_contract, required_status
from core.sample import CLAUDE_YB_ASSUMPTION, claude_yb_contract, claude_yb_events, sample_contract, sample_events
from export.report import KIND_LABEL
from ui import tab_contract, tab_result, tab_sof
from ui.style import inject_css, steps_bar
from ui.state import (
    apply_pending,
    contract_to_state,
    events_from_json,
    events_to_json,
    init_state,
    queue_state,
)

st.set_page_config(page_title="조체선료 자동 정산 TOOL", page_icon="⚓", layout="wide")


def password_gate() -> bool:
    pw = config.app_password()
    if not pw or st.session_state.get("authed"):
        return True
    st.title("⚓ 조체선료 자동 정산 TOOL")
    entered = st.text_input("접속 비밀번호", type="password")
    if entered:
        if hmac.compare_digest(entered, pw):
            st.session_state["authed"] = True
            st.rerun()
        st.error("비밀번호가 올바르지 않습니다.")
    return False


def sidebar(contract_fn):
    with st.sidebar:
        st.subheader("🤖 AI 상태")
        models = f"분석 모델: `{config.openai_model()}`\n\n비전 모델: `{config.openai_vision_model()}`"
        if ai_client.is_available() and st.session_state.get("ai_error"):
            st.error(f"AI 호출 오류\n\n{st.session_state['ai_error']}\n\n{models}")
        elif ai_client.is_available():
            st.success(f"API 키 설정됨 (연결은 AI 실행 시 확인)\n\n{models}")
            u = st.session_state["ai_usage"]
            if u["calls"]:
                st.caption(f"이번 세션 AI 호출 {u['calls']}회 · 입력 {u['prompt_tokens']:,} / 출력 {u['completion_tokens']:,} 토큰")
        else:
            st.warning("AI 미연결 — `.env` 또는 Secrets 에 OPENAI_API_KEY 를 설정하세요. 수동 입력·계산은 사용 가능합니다.")

        st.divider()
        st.subheader("📂 샘플")
        samples = {
            "MV CLAUDE YB (실제 SOF · 가정 계약)": (claude_yb_contract, claude_yb_events, CLAUDE_YB_ASSUMPTION),
            "MV SAMPLE STAR (데모 · 체선 발생)": (sample_contract, sample_events, "데모용 가상 데이터입니다."),
        }
        choice = st.selectbox("샘플 선택", list(samples), label_visibility="collapsed")
        if st.button("샘플 불러오기", width="stretch"):
            c_fn, e_fn, note = samples[choice]
            st.session_state["ai_contract"] = None
            st.session_state["ai_sof"] = None
            st.session_state["sample_note"] = note
            queue_state(contract_to_state(c_fn()), events=e_fn(), holidays=[])

        st.divider()
        st.subheader("💾 템플릿 · 작업 파일")
        contract, events = contract_fn()
        payload = {"saved_at": datetime.now().isoformat(timespec="seconds"), "contract": contract, "events": events_to_json(events)}
        fname = f"laytime_{(contract.get('counterparty') or contract.get('vessel') or 'template').replace(' ', '_')}.json"
        st.download_button("💾 현재 계약+SOF 저장 (JSON)", json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                           file_name=fname, mime="application/json", width="stretch")
        up = st.file_uploader("불러오기 (JSON)", type=["json"], key="template_upload")
        include_events = st.checkbox("SOF 이벤트도 불러오기", value=False, help="해제 시 계약 조건만 불러옵니다 (공급사·선사별 템플릿 용도)")
        if up is not None and st.button("불러오기 적용", width="stretch"):
            try:
                data = json.loads(up.getvalue().decode("utf-8"))
                c = normalize_contract(data.get("contract", data))
            except Exception as exc:
                st.error(f"파일을 읽을 수 없습니다: {exc}")
            else:
                st.session_state["ai_contract"] = None
                queue_state(
                    contract_to_state(c),
                    events=events_from_json(data.get("events", [])) if include_events else None,
                    holidays=c.get("holidays") or [],
                )

        st.divider()
        with st.popover("🗑️ 전체 초기화", width="stretch"):
            st.warning("입력한 계약 조건, SOF 이벤트, 검토 판단이 모두 지워집니다. 필요하면 먼저 JSON 으로 저장하세요.")
            if st.button("초기화 실행", type="primary", width="stretch"):
                st.session_state.clear()
                st.rerun()
        st.caption("계산 규칙: 분 단위 · 1일 = 24시간 · 금액 pro rata · USD 0.01 반올림. AI 는 해석만, 계산은 규칙 엔진이 수행합니다.")


TAB_BASE = ["① 계약 조건", "② NOR / SOF", "③ 정산 결과"]
BADGE = {"ok": "✅", "err": "❌", "idle": ""}


def compute_status(contract, events, errors, warnings, result) -> list[tuple[str, str, str]]:
    """[(state, 제목, 설명)] × 3 — 상단 진행 카드와 탭 배지에 사용."""
    filled, total, missing = required_status(contract)
    if missing:
        c = ("err", f"필수 {filled}/{total} 입력 · 누락 {len(missing)}개")
    else:
        c = ("ok", f"필수 {total}/{total} 입력 완료")
    if not events:
        s = ("idle", "이벤트 없음 — SOF 를 가져오거나 입력하세요")
    elif errors:
        s = ("err", f"이벤트 {len(events)}건 · 오류 {len(errors)} · 경고 {len(warnings)}")
    elif warnings:
        s = ("warn", f"이벤트 {len(events)}건 · 경고 {len(warnings)}")
    else:
        s = ("ok", f"이벤트 {len(events)}건 · 검증 통과")
    if result is None:
        r = ("idle", "계산 대기 — ①·② 를 완료하세요")
    else:
        money = f"{KIND_LABEL[result['kind']].split(' ')[0]} USD {result['amount']:,.2f}"
        r = ("warn", f"{money} · 검토 필요 {result['review_count']}건") if result["review_count"] else ("ok", f"{money} · 확정 가능")
    return [(c[0], TAB_BASE[0], c[1]), (s[0], TAB_BASE[1], s[1]), (r[0], TAB_BASE[2], r[1])]


def _badge(state: str, desc: str) -> str:
    if state == "warn":
        n = next((tok for tok in desc.replace("·", " ").split() if tok.isdigit()), "")
        return f"⚠️{n}"
    return BADGE[state]


def tabs_with_badges(status):
    """상태 배지가 붙은 탭. 라벨이 바뀌어도 사용자가 보던 탭을 유지한다."""
    labels = [f"{base} {_badge(st_, desc)}".strip() for base, (st_, _t, desc) in zip(TAB_BASE, status)]
    prev = st.session_state.get("main_tab")
    if prev not in labels:
        idx = next((i for i, b in enumerate(TAB_BASE) if prev and prev.startswith(b)), 0)
        st.session_state["main_tab"] = labels[idx]
    return st.tabs(labels, key="main_tab", on_change="rerun")


def main():
    if not password_gate():
        return
    inject_css()
    init_state()
    apply_pending()

    st.title("⚓ 벌크선 조체선료 자동 정산 TOOL")
    st.caption("계약 조건과 SOF 를 입력하면 Laytime Statement 를 자동 생성합니다. 담당자는 '검토 필요' 항목만 확인하세요.")
    status = st.session_state.get("_status") or [("idle", b, "확인 중…") for b in TAB_BASE]
    steps_bar(status)
    if st.session_state.get("sample_note"):
        st.info("📌 샘플 불러옴 — " + st.session_state["sample_note"])

    t1, t2, t3 = tabs_with_badges(status)
    with t1:
        contract = tab_contract.render()
    with t2:
        events, errors, warnings = tab_sof.render(contract)
    with t3:
        result = tab_result.render(contract, events, errors)

    sidebar(lambda: (contract, events))

    # 입력 결과로 상태가 바뀌었으면 상단 카드·탭 배지를 갱신하기 위해 한 번 더 그린다
    new_status = compute_status(contract, events, errors, warnings, result)
    if new_status != st.session_state.get("_status"):
        st.session_state["_status"] = new_status
        st.rerun()


main()
