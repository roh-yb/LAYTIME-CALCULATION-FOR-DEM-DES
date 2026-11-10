"""REVIEW C1 회귀 방지 — 조건부 입력칸은 항상 렌더링되어야 한다.

Streamlit 은 한 번의 실행에서 그려지지 않은 위젯의 session_state 를 지운다. 조건에 따라 입력칸을 생략하면
다시 나타날 때 기본값(현재 시각·0·첫 항목)으로 생성되어 금액이 조용히 틀어진다.
(AppTest 는 이 정리 동작을 재현하지 않으므로 '항상 렌더링되는지'를 구조적으로 검사한다.)
"""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")
CONDITIONAL_KEYS = {
    "number_input": ["c_rate_mt_day", "c_fixed_laytime_hours", "c_despatch_ratio", "c_despatch_rate"],
    "selectbox": ["c_excepted_used", "c_weekend_start_dow", "c_weekend_end_dow", "c_nor_early_mode"],
    "time_input": ["c_weekend_start_time", "c_weekend_end_time"],
}


def _rendered(at, kind, key):
    return any(getattr(w, "key", None) == key for w in getattr(at, kind))


@pytest.mark.parametrize("state", [
    {"c_laytime_mode": "RATE", "c_laytime_terms": "SHINC", "c_despatch_mode": "RATIO", "c_nor_before_laycan_counts": True},
    {"c_laytime_mode": "FIXED", "c_laytime_terms": "SHEX", "c_despatch_mode": "AMOUNT", "c_nor_before_laycan_counts": False},
])
def test_conditional_inputs_always_rendered(state):
    at = AppTest.from_file(APP, default_timeout=60)
    for k, v in state.items():
        at.session_state[k] = v
    at.run()
    assert not at.exception
    for kind, keys in CONDITIONAL_KEYS.items():
        for key in keys:
            assert _rendered(at, kind, key), f"{key} 가 렌더링되지 않음 ({state})"


def test_inactive_inputs_are_disabled_not_hidden():
    at = AppTest.from_file(APP, default_timeout=60).run()  # 기본: RATE · SHINC · RATIO
    assert at.number_input(key="c_fixed_laytime_hours").disabled
    assert at.number_input(key="c_despatch_rate").disabled
    assert at.selectbox(key="c_weekend_start_dow").disabled
    assert not at.number_input(key="c_rate_mt_day").disabled
