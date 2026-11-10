"""이벤트 코드, 예외 항목, 계약 선택지 정의."""
import re

EVENT_TYPES: dict[str, str] = {
    "ARRIVAL": "도착 (EOSP/Arrived)",
    "NOR_TENDERED": "NOR 제출",
    "NOR_ACCEPTED": "NOR 수리",
    "ANCHORED": "투묘",
    "FREE_PRATIQUE": "검역 완료 (Free pratique)",
    "PILOT_ON": "도선사 승선",
    "ALL_FAST": "접안 완료 (All fast)",
    "COMMENCED": "하역 개시",
    "COMPLETED": "하역 완료",
    "DOCS_ON_BOARD": "서류 선적 완료",
    "SHIFTING": "이동 (Shifting)",
    "DRAFT_SURVEY": "흘수 검정 (Draft survey)",
    "WEATHER": "악천후 (Rain/Weather)",
    "BREAKDOWN_SHIP": "선박 장비 고장",
    "BREAKDOWN_SHORE": "육상 장비 고장",
    "STRIKE": "파업",
    "STOPPAGE_OTHER": "기타 중단",
    "OTHER": "기타 (정보)",
}

# 구간(From~To) 이벤트 → 계약 예외 항목 키 (None = 계약 근거 없음, 검토 필요)
INTERVAL_EVENTS: dict[str, str | None] = {
    "SHIFTING": "shifting",
    "DRAFT_SURVEY": "draft_survey",
    "WEATHER": "weather",
    "BREAKDOWN_SHIP": "breakdown_ship",
    "BREAKDOWN_SHORE": "breakdown_shore",
    "STRIKE": "strike",
    "STOPPAGE_OTHER": None,
}

# 시점 이벤트 (시작 일시만 사용, 종료 없음)
POINT_EVENTS: tuple[str, ...] = tuple(c for c in EVENT_TYPES if c not in INTERVAL_EVENTS)

EXCEPTION_LABELS: dict[str, str] = {
    "shifting": "Shifting (앵커리지→부두 이동 등)",
    "draft_survey": "Draft survey",
    "weather": "악천후 (WWD)",
    "breakdown_ship": "선박 장비 고장",
    "breakdown_shore": "육상 장비 고장",
    "strike": "파업",
}

# 정산 기준 (내부 코드 "SPA" 는 기존 템플릿 호환을 위해 유지, 화면 표기는 '구매계약')
BASIS_LABELS = {"CP": "Charter Party", "SPA": "구매계약"}
BASIS_LABELS_EN = {"CP": "Charter Party", "SPA": "Purchase Contract"}

# 정산 기준별 정산 대상
COUNTERPARTIES: dict[str, list[str]] = {
    "CP": ["PAN HOPE", "HL OCEANIC", "SM GUARDIAN", "SOLAR MAJESTY"],
    "SPA": ["BHP", "VALE", "RIO TINTO", "FMG", "KUMBA", "ASSMANG", "SAMARCO"],
}


def match_counterparty(value, basis: str) -> str | None:
    """입력값(템플릿·AI 결과)을 해당 정산 기준의 정산 대상 목록 항목으로 맞춘다. 없으면 None."""
    if not value:
        return None
    norm = " ".join(str(value).upper().replace("-", " ").split())
    options = COUNTERPARTIES.get(basis, [])
    for opt in options:
        if norm == opt:
            return opt
    for opt in options:  # "BHP Billiton", "Vale S.A.", "Rio Tinto Shipping" 등
        if opt in norm or norm in opt:
            return opt
    return None


LAYTIME_TERMS = {
    "SHINC": "SHINC (일요일·휴일 포함)",
    "SHEX": "SHEX (일요일·휴일 제외)",
    "SSHEX": "SSHEX (토·일요일·휴일 제외)",
}
EXCEPTED_USED = {"EIU": "EIU (사용해도 미반영)", "UU": "UU (사용 시 반영)"}
BERTH_TERMS = {
    "WIBON": "WIBON",
    "WIPON": "WIPON",
    "WIFPON": "WIFPON",
    "WCCON": "WCCON",
    "PORT": "Port charter",
    "BERTH": "Berth charter (접안 후 NOR 유효)",
}
LAYTIME_END_EVENTS = {"COMPLETED": "하역 완료", "DOCS_ON_BOARD": "서류 선적 완료"}
NOR_EARLY_MODES = {
    "NOT_BEFORE_LAYCAN": "NOR+Notice 와 Laycan 시작 중 늦은 시점 (laytime not to commence before laycan)",
    "DEEMED_AT_LAYCAN": "Laycan 시작에 NOR 제출 간주 → + Notice time",
}
DESPATCH_BASIS = {"WTS": "Working time saved", "ATS": "All time saved"}
ALLOWED_ROUNDING = {
    "ROUND": "분 단위 반올림",
    "DOWN": "분 단위 절사",
    "UP": "분 단위 올림",
    "EXACT": "반올림 없음 (소수 분 유지)",
}
DOW_KR = ["월", "화", "수", "목", "금", "토", "일"]

_LABEL_RE = re.compile(r"\[([A-Z_]+)\]\s*$")


def event_label(code: str) -> str:
    return f"{EVENT_TYPES.get(code, code)} [{code}]"


EVENT_LABELS = [event_label(c) for c in EVENT_TYPES]


def code_from_label(value) -> str | None:
    if value is None or (isinstance(value, float) and value != value):
        return None
    s = str(value).strip()
    m = _LABEL_RE.search(s)
    if m:
        return m.group(1)
    return s if s in EVENT_TYPES else None
