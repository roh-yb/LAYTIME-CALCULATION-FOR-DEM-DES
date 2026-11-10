"""공통 스타일 — 의미 색상(화면·Excel 공통 의미), 상태 카드, 결과 카드, 범례.

색은 의미에만 쓴다. 배경은 반투명 rgba 로 지정해 라이트/다크 테마 모두에서 글자가 읽히게 한다.
"""
from html import escape

import streamlit as st

# 화면 강조색 (Excel 은 export/excel.py 의 같은 의미 색을 사용)
ROW_COLORS = {
    "review": "rgba(255, 193, 7, 0.32)",  # 검토 필요 — 노랑
    "user": "rgba(13, 110, 253, 0.18)",  # 사용자 판단 — 파랑
    "dem": "rgba(220, 53, 69, 0.14)",  # 체선 구간 — 연한 빨강
}
STATE_COLORS = {
    "ok": ("rgba(25, 135, 84, 0.12)", "rgba(25, 135, 84, 0.55)"),
    "warn": ("rgba(255, 193, 7, 0.16)", "rgba(204, 153, 0, 0.65)"),
    "err": ("rgba(220, 53, 69, 0.12)", "rgba(220, 53, 69, 0.60)"),
    "idle": ("rgba(128, 128, 128, 0.08)", "rgba(128, 128, 128, 0.35)"),
}
STATE_ICON = {"ok": "✅", "warn": "⚠️", "err": "❌", "idle": "○"}

_CSS = """
<style>
.block-container {padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1500px;}
h1 {font-size: 1.75rem !important;}
div[data-testid="stTabs"] button p {font-size: 0.98rem; font-weight: 600;}
.lt-steps {display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.6rem; margin: 0.2rem 0 0.8rem;}
@media (max-width: 760px) {.lt-steps {grid-template-columns: 1fr;}}
.lt-step {border: 1px solid; border-radius: 10px; padding: 0.55rem 0.85rem; line-height: 1.35;}
.lt-step .t {font-weight: 700; font-size: 0.92rem;}
.lt-step .s {font-size: 0.85rem; opacity: 0.85;}
.lt-hero {border: 1px solid; border-radius: 12px; padding: 0.9rem 1.2rem; margin-bottom: 0.6rem;}
.lt-hero .k {font-size: 0.9rem; font-weight: 700; letter-spacing: 0.02em;}
.lt-hero .a {font-size: 2.1rem; font-weight: 800; line-height: 1.15; font-variant-numeric: tabular-nums;}
.lt-hero .d {font-size: 0.88rem; opacity: 0.85;}
.lt-legend {display: flex; flex-wrap: wrap; gap: 0.4rem 0.9rem; font-size: 0.82rem; margin: 0.3rem 0 0.2rem;}
.lt-chip {display: inline-flex; align-items: center; gap: 0.35rem;}
.lt-chip i {display: inline-block; width: 0.95rem; height: 0.95rem; border-radius: 3px; border: 1px solid rgba(128,128,128,0.4);}
.lt-sec {font-weight: 700; font-size: 1.02rem; margin: 0.1rem 0 0.35rem;}
.lt-muted {font-size: 0.85rem; opacity: 0.75;}
</style>
"""


def inject_css():
    st.markdown(_CSS, unsafe_allow_html=True)


def section(title: str, caption: str | None = None):
    st.markdown(f'<div class="lt-sec">{escape(title)}</div>', unsafe_allow_html=True)
    if caption:
        st.caption(caption)


def steps_bar(steps: list[tuple[str, str, str]]):
    """steps: [(state, 제목, 설명)] — state ∈ ok|warn|err|idle"""
    cards = []
    for state, title, desc in steps:
        bg, border = STATE_COLORS[state]
        cards.append(
            f'<div class="lt-step" style="background:{bg};border-color:{border}">'
            f'<div class="t">{STATE_ICON[state]} {escape(title)}</div><div class="s">{escape(desc)}</div></div>'
        )
    st.markdown(f'<div class="lt-steps">{"".join(cards)}</div>', unsafe_allow_html=True)


def result_hero(kind_label: str, amount_text: str, direction: str, state: str):
    bg, border = STATE_COLORS[state]
    st.markdown(
        f'<div class="lt-hero" style="background:{bg};border-color:{border}">'
        f'<div class="k">{escape(kind_label)}</div><div class="a">{escape(amount_text)}</div>'
        f'<div class="d">{escape(direction)}</div></div>',
        unsafe_allow_html=True,
    )


def legend():
    items = [
        (ROW_COLORS["review"], "검토 필요"),
        (ROW_COLORS["user"], "사용자 판단 반영"),
        (ROW_COLORS["dem"], "체선(Demurrage) 구간"),
        ("transparent", "회색 글자 = 미반영(0%)"),
    ]
    chips = "".join(f'<span class="lt-chip"><i style="background:{c}"></i>{escape(t)}</span>' for c, t in items)
    st.markdown(f'<div class="lt-legend">{chips}</div>', unsafe_allow_html=True)
