"""AI 레이어 — 네트워크 없이 모의 응답으로 후처리·파일 추출·오류 안내를 검증."""
import io
from pathlib import Path

import openai
import pandas as pd
import pytest

import ai.client as client
import ai.parsers as parsers
from ai.extract import file_to_payload
from core.sample import claude_yb_events

ROOT = Path(__file__).resolve().parents[1]
SOF_PDF = ROOT / "SOF_MV CLAUDE YB.pdf"


def fake_chat(response):
    return lambda system, user, images=None: (response, {"prompt_tokens": 10, "completion_tokens": 5, "model": "fake"})


# --- 계약 파서 -----------------------------------------------------------------

def test_parse_contract_coerces_and_flags(monkeypatch):
    monkeypatch.setattr(parsers, "chat_json", fake_chat({
        "fields": {
            "laytime_terms": {"value": "shex", "source_clause": "Cl.5 SHEX EIU", "confidence": "high", "needs_review": False},
            "rate_mt_day": {"value": "35,000", "confidence": "high"},
            "demurrage_rate": {"value": 25000, "confidence": "low"},
            "notice_hours": {"value": None, "needs_review": True},
            "berth_terms": {"value": "SOMETHING", "confidence": "high"},
            "laycan_start": {"value": "2026-10-01", "confidence": "high"},
            "weekend_start_time": {"value": "12:00", "confidence": "high"},
            "oodaod": {"value": "yes", "confidence": "high"},
            "unknown_field": {"value": 1},
        },
        "exceptions": {"weather": {"applies": True, "counted_pct": 0, "clause": "Cl.10", "confidence": "high"},
                       "strike": {"applies": None, "confidence": "low"}},
        "summary": "요약",
    }))
    r = parsers.parse_contract("text")
    v, m = r["values"], r["meta"]
    assert v["laytime_terms"] == "SHEX" and v["rate_mt_day"] == 35000.0
    assert v["laycan_start"] == "2026-10-01 00:00" and v["weekend_start_time"] == "12:00" and v["oodaod"] is True
    assert "berth_terms" not in v and m["berth_terms"]["needs_review"]  # 허용값 아님 → 채우지 않고 검토
    assert m["demurrage_rate"]["needs_review"]  # low confidence → 검토
    assert m["notice_hours"]["needs_review"] and "notice_hours" not in v  # 원문 없음 → 추정 금지
    assert "unknown_field" not in m
    assert r["exceptions"] == {"weather": {"applies": True, "counted_pct": 0.0, "clause": "Cl.10"}}
    assert m["exc_strike"]["needs_review"]


# --- SOF 파서 ------------------------------------------------------------------

def test_parse_sof_normalizes_events(monkeypatch):
    monkeypatch.setattr(parsers, "chat_json", fake_chat({"vessel": "M/V CLAUDE YB", "events": [
        {"start": "2026-10-03 18:00", "event_type": "COMMENCED", "description": "Commenced discharging"},
        {"start": "2026-10-01 10:00", "end": "2026-10-01 11:00", "event_type": "nor_tendered", "description": "NOR"},
        {"start": "2026-10-04 10:00", "end": None, "event_type": "WEATHER", "description": "rain"},
        {"start": "garbage", "event_type": "XYZ", "description": "?"},
    ]}))
    r = parsers.parse_sof("sof", year_hint="2026-10")
    evs = r["events"]
    assert [e["event_type"] for e in evs] == ["NOR_TENDERED", "COMMENCED", "WEATHER", "OTHER"]  # 시간순, 시작 없는 행은 마지막
    assert evs[0]["end"] is None  # 시점 이벤트의 종료는 버림
    assert evs[2]["ai_flag"] and "종료 시각" in evs[2]["remarks"]
    assert evs[3]["ai_flag"] and evs[3]["start"] is None and "XYZ" in evs[3]["remarks"]
    assert r["vessel"] == "M/V CLAUDE YB"


def test_sof_accuracy_metric_against_transcript(monkeypatch):
    """실제 AI 결과를 수기 전사본과 비교하는 지표 — 모의 응답(전사본 그대로)일 때 100%."""
    truth = claude_yb_events()
    monkeypatch.setattr(parsers, "chat_json", fake_chat({"events": [
        {"start": e["start"].strftime("%Y-%m-%d %H:%M"), "end": e["end"].strftime("%Y-%m-%d %H:%M") if e["end"] else None,
         "event_type": e["event_type"], "description": e["description"]} for e in truth]}))
    parsed = parsers.parse_sof("sof")["events"]
    key = lambda e: (e["start"], e["end"], e["event_type"])  # noqa: E731
    hits = len({key(e) for e in truth} & {key(e) for e in parsed})
    assert hits / len(truth) == 1.0


# --- 파일 추출 -----------------------------------------------------------------

@pytest.mark.skipif(not SOF_PDF.exists(), reason="샘플 SOF PDF 없음")
def test_scanned_sof_pdf_goes_to_vision():
    text, images = file_to_payload(SOF_PDF.name, SOF_PDF.read_bytes())
    assert text == "" and len(images) == 2
    assert all(u.startswith("data:image/jpeg;base64,") for u in images)


def test_excel_csv_txt_payloads():
    buf = io.BytesIO()
    pd.DataFrame([["01-Oct-2026", "10:00", "NOR tendered"]]).to_excel(buf, index=False, header=False)
    text, images = file_to_payload("sof.xlsx", buf.getvalue())
    assert "NOR tendered" in text and images == []
    text, _ = file_to_payload("sof.csv", "01-Oct-2026,10:00,NOR tendered\n".encode())
    assert "NOR tendered" in text
    text, _ = file_to_payload("sof.txt", "선박 도착".encode("cp949"))
    assert text == "선박 도착"
    text, images = file_to_payload("scan.PNG", b"\x89PNG fake")
    assert text == "" and images[0].startswith("data:image/png;base64,")
    with pytest.raises(ValueError):
        file_to_payload("sof.docx", b"x")


# --- OpenAI 오류 안내 ----------------------------------------------------------

def _status_error(cls, code, message="boom"):
    """SDK 버전(httpx/httpx2)에 의존하지 않도록 생성자를 거치지 않고 오류 객체를 만든다."""
    err = cls.__new__(cls)
    Exception.__init__(err, message)
    err.message, err.status_code, err.body = message, code, None
    return err


class FakeCompletions:
    def __init__(self, errors, content='{"ok": true}'):
        self.errors, self.content, self.calls = list(errors), content, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.errors:
            raise self.errors.pop(0)
        msg = type("M", (), {"content": self.content})
        usage = type("U", (), {"prompt_tokens": 3, "completion_tokens": 2})
        return type("R", (), {"choices": [type("C", (), {"message": msg})], "usage": usage})


def _patch_client(monkeypatch, completions):
    fake = type("Client", (), {"chat": type("Chat", (), {"completions": completions})})
    monkeypatch.setattr(client, "_client", lambda: fake)


@pytest.mark.parametrize("cls,code,text", [
    (openai.AuthenticationError, 401, "API 키가 유효하지 않습니다"),
    (openai.NotFoundError, 404, "찾을 수 없거나"),
    (openai.RateLimitError, 429, "한도"),
])
def test_api_errors_become_korean_messages(monkeypatch, cls, code, text):
    _patch_client(monkeypatch, FakeCompletions([_status_error(cls, code)]))
    with pytest.raises(client.AIUnavailable, match=text):
        client.chat_json("sys", "user")


def test_temperature_unsupported_retries_without_it(monkeypatch):
    comp = FakeCompletions([_status_error(openai.BadRequestError, 400, "Unsupported parameter: 'temperature'")])
    _patch_client(monkeypatch, comp)
    data, usage = client.chat_json("sys", "user")
    assert data == {"ok": True}
    assert "temperature" in comp.calls[0] and "temperature" not in comp.calls[1]
    assert comp.calls[0]["response_format"] == {"type": "json_object"}


def test_images_use_vision_model(monkeypatch):
    comp = FakeCompletions([])
    _patch_client(monkeypatch, comp)
    monkeypatch.setenv("OPENAI_MODEL", "analysis-model")
    monkeypatch.setenv("OPENAI_VISION_MODEL", "vision-model")
    client.chat_json("sys", "user", ["data:image/png;base64,AAA"])
    assert comp.calls[0]["model"] == "vision-model"
    assert comp.calls[0]["messages"][1]["content"][1]["type"] == "image_url"


def test_non_json_response_raises(monkeypatch):
    _patch_client(monkeypatch, FakeCompletions([], content="not json"))
    with pytest.raises(ValueError, match="JSON"):
        client.chat_json("sys", "user")
