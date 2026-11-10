"""1단계: 계약 데이터 모델 · 이벤트 코드 정의 테스트."""
import json

from core.constants import EVENT_TYPES, EXCEPTION_LABELS, INTERVAL_EVENTS, POINT_EVENTS, code_from_label, event_label
from core.contract import DEFAULT_CONTRACT, default_contract, missing_fields, normalize_contract


def _complete_contract():
    return normalize_contract(
        {
            "laycan_start": "2026-10-01 00:00",
            "laycan_end": "2026-10-10 23:59",
            "cargo_qty": 175000,
            "rate_mt_day": 35000,
            "demurrage_rate": 25000,
        }
    )


def test_default_contract_is_json_serializable_and_independent():
    c = default_contract()
    json.dumps(c)  # 템플릿 저장 가능해야 함
    c["exceptions"]["shifting"]["applies"] = False
    c["holidays"].append({"date": "2026-10-03", "name": "x"})
    assert DEFAULT_CONTRACT["exceptions"]["shifting"]["applies"] is True  # 기본값 오염 없음
    assert DEFAULT_CONTRACT["holidays"] == []


def test_default_contract_has_all_exception_items():
    assert set(default_contract()["exceptions"]) == set(EXCEPTION_LABELS)
    for rule in default_contract()["exceptions"].values():
        assert set(rule) == {"applies", "counted_pct", "clause"}


def test_normalize_fills_missing_and_ignores_unknown():
    c = normalize_contract({"vessel": "MV X", "unknown_key": 1, "exceptions": {"weather": {"applies": True}, "bogus": {}}})
    assert c["vessel"] == "MV X"
    assert "unknown_key" not in c
    assert c["exceptions"]["weather"] == {"applies": True, "counted_pct": 0.0, "clause": ""}
    assert "bogus" not in c["exceptions"]
    assert c["notice_hours"] == DEFAULT_CONTRACT["notice_hours"]


def test_missing_fields_default_lists_required_labels():
    missing = missing_fields(default_contract())
    for label in ("화물량 (B/L MT)", "하역률 (MT/day)", "Demurrage 요율 (USD/day)", "Laycan 시작", "Laycan 종료"):
        assert label in missing


def test_missing_fields_complete_contract_is_empty():
    assert missing_fields(_complete_contract()) == []


def test_missing_fields_fixed_laytime_mode():
    c = _complete_contract()
    c["laytime_mode"] = "FIXED"
    assert "고정 Laytime (시간)" in missing_fields(c)
    c["fixed_laytime_hours"] = 72
    assert missing_fields(c) == []


def test_event_types_split_into_point_and_interval():
    assert set(POINT_EVENTS) | set(INTERVAL_EVENTS) == set(EVENT_TYPES)
    assert not set(POINT_EVENTS) & set(INTERVAL_EVENTS)
    for required in ("NOR_TENDERED", "COMMENCED", "COMPLETED", "ALL_FAST", "DOCS_ON_BOARD"):
        assert required in POINT_EVENTS
    for interval in ("SHIFTING", "DRAFT_SURVEY", "WEATHER", "BREAKDOWN_SHIP", "BREAKDOWN_SHORE", "STRIKE"):
        assert INTERVAL_EVENTS[interval] in EXCEPTION_LABELS


def test_event_label_roundtrip():
    for code in EVENT_TYPES:
        assert code_from_label(event_label(code)) == code
    assert code_from_label("COMMENCED") == "COMMENCED"
    assert code_from_label(None) is None
    assert code_from_label("없는 이벤트") is None


def test_counterparty_lists_by_basis():
    from core.constants import BASIS_LABELS, COUNTERPARTIES

    assert BASIS_LABELS == {"CP": "Charter Party", "SPA": "구매계약"}
    assert COUNTERPARTIES["CP"] == ["PAN HOPE", "HL OCEANIC", "SM GUARDIAN", "SOLAR MAJESTY"]
    assert COUNTERPARTIES["SPA"] == ["BHP", "VALE", "RIO TINTO", "FMG", "KUMBA", "ASSMANG", "SAMARCO"]


def test_match_counterparty():
    from core.constants import match_counterparty

    assert match_counterparty("pan hope", "CP") == "PAN HOPE"
    assert match_counterparty("Rio Tinto Shipping", "SPA") == "RIO TINTO"
    assert match_counterparty("Vale S.A.", "SPA") == "VALE"
    assert match_counterparty("HL-OCEANIC", "CP") == "HL OCEANIC"
    assert match_counterparty("BHP", "CP") is None  # 기준이 다르면 매칭 안 함
    assert match_counterparty("Unknown Owner", "CP") is None
    assert match_counterparty("", "SPA") is None and match_counterparty(None, "CP") is None
