from datetime import datetime, time
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd

DT_FORMATS = (
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y.%m.%d %H:%M",
)


def parse_dt(value) -> datetime | None:
    """문자열/Timestamp/datetime → datetime(분 단위). 실패 시 None."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, float) and value != value:
        return None
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        return value.replace(second=0, microsecond=0, tzinfo=None)
    s = str(value).strip()
    if not s or s.lower() in ("nat", "none", "null"):
        return None
    for fmt in DT_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        ts = pd.to_datetime(s)
        return None if pd.isna(ts) else ts.to_pydatetime().replace(second=0, microsecond=0, tzinfo=None)
    except Exception:
        return None


def fmt_dt(dt: datetime | None) -> str:
    if dt is None or dt is pd.NaT:
        return ""
    return dt.strftime("%Y-%m-%d %H:%M")


def parse_hm(s) -> time:
    if isinstance(s, time):
        return s
    h, m = str(s).split(":")[:2]
    return time(int(h), int(m))


def fmt_hm(t: time) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


def fmt_minutes(minutes) -> str:
    """분 → 'D일 HH:MM' (소수 분이 있으면 초까지 표시)."""
    m = Decimal(str(minutes))
    sign = "-" if m < 0 else ""
    m = abs(m)
    total_sec = int((m * 60).quantize(Decimal(1), ROUND_HALF_UP))
    d, rem = divmod(total_sec, 86400)
    h, rem = divmod(rem, 3600)
    mi, sec = divmod(rem, 60)
    text = f"{sign}{d}일 {h:02d}:{mi:02d}"
    if sec:
        text += f":{sec:02d}"
    return text


def fmt_hhmm(minutes) -> str:
    """분 → 'HH:MM' (24시간 초과 시 시간 누적)."""
    m = Decimal(str(minutes))
    total_sec = int((abs(m) * 60).quantize(Decimal(1), ROUND_HALF_UP))
    h, rem = divmod(total_sec, 3600)
    mi, sec = divmod(rem, 60)
    text = f"{'-' if m < 0 else ''}{h:02d}:{mi:02d}"
    if sec:
        text += f":{sec:02d}"
    return text


def to_days(minutes) -> Decimal:
    return (Decimal(str(minutes)) / Decimal(1440)).quantize(Decimal("0.000001"), ROUND_HALF_UP)
