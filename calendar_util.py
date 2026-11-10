"""항구 국가 공휴일 캘린더 (holidays 라이브러리)."""
from datetime import date


def country_holidays(country: str, years: list[int]) -> list[dict]:
    """[{"date": "YYYY-MM-DD", "name": str}] — 지원하지 않는 국가 코드면 빈 목록."""
    try:
        import holidays
    except ImportError:
        return []
    try:
        cal = holidays.country_holidays(country.strip().upper(), years=sorted(set(years)))
    except (NotImplementedError, KeyError, AttributeError):
        return []
    items = sorted(cal.items())
    return [{"date": d.isoformat(), "name": str(n)} for d, n in items if isinstance(d, date)]
