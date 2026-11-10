"""1단계: 설정 로딩 (st.secrets → .env/환경변수 → 기본값)."""
import config


def test_env_value_used_when_no_secrets(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "ft:gpt-4o:laytime:test")
    assert config.openai_model() == "ft:gpt-4o:laytime:test"


def test_defaults_when_missing(monkeypatch):
    for key in ("OPENAI_MODEL", "OPENAI_VISION_MODEL", "APP_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    assert config.openai_model() == "gpt-4o"
    assert config.openai_vision_model() == "gpt-4o"  # 비전 모델 미설정 시 분석 모델 사용
    assert config.app_password() is None


def test_vision_model_falls_back_to_analysis_model(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "my-model")
    monkeypatch.delenv("OPENAI_VISION_MODEL", raising=False)
    assert config.openai_vision_model() == "my-model"


def test_empty_value_treated_as_missing(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "")
    assert config.app_password() is None


def test_secrets_take_precedence(monkeypatch):
    import streamlit as st

    class FakeSecrets(dict):
        pass

    monkeypatch.setattr(st, "secrets", FakeSecrets(OPENAI_MODEL="from-secrets"))
    monkeypatch.setenv("OPENAI_MODEL", "from-env")
    assert config.openai_model() == "from-secrets"


def test_missing_secrets_file_does_not_crash(monkeypatch):
    import streamlit as st

    class BrokenSecrets:
        def __contains__(self, key):
            raise FileNotFoundError("no secrets.toml")

    monkeypatch.setattr(st, "secrets", BrokenSecrets())
    monkeypatch.setenv("OPENAI_MODEL", "from-env")
    assert config.openai_model() == "from-env"


def test_ai_unavailable_without_key(monkeypatch):
    from ai import client

    monkeypatch.setattr(config, "openai_api_key", lambda: None)
    assert client.is_available() is False
