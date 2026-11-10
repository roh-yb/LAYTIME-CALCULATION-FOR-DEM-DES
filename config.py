"""환경 설정 로더.

우선순위: Streamlit Cloud Secrets(st.secrets) → .env / 환경변수 → 기본값
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


def get_setting(key: str, default: str | None = None) -> str | None:
    try:
        import streamlit as st

        if key in st.secrets:
            value = st.secrets[key]
            return str(value) if value not in (None, "") else default
    except Exception:
        # secrets.toml 이 없는 로컬 환경 등
        pass
    value = os.getenv(key)
    return value if value not in (None, "") else default


def openai_api_key() -> str | None:
    return get_setting("OPENAI_API_KEY")


def openai_model() -> str:
    """조체선료 분석 모델 ID (fine-tuned 모델 ID 사용 가능: ft:...)."""
    return get_setting("OPENAI_MODEL", "gpt-4o")


def openai_vision_model() -> str:
    """스캔본/이미지 SOF 파싱용 모델. 미설정 시 OPENAI_MODEL 사용."""
    return get_setting("OPENAI_VISION_MODEL", openai_model())


def app_password() -> str | None:
    return get_setting("APP_PASSWORD")
