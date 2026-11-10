"""OpenAI 클라이언트 — .env / Streamlit Secrets 의 OPENAI_API_KEY, OPENAI_MODEL 사용."""
import json

import config


class AIUnavailable(RuntimeError):
    pass


def is_available() -> bool:
    return bool(config.openai_api_key())


def _client():
    key = config.openai_api_key()
    if not key:
        raise AIUnavailable("OPENAI_API_KEY 가 설정되지 않았습니다. .env 또는 Streamlit Secrets 에 등록하세요.")
    from openai import OpenAI

    return OpenAI(api_key=key)


def chat_json(system: str, user_text: str, images: list[str] | None = None, model: str | None = None) -> tuple[dict, dict]:
    """JSON 응답을 받아 (dict, usage) 반환.

    images: data URL 목록 ("data:image/png;base64,...") — 있으면 비전 모델 사용.
    """
    client = _client()
    if images:
        model = model or config.openai_vision_model()
        content = [{"type": "text", "text": user_text}] + [
            {"type": "image_url", "image_url": {"url": url, "detail": "high"}} for url in images
        ]
    else:
        model = model or config.openai_model()
        content = user_text

    kwargs = dict(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": content}],
        response_format={"type": "json_object"},
    )
    import openai

    try:
        try:
            resp = client.chat.completions.create(temperature=0, **kwargs)
        except openai.BadRequestError as exc:  # 일부 추론 모델은 temperature 를 지원하지 않음
            if "temperature" not in str(exc).lower():
                raise
            resp = client.chat.completions.create(**kwargs)
    except openai.AuthenticationError as exc:
        raise AIUnavailable(f"OpenAI API 키가 유효하지 않습니다 (만료/무효화/오타). .env 또는 Secrets 의 OPENAI_API_KEY 를 새 키로 교체하세요. [{exc.status_code}]") from exc
    except openai.NotFoundError as exc:
        raise AIUnavailable(f"모델 '{model}' 을(를) 찾을 수 없거나 이 키로 접근 권한이 없습니다. OPENAI_MODEL 값을 확인하세요.") from exc
    except openai.RateLimitError as exc:
        raise AIUnavailable("OpenAI 사용 한도/요금 한도를 초과했습니다. 잠시 후 다시 시도하거나 결제 설정을 확인하세요.") from exc
    except openai.APIConnectionError as exc:
        raise AIUnavailable("OpenAI 서버에 연결할 수 없습니다. 네트워크를 확인하세요.") from exc

    text = resp.choices[0].message.content or "{}"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"모델 응답이 JSON 형식이 아닙니다: {text[:300]}") from exc
    usage = {
        "model": model,
        "prompt_tokens": getattr(resp.usage, "prompt_tokens", 0) if resp.usage else 0,
        "completion_tokens": getattr(resp.usage, "completion_tokens", 0) if resp.usage else 0,
    }
    return data, usage
