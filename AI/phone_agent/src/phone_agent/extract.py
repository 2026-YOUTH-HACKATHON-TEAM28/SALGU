"""대화록 → 결과 (specs/04-extraction.md).

1. 화자 구분(label_speakers)
2. LLM이 값과 근거 줄 번호를 찾음(LLMExtractor). 키가 없거나 실패하면 결론 unclear
3. 코드가 근거 줄과 대조하고 결론을 정함(decide). 근거는 중개사가 한 말이어야 하고,
   확인되지 않은 값은 null + unverified. 요청 값(예산)으로 채우지 않는다.

낱말·정규식은 specs/assets/word_lists.md, LLM 지시는 specs/assets/extract_prompts.md 원문.
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Optional

import httpx

from .config import KST, ROOT, Settings
from .instruction import when, window_text
from .schemas import CallRequest
from .timing import turn_timing
from .dedupe import building_key

# ------------------------------------------------------------------ 자료

_PROMPTS_FILE = ROOT / "specs" / "assets" / "extract_prompts.md"


def _prompt(name: str) -> str:
    text = _PROMPTS_FILE.read_text(encoding="utf-8")
    section = text[text.index(f"## {name}"):]
    start = section.index("```text\n") + len("```text\n")
    return section[start:section.index("```", start)].strip()


INQUIRY_PROMPT = _prompt("INQUIRY_PROMPT")
CONFIRM_PROMPT = _prompt("CONFIRM_PROMPT")

# word_lists.md
AI_MARKS = ("살구", "AI 비서", "에이아이 비서", "AI비서", "전화드린")
PICKUP = re.compile(r"^\s*(여보세요|네[,.\s]|네$|예[,.\s]|.{0,12}(부동산|공인중개사)(입니다|이에요|예요))")
QUESTION = re.compile(r"(\?|까요|나요|인가요|되나요|있나요)\s*$")
_CORRECTION = re.compile(r"(아\s*잠깐|잠깐만|잠시만|아\s*아니|아니다|아니[요고,.\s]|옆방|그거\s*말고|말고요|정정|다시\s*말(?:하면|씀)|아\s*참)")
_HEDGE = re.compile(r"(던가|일걸|일\s*거예요|확인해\s*봐야|확실하지|정확하지는|정확히는\s*모르|기억이\s*안)")
_TIME_NO = re.compile(r"(안\s*되|안\s*돼|어렵|힘들|곤란)")
_ASKS = re.compile(r"(\?|까요|나요|될까|괜찮으세요|되세요)\s*$")
_ACCEPT = re.compile(r"(네|예|좋|당연|괜찮|그래|그럼요|돼요|됩니다|가능|오세요|맞아요)")
_REFUSE = re.compile(r"(안\s*되|안\s*돼|어렵|힘들|곤란|말고|다른\s*(날|시간|때)|글쎄)")
_NOT_MONEY = r"(?!\s*(?:층|호(?!가)|시(?!세)|분|년|개월|월(?!세)|일|번|명|살|평|동|㎡|제곱))"
_WEEKDAY = re.compile(r"(다음\s*주|담주|이번\s*주)?\s*([월화수목금토일])요일")
_MONTH_DAY = re.compile(r"(?:(\d{1,2})\s*월\s*)?(\d{1,2})\s*일(?!\s*(?:간|정도|째|이내|안에))")
MAX_LISTINGS = 5
MAX_SLOTS = 6
GENERIC = ("오피스텔", "빌라", "주택", "원룸", "건물", "아파트")

LISTING_FIELDS = (
    "location", "building", "floor", "unit", "area_m2", "deposit_manwon", "monthly_rent_manwon",
    "maintenance_fee_manwon", "maintenance_includes", "move_in",
)
MONEY_FIELDS = ("deposit_manwon", "monthly_rent_manwon", "maintenance_fee_manwon")
PYEONG_M2 = 3.3058
DAYS = "월화수목금토일"


# ------------------------------------------------------------------ 화자 구분


def label_speakers(segments: list[dict]) -> list[dict]:
    """공급사 화자 이름(speaker_0 …) → ai / broker.

    'AI 비서 살구' 소개가 있는 쪽이 AI. 소개가 끊겼으면 첫 줄을 '여보세요/○○부동산입니다'로
    받은 쪽이 중개사, 그것도 없으면 질문을 많이 한 쪽이 AI (lessons L6).
    """
    if not segments:
        return []
    names = [seg.get("speaker") for seg in segments]
    if set(names) <= {"ai", "broker"}:
        return [dict(seg) for seg in segments]
    ai = None
    for mark in AI_MARKS:
        ai = next((seg.get("speaker") for seg in segments if mark in (seg.get("text") or "")), None)
        if ai is not None:
            break
    if ai is None and PICKUP.search(segments[0].get("text") or ""):
        ai = next((name for name in names if name != names[0]), None)
    if ai is None:
        counts: dict[Any, int] = {}
        for seg in segments:
            if QUESTION.search((seg.get("text") or "").strip()):
                counts[seg.get("speaker")] = counts.get(seg.get("speaker"), 0) + 1
        ai = max(counts, key=counts.get) if counts else names[0]
    return [{**seg, "speaker": "ai" if seg.get("speaker") == ai else "broker"} for seg in segments]


# ------------------------------------------------------------------ 숫자 읽기

_KDIGIT = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "륙": 6, "칠": 7, "팔": 8, "구": 9}
_KUNIT = {"십": 10, "백": 100, "천": 1000}
_KBIG = {"만": 10 ** 4, "억": 10 ** 8}
_KCHARS = "".join(_KDIGIT) + "".join(_KUNIT) + "".join(_KBIG)
_KTOKEN = re.compile(rf"[{_KCHARS}]+(?: [{_KCHARS}]+)*")
_DTOKEN = re.compile(r"(?<![\d.])(\d[\d,]*(?:\.\d+)?)\s*(억|천|만)?")
_GLUED_HANGUL = re.compile(r"^[가-힣]")  # '육십이요', '오만이던가'의 '이'는 숫자가 아님


def parse_korean(token: str) -> Optional[int]:
    """'천육십오' → 1065, '칠만' → 70000. 숫자 둘이 붙거나('이사', '사이') 단위가 겹치면('천천히') None."""
    total = section = 0
    digit: Optional[int] = None
    prev_unit = False
    for ch in token.replace(" ", ""):
        if ch in _KDIGIT:
            if digit is not None:
                return None
            digit, prev_unit = _KDIGIT[ch], False
        elif ch in _KUNIT:
            if prev_unit and digit is None:
                return None
            section += (digit or 1) * _KUNIT[ch]
            digit, prev_unit = None, True
        elif ch in _KBIG:
            section += digit or 0
            total += (section or 1) * _KBIG[ch]
            section, digit, prev_unit = 0, None, True
        else:
            return None
    return total + section + (digit or 0)


@dataclass
class Money:
    value: float               # 만원
    start: int
    end: int
    pair: Optional[tuple[int, int]] = None  # '천육십오' → (1000, 65)


def _not_money_after(text: str, end: int) -> bool:
    return re.match(_NOT_MONEY, text[end:]) is None


def money_mentions(text: str) -> list[Money]:
    """줄 안의 금액(만원). '3층', '2시'처럼 단위가 붙은 숫자는 빼고, '칠만 원이에요'의 '이'는 2가 아님."""
    found: list[Money] = []
    for m in _DTOKEN.finditer(text):
        number = float(m.group(1).replace(",", ""))
        suffix = m.group(2)
        if not suffix and _not_money_after(text, m.end()):
            continue
        value = {"억": number * 10000, "천": number * 1000, "만": number, None: number}[suffix]
        found.append(Money(value, m.start(), m.end()))
    for m in _KTOKEN.finditer(text):
        token = m.group(0)
        end = m.end()
        if token.endswith("이") and len(token) > 1 and _GLUED_HANGUL.match(text[end:]):
            token, end = token[:-1], end - 1  # '육십이요' → 육십
        if len(token.replace(" ", "")) < 2 and token != "천":
            continue
        n = parse_korean(token)
        if not n or _not_money_after(text, end):
            continue
        if n >= 10000:
            found.append(Money(n / 10000, m.start(), end))
        else:
            pair = (n // 1000 * 1000, n % 1000) if n > 1000 and n % 1000 else None
            found.append(Money(float(n), m.start(), end, pair))
    return sorted(found, key=lambda x: x.start)


def _same(a: float, b: float) -> bool:
    return abs(a - b) < 1e-6


def _similar(a: float, b: float) -> bool:
    return a > 0 and b > 0 and not _same(a, b) and max(a, b) / min(a, b) <= 3


def find_money(value: float, text: str, field: str = "") -> Optional[Money]:
    for mention in money_mentions(text):
        if _same(mention.value, value):
            return mention
        if mention.pair and field in ("deposit_manwon", "monthly_rent_manwon"):
            part = mention.pair[0] if field == "deposit_manwon" else mention.pair[1]
            if _same(part, value):
                return mention
    return None


# ------------------------------------------------------------------ 글자 값

_PUNCT = re.compile(r"[\s·,./\-~'\"“”‘’()!?…]+")


def norm(text: str) -> str:
    return _PUNCT.sub("", (text or "")).lower()


def _korean_digits(n: int) -> list[str]:
    words = {1: "일", 2: "이", 3: "삼", 4: "사", 5: "오", 6: "육", 7: "칠", 8: "팔", 9: "구", 10: "십"}
    return [words[n]] if n in words else []


def _numbered(value: str, unit: str, text: str) -> bool:
    """'3층', '302호'가 그 줄에 숫자나 한국어('삼층')로 있는지."""
    m = re.search(r"(\d+)", value)
    if not m:
        return norm(value) in norm(text)
    n = int(m.group(1))
    if re.search(rf"(?<!\d){n}\s*{unit}", text):
        return True
    if any(re.search(rf"{w}\s*{unit}", text) for w in _korean_digits(n)):
        return True
    # 실시간 전사는 숫자를 한글로 적는다: '삼백일호' = 301호, '십이층' = 12층 (11-21)
    return any(parse_korean(k.group(1)) == n for k in re.finditer(rf"([{_KCHARS}]+)\s*{unit}", text))


def text_in_line(field: str, value: str, text: str) -> bool:
    if not value:
        return False
    if field == "floor":
        return "지하" in value and "지하" in text or _numbered(value, "층", text)
    if field == "unit":
        return _numbered(value, "호", text)
    if field == "maintenance_includes":
        parts = [p for p in re.split(r"[·,/\s]|랑|및|와|과", value) if p]
        return bool(parts) and all(norm(p) in norm(text) for p in parts)
    if field == "location":
        tokens = value.split()
        return all(_numbered(t, "층", text) if t.endswith("층") else
                   _numbered(t, "호", text) if t.endswith("호") else norm(t) in norm(text) for t in tokens)
    return norm(value) in norm(text)


def _area_in_line(value: float, text: str, unit_pattern: str) -> bool:
    number = f"{value:g}"
    return re.search(rf"(?<![\d.]){re.escape(number)}\s*{unit_pattern}", text) is not None


# ------------------------------------------------------------------ 시각·날짜

_HOUR_WORDS = {"열두": 12, "열한": 11, "열": 10, "한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5,
               "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9}
_MIN_WORDS = {"십오": 15, "삼십": 30, "사십오": 45, "이십": 20, "사십": 40, "오십": 50, "십": 10}
_TIME = re.compile(
    r"(오전|오후|아침|낮|저녁|밤)?\s*"
    r"(\d{1,2}|" + "|".join(sorted(_HOUR_WORDS, key=len, reverse=True)) + r")\s*시(?!\s*간|세)"
    r"(?:\s*(반)|\s*(\d{1,2}|" + "|".join(sorted(_MIN_WORDS, key=len, reverse=True)) + r")\s*분)?"
)


@dataclass
class TimeMention:
    hours: tuple[int, ...]  # 오전·오후가 없으면 두 후보
    minute: int
    start: int
    end: int


def time_mentions(text: str) -> list[TimeMention]:
    found = []
    for m in _TIME.finditer(text):
        period, hour_text, half, minute_text = m.groups()
        hour = int(hour_text) if hour_text.isdigit() else _HOUR_WORDS[hour_text]
        if hour > 24:
            continue
        minute = 30 if half else (int(minute_text) if minute_text and minute_text.isdigit()
                                  else _MIN_WORDS.get(minute_text or "", 0))
        if period in ("오후", "저녁", "밤") and hour < 12:
            hours: tuple[int, ...] = (hour + 12,)
        elif period == "낮":
            hours = (hour if hour >= 11 else hour + 12,)
        elif period in ("오전", "아침") or hour >= 13:
            hours = (hour % 24,)
        else:
            hours = (hour, (hour + 12) % 24)
        found.append(TimeMention(hours, minute, m.start(), m.end()))
    return found


def find_time(dt: datetime, text: str) -> Optional[TimeMention]:
    """그 줄에 그 시·분이 있고, 바로 뒤에서 거절('2시는 힘들고')하지 않았는지."""
    dt = dt.astimezone(KST)
    mentions = time_mentions(text)
    for i, mention in enumerate(mentions):
        if dt.hour in mention.hours and dt.minute == mention.minute:
            tail_end = mentions[i + 1].start if i + 1 < len(mentions) else len(text)
            if _TIME_NO.search(text[mention.end:tail_end]):
                return None
            return mention
    return None


_KMONTH_DAY = re.compile(r"(?:([일이삼사오육칠팔구십유시]+)\s*월\s*)?([일이삼사오육칠팔구십]+)\s*일(?!\s*(?:간|정도|째|이내|안에))")


def _korean_month(token: str) -> Optional[int]:
    return {"유": 6, "시": 10}.get(token) or parse_korean(token)


def _date_matches(day: date, text: str, called_at: Optional[datetime]) -> Optional[bool]:
    """그 글에 날짜 표현이 있으면 맞는지(True/False), 없으면 None. '11월 23일'과 '십일월 이십삼일' 모두."""
    seen = None
    for m in _KMONTH_DAY.finditer(text):  # 실시간 전사는 AI가 읽은 대로 한글로 적음(11-21)
        month = _korean_month(m.group(1)) if m.group(1) else None
        dom = parse_korean(m.group(2))
        if not dom or dom > 31 or (m.group(1) and not month):
            continue
        seen = False
        if dom == day.day and (not month or month == day.month):
            return True
    for m in _WEEKDAY.finditer(text):
        seen = False
        if DAYS.index(m.group(2)) == day.weekday():
            return True
    for m in _MONTH_DAY.finditer(text):
        month, dom = m.group(1), int(m.group(2))
        if dom > 31:
            continue
        seen = False
        if dom == day.day and (not month or int(month) == day.month):
            return True
    if called_at:
        base = called_at.astimezone(KST).date()
        for word, offset in (("오늘", 0), ("내일", 1), ("모레", 2)):
            if word in text:
                seen = False
                if base + timedelta(days=offset) == day:
                    return True
    return seen


def date_confirmed(day: date, lines: list[dict], n: int, before: str, called_at: Optional[datetime],
                   candidate_days: set[date]) -> bool:
    """날짜는 그 줄(시각 앞)이나 바로 앞 두 줄의 날짜 표현으로. 없으면 후보 날짜가 하나뿐일 때만."""
    verdict = _date_matches(day, before, called_at)
    if verdict is not None:
        return verdict
    for k in (n - 1, n - 2):
        if k >= 0:
            verdict = _date_matches(day, lines[k].get("text") or "", called_at)
            if verdict is not None:
                return verdict
    return candidate_days == {day}


# ------------------------------------------------------------------ 전사 보정(건물 이름·되읽기)

_CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
_JONG = ("", *"ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ")


def jamo(text: str) -> str:
    """'해든' → 'ㅎㅐㄷㅡㄴ'."""
    out = []
    for ch in text:
        if "가" <= ch <= "힣":
            code = ord(ch) - 0xAC00
            out.append(_CHO[code // 588] + _JUNG[code % 588 // 28] + _JONG[code % 28])
        else:
            out.append(ch)
    return "".join(out)


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def match_known_name(heard: Optional[str], known: list[str]) -> Optional[str]:
    """전사된 건물 이름을 아는 이름(요청의 참고 건물 등)에 맞춘다.

    일반 단어(빌라·오피스텔…)를 뺀 글자 수가 같고 자모가 거의 같을 때만: 3글자까지 자모 1개, 4글자부터 2개.
    '헤든빌라' → '해든빌라'는 맞추고, '해변빌라'는 다른 건물일 수 있어 맞추지 않는다.
    """
    heard_key = building_key(heard)
    if not heard_key:
        return None
    for name in known:
        key = building_key(name)
        if not key:
            continue
        if key == heard_key:
            return name
        limit = 1 if len(key) <= 3 else 2
        if len(key) == len(heard_key) and _edit_distance(jamo(key), jamo(heard_key)) <= limit:
            return name
    return None


_FILLER = re.compile(r"^\s*(?:네|예|아|아네|그럼|그러면)[,.\s]+")
_MOVE_IN_PREFIX = re.compile(r"^\s*입주\s*(?:는|가|일은|일이|가능일은|가능일이|가능\s*시기는|시기는)?\s*")
_READ_BACK_TAIL = re.compile(
    r"\s*(?:가능(?:한|하신)?\s*)?(?:거|건)?\s*"
    r"(?:이요|요|인가요|이죠|죠|이시죠|맞죠|맞으시죠|맞나요|이신가요|시죠|인\s*거죠|맞으세요)?\s*[?.!]*\s*$")
_READ_BACK_END = re.compile(r"(\?|요|죠)[.!]?\s*$")


def read_back_phrase(text: str) -> str:
    """'네, 다음 달 초부터요?' → '다음 달 초부터'."""
    phrase = text.strip()
    while _FILLER.match(phrase):
        phrase = _FILLER.sub("", phrase, count=1)
    phrase = _MOVE_IN_PREFIX.sub("", phrase)
    return _READ_BACK_TAIL.sub("", phrase).strip()


# ------------------------------------------------------------------ 근거 대조


def _line_no(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    if isinstance(value, list) and value:
        return _line_no(value[0])
    return None


class _Checker:
    def __init__(self, request: CallRequest, lines: list[dict], called_at: Optional[datetime]):
        self.request = request
        self.lines = lines
        self.called_at = called_at
        self.evidence: dict[str, int] = {}
        self.unverified: list[str] = []
        self.corrections: list[dict] = []

    def broker_line(self, n: Optional[int]) -> Optional[str]:
        if n is None or not 0 <= n < len(self.lines) or self.lines[n].get("speaker") != "broker":
            return None
        return self.lines[n].get("text") or ""

    def broker_lines(self) -> list[int]:
        return [i for i, line in enumerate(self.lines) if line.get("speaker") == "broker"]

    def next_broker(self, n: int, count: int = 2) -> list[int]:
        return [i for i in self.broker_lines() if i > n][:count]

    def prev_broker(self, n: int, count: int = 2) -> list[int]:
        return [i for i in self.broker_lines() if i < n][-count:]

    def ai_numbers(self, n: int) -> list[float]:
        """n 앞의 가장 가까운 AI 말에 나온 금액(되풀이 판단용)."""
        for k in range(n - 1, -1, -1):
            if self.lines[k].get("speaker") == "ai":
                return [m.value for m in money_mentions(self.lines[k].get("text") or "")]
        return []

    # 금액 ----------------------------------------------------------------
    def money(self, key: str, field: str, value: Any, n: Optional[int], others: list[float]) -> Optional[float]:
        """금액 하나를 근거 줄과 대조하고 정정·되풀이·불확실을 처리한다."""
        try:
            value = float(value)
        except (TypeError, ValueError):
            self.unverified.append(key)
            return None
        text = self.broker_line(n)
        mention = find_money(value, text, field) if text is not None else None
        if mention is None:  # 근거 줄이 틀렸으면 중개사 말에서 찾아봄
            for k in self.broker_lines():
                mention = find_money(value, self.lines[k]["text"], field)
                if mention:
                    n, text = k, self.lines[k]["text"]
                    break
        if mention is None:
            self.unverified.append(key)
            return None
        if _HEDGE.search(text[mention.start:]):
            self.corrections.append({"field": key, "dropped": _num(value), "reason": "hedged", "line": n})
            self.unverified.append(key)
            return None

        later = self._later_value(field, value, n, mention, others)
        if later is not None:
            new_value, new_line, reason = later
            self.corrections.append({"field": key, "value": _num(new_value), "reason": "corrected_value", "line": new_line})
            self.corrections.append({"field": key, "dropped": _num(value), "reason": reason, "line": n})
            self.evidence[key] = new_line
            return new_value

        earlier = self._earlier_value(field, value, n, mention, others)
        if earlier is not None:
            old_value, old_line, reason = earlier
            self.corrections.append({"field": key, "value": _num(value), "reason": "corrected_value", "line": n})
            self.corrections.append({"field": key, "dropped": _num(old_value), "reason": reason, "line": old_line})
        self.evidence[key] = n
        return value

    def _candidates(self, field: str, value: float, others: list[float], text: str, start: int):
        for m in money_mentions(text):
            if m.start < start or m.pair:
                continue
            if _similar(m.value, value) and not any(_same(m.value, o) for o in others):
                yield m

    def _later_value(self, field, value, n, mention, others):
        """그 값 뒤에 고치는 말과 비슷한 크기의 다른 값이 나오면(다음 중개사 말 두 줄까지) 고치기 전 값."""
        text = self.lines[n]["text"]
        echoed = any(_same(value, a) for a in self.ai_numbers(n))
        rest = text[mention.end:]
        marker = _CORRECTION.search(rest)
        if marker or echoed:
            start = mention.end + (marker.end() if marker else 0)
            for m in self._candidates(field, value, others, text, start):
                return m.value, n, "echoed" if echoed and not marker else "corrected"
        for k in self.next_broker(n):  # 다음 중개사 말 두 줄까지: 고치는 말 뒤의 다른 값
            line = self.lines[k]["text"]
            line_marker = _CORRECTION.search(line)
            if line_marker:
                for m in self._candidates(field, value, others, line, line_marker.end()):
                    return m.value, k, "corrected"
        return None

    def _earlier_value(self, field, value, n, mention, others):
        """그 값이 고친 뒤 값이면(앞에 비슷한 값 + 고치는 말) 고치기 전 값을 돌려준다."""
        text = self.lines[n]["text"]
        before = text[:mention.start]
        for m in reversed(money_mentions(before)):
            if m.pair or not _similar(m.value, value) or any(_same(m.value, o) for o in others):
                continue
            if _CORRECTION.search(before[m.end:]):
                return m.value, n, "corrected"
            if any(_same(m.value, a) for a in self.ai_numbers(n)):
                return m.value, n, "echoed"
        if _CORRECTION.search(before):
            for k in reversed(self.prev_broker(n)):
                for m in reversed(money_mentions(self.lines[k]["text"])):
                    if not m.pair and _similar(m.value, value) and not any(_same(m.value, o) for o in others):
                        return m.value, k, "corrected"
        return None

    # 되읽기 -------------------------------------------------------------
    def read_back(self, heard: Optional[str], n: Optional[int]) -> Optional[tuple[str, int]]:
        """중개사 말(n) 바로 뒤 AI가 들은 표현을 되묻고('다음 달 초부터요?') 중개사가 거절·정정 없이 '네'로
        받으면, 또렷하게 전사된 AI 쪽 표현과 그 대답 줄. 전사가 중개사 말을 틀리게 적은 경우를 위해(11-21 '추석')."""
        if n is None:
            return None
        for k in range(n + 1, min(n + 3, len(self.lines) - 1)):
            if self.lines[k].get("speaker") != "ai":
                continue
            text = (self.lines[k].get("text") or "").strip()
            answer = self.lines[k + 1]
            phrase = read_back_phrase(text)
            if not _READ_BACK_END.search(text) or not phrase:
                return None
            if heard and SequenceMatcher(None, norm(phrase), norm(heard)).ratio() < 0.5:
                return None  # 다른 질문
            reply = answer.get("text") or ""
            if (answer.get("speaker") == "broker" and _ACCEPT.search(reply)
                    and not _REFUSE.search(reply) and not _CORRECTION.search(reply)):
                return phrase, k + 1
            return None
        return None

    # 글자·면적 ----------------------------------------------------------
    def text(self, key: str, field: str, value: Any, n: Optional[int]) -> Optional[str]:
        if value in (None, ""):
            return None
        value = str(value).strip()
        candidates = [n] + [k for k in self.broker_lines() if k != n]
        for k in candidates:
            line = self.broker_line(k)
            if line is not None and text_in_line(field, value, line):
                if _HEDGE.search(line) and field in ("move_in",):
                    break
                self.evidence[key] = k
                return value
        self.unverified.append(key)
        return None

    def area(self, key: str, item: dict, ev: dict) -> Optional[float]:
        for field, unit, factor in (("area_m2", r"(?:㎡|제곱|평방|m)", 1.0), ("area_pyeong", r"평", PYEONG_M2)):
            value = item.get(field)
            if value in (None, ""):
                continue
            try:
                value = float(value)
            except (TypeError, ValueError):
                break
            n = _line_no(ev.get(field))
            for k in [n] + [k for k in self.broker_lines() if k != n]:
                line = self.broker_line(k)
                if line is not None and _area_in_line(value, line, unit):
                    self.evidence[key] = k
                    return round(value * factor, 1)
            break
        if item.get("area_m2") not in (None, "") or item.get("area_pyeong") not in (None, ""):
            self.unverified.append(key)
        return None

    # 그 밖의 값 ----------------------------------------------------------
    def plain(self, key: str, value: Any, n: Optional[int]) -> Any:
        """근거 줄이 중개사 말이어야 하는 값(반려동물·등기부 답)."""
        if value is None:
            return None
        if self.broker_line(n) is None:
            self.unverified.append(key)
            return None
        self.evidence[key] = n
        return value

    def slot_time(self, value: Any, n: Optional[int], candidate_days: set[date]) -> tuple[Optional[datetime], Optional[int]]:
        """시각을 근거 줄(없으면 중개사 말)과 대조: 시·분은 그 줄, 날짜는 그 줄이나 앞 두 줄."""
        try:
            dt = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None, None
        dt = dt.replace(tzinfo=KST) if dt.tzinfo is None else dt.astimezone(KST)
        for k in [n] + [k for k in self.broker_lines() if k != n]:
            line = self.broker_line(k)
            if line is None:
                continue
            mention = find_time(dt, line)
            if mention and date_confirmed(dt.date(), self.lines, k, line[:mention.start], self.called_at, candidate_days):
                return dt, k
        return None, None


def _num(value: float) -> float | int:
    return int(value) if float(value).is_integer() else value


def _quotes(lines: list[dict], evidence: dict[str, int], corrections: list[dict]) -> dict[str, dict]:
    used = set(evidence.values()) | {c["line"] for c in corrections if c.get("line") is not None}
    quotes = {}
    for n in sorted(used):
        if 0 <= n < len(lines):
            line = lines[n]
            quotes[str(n)] = {k: line[k] for k in ("speaker", "text", "start", "end") if line.get(k) is not None}
    return quotes


def in_user_window(start: datetime, windows: list) -> bool:
    return any(w.start <= start < w.end for w in windows)


def empty_result() -> dict:
    return {
        "listings": [], "broker_slots": [], "availability_note": None, "pet_allowed": None,
        "registry_reply": None, "unverified": [], "corrections": [], "evidence": {}, "quotes": {},
        "transcript": [], "sms_draft": None, "timing": None, "warnings": [],
    }


# ------------------------------------------------------------------ 결론: 문의 통화


def decide_inquiry(request: CallRequest, raw: Optional[dict], lines: list[dict],
                   called_at: Optional[datetime] = None) -> dict:
    result = empty_result()
    if raw is None:
        result["outcome"] = "unclear"
        return result
    check = _Checker(request, lines, called_at)
    items = [item for item in (raw.get("listings") or []) if isinstance(item, dict)][:MAX_LISTINGS]

    listings = []
    for item in items:
        i = len(listings)
        ev = item.get("evidence") or {}
        # 정정 비교에서 뺄 값: 다른 방의 같은 항목 + 같은 방의 다른 금액 항목
        others_by_field = {
            f: [float(o[g]) for o in items for g in MONEY_FIELDS
                if (o is not item and g == f or o is item and g != f)
                and isinstance(o.get(g), (int, float)) and not isinstance(o.get(g), bool)]
            for f in MONEY_FIELDS
        }
        before = (len(check.unverified), len(check.corrections), dict(check.evidence))
        room: dict[str, Any] = {}
        for field in LISTING_FIELDS:
            key = f"listings[{i}].{field}"
            if field in MONEY_FIELDS:
                value = item.get(field)
                room[field] = None if value is None else _num_or_none(
                    check.money(key, field, value, _line_no(ev.get(field)), others_by_field[field]))
            elif field == "area_m2":
                room[field] = check.area(key, item, ev)
            else:
                room[field] = check.text(key, field, item.get(field), _line_no(ev.get(field)))
        if any(v is not None for v in room.values()):
            _fix_transcription(check, request, room, item, ev, i)
            listings.append(room)
        else:  # 확인된 값이 하나도 없는 방은 결과에 넣지 않음
            check.unverified = check.unverified[:before[0]]
            check.corrections = check.corrections[:before[1]]
            check.evidence = before[2]

    windows = request.windows
    candidate_days = {w.start.astimezone(KST).date() for w in windows} | {w.end.astimezone(KST).date() for w in windows}
    slots = []
    for j, slot in enumerate([s for s in (raw.get("broker_slots") or []) if isinstance(s, dict)][:MAX_SLOTS]):
        start, n = _confirm_time(check, slot.get("start"), _line_no(slot.get("evidence")), candidate_days, True)
        if start is None:
            check.unverified.append(f"broker_slots[{j}]")
            continue
        end = _slot_end(lines, n, start, _iso_dt(slot.get("end")))
        check.evidence[f"broker_slots[{len(slots)}]"] = n
        slots.append({"start": start.isoformat(), "end": end.isoformat() if end else None,
                      "in_user_window": in_user_window(start, windows)})
    if not slots:  # LLM이 '구체적 시각 없음'으로 비워도, 시각을 넣어 물은 질문에 '네'만 했으면 그 시각
        for start, end, n in _accepted_slots(lines, candidate_days, called_at)[:MAX_SLOTS]:
            check.evidence[f"broker_slots[{len(slots)}]"] = n
            slots.append({"start": start.isoformat(), "end": end.isoformat() if end else None,
                          "in_user_window": in_user_window(start, windows)})

    top_ev = raw.get("evidence") or {}
    pet = check.plain("pet_allowed", raw.get("pet_allowed") if isinstance(raw.get("pet_allowed"), bool) else None,
                      _line_no(top_ev.get("pet_allowed")))
    reply = raw.get("registry_reply") if raw.get("registry_reply") in ("will_send", "at_visit", "refused") else None
    reply = check.plain("registry_reply", reply, _line_no(top_ev.get("registry_reply")))
    note = check.text("availability_note", "availability_note", raw.get("availability_note"),
                      _line_no(top_ev.get("availability_note")))

    if raw.get("voicemail"):
        outcome = "no_answer"
    elif raw.get("declined") and not listings:
        outcome = "declined"
    elif listings:
        outcome = "listing"
    elif raw.get("available") is False:
        outcome = "no_listing"
    else:
        outcome = "unclear"

    result.update(
        outcome=outcome, listings=listings, broker_slots=slots, availability_note=note,
        pet_allowed=pet, registry_reply=reply, unverified=check.unverified, corrections=check.corrections,
        evidence=check.evidence, quotes=_quotes(lines, check.evidence, check.corrections),
    )
    return result


def _fix_transcription(check: "_Checker", request: CallRequest, room: dict, item: dict, ev: dict, i: int) -> None:
    """전사 보정: 건물 이름은 아는 이름에, 입주 시기는 AI가 되읽고 중개사가 '네'라고 한 표현으로."""
    known = [name for name in (request.search.ref_building,) if name]
    heard = room.get("building")
    name = match_known_name(heard, known) if heard else None
    if name and name != heard:
        key = f"listings[{i}].building"
        check.corrections.append({"field": key, "value": name, "heard": heard, "reason": "name_matched",
                                  "line": check.evidence.get(key)})
        room["building"] = name
        if room.get("location"):
            room["location"] = room["location"].replace(heard, name)

    key = f"listings[{i}].move_in"
    heard = room.get("move_in") or (str(item["move_in"]) if item.get("move_in") else None)
    if not heard:
        return
    found = check.read_back(heard, check.evidence.get(key, _line_no(ev.get("move_in"))))
    if not found:
        return
    phrase, line = found
    if norm(phrase) != norm(heard):
        check.corrections.append({"field": key, "value": phrase, "heard": heard, "reason": "read_back", "line": line})
        room["move_in"] = phrase
    check.evidence[key] = line
    if key in check.unverified:
        check.unverified.remove(key)


def _slot_end(lines: list[dict], n: int, start: datetime, end: Optional[datetime]) -> Optional[datetime]:
    """끝 시각은 말했을 때만: 근거 줄에, 또는 '네'만 한 경우 바로 앞 AI 질문에 그 시각이 있어야 한다."""
    if end is None or end <= start:
        return None
    if find_time(end, lines[n].get("text") or ""):
        return end
    if n > 0 and lines[n - 1].get("speaker") == "ai" and not time_mentions(lines[n].get("text") or ""):
        if find_time(end, lines[n - 1].get("text") or ""):
            return end
    return None


def _accepted_slots(lines: list[dict], candidate_days: set[date],
                    called_at: Optional[datetime]) -> list[tuple[datetime, Optional[datetime], int]]:
    """AI가 날짜·시각을 넣어 물은 질문('11월 23일 월요일 오후 2시부터 5시 사이에 볼 수 있을까요?')에
    중개사가 거절·다른 시각 없이 '네'만 한 경우 → (시작, 끝, 대답 줄). 11-21 리허설."""
    found = []
    for n in range(1, len(lines)):
        question = lines[n - 1]
        if question.get("speaker") != "ai" or lines[n].get("speaker") != "broker":
            continue
        mentions = time_mentions(question.get("text") or "")
        if not mentions:
            continue
        for day in sorted(candidate_days) or [None]:
            if day is None:
                break
            first = mentions[0]
            hour = next((h for h in first.hours if 7 <= h <= 21), first.hours[0])
            start = datetime(day.year, day.month, day.day, hour, first.minute, tzinfo=KST)
            if _accepted_time(start, lines, n, candidate_days, called_at):
                end = None
                if len(mentions) > 1:
                    last = mentions[1]
                    end_hour = next((h for h in last.hours if h > hour), last.hours[0])
                    candidate = datetime(day.year, day.month, day.day, end_hour % 24, last.minute, tzinfo=KST)
                    end = candidate if candidate > start else None
                found.append((start, end, n))
                break
    return found


def _num_or_none(value: Optional[float]):
    return None if value is None else _num(value)


# ------------------------------------------------------------------ 결론: 확정 통화

ROOM_STATUS = {"confirmed": "confirmed", "alternative": "needs_approval"}  # 나머지는 not_scheduled
VISIT_STATUS = {"confirmed": "confirmed", "partial": "partially_confirmed", "alternative": "needs_approval"}


def room_status(outcome: Optional[str]) -> str:
    """방별 outcome → visit_status. 통화 전·중(outcome 없음)은 requesting."""
    if outcome is None:
        return "requesting"
    return ROOM_STATUS.get(outcome, "not_scheduled")


def visit_status(outcome: Optional[str]) -> str:
    if outcome is None:
        return "requesting"
    return VISIT_STATUS.get(outcome, "not_scheduled")


def _target(request: CallRequest) -> dict:
    return {"rooms": [{"listing_index": r.listing_index, "at": r.at.isoformat(), "place": r.place or None,
                       "alternatives": [{"start": w.start.isoformat(), "end": w.end.isoformat()} for w in r.alternatives]}
                      for r in request.target.rooms]}


def empty_confirm_result(request: CallRequest, outcome: Optional[str] = None) -> dict:
    """확정 통화의 빈 결과. outcome이 없으면 '요청 중', 있으면 모든 방이 그 결과(안 받음·거절 등)."""
    rooms = [{"listing_index": r.listing_index, "at": r.at.isoformat(), "outcome": outcome,
              "visit_status": room_status(outcome), "visit": None, "proposal": None,
              "still_available": None, "same_listing": None, "unit": None} for r in request.target.rooms]
    result = {**empty_result(), "target": _target(request), "visit_status": visit_status(outcome), "rooms": rooms}
    for key in ("listings", "broker_slots", "availability_note", "pet_allowed", "registry_reply"):
        result.pop(key, None)
    result.update(_outer(rooms))
    return result


def _outer(rooms: list[dict]) -> dict:
    """방이 하나면 rooms[0]의 값이 바깥에도(예전 형식 호환), 여럿이면 null."""
    keys = ("visit", "proposal", "still_available", "same_listing", "unit")
    if len(rooms) == 1:
        return {k: rooms[0][k] for k in keys}
    return {k: None for k in keys}


def _accepted_time(dt: datetime, lines: list[dict], n: int, candidate_days: set[date],
                   called_at: Optional[datetime]) -> bool:
    """AI가 시각을 넣어 묻고('… 오후 2시에 뵐 수 있을까요?'), 바로 다음 중개사 말이 거절이나
    다른 시각 없이 '당연하죠/네/괜찮아요'면 그 시각을 합의로 본다 (lessons L8).
    근거 줄은 중개사의 대답, 날짜는 질문 줄로 확인."""
    if not (0 < n < len(lines)) or lines[n].get("speaker") != "broker" or lines[n - 1].get("speaker") != "ai":
        return False
    question, answer = (lines[n - 1].get("text") or "").strip(), (lines[n].get("text") or "").strip()
    if not _ASKS.search(question) or not _ACCEPT.search(answer) or _REFUSE.search(answer) or time_mentions(answer):
        return False
    mention = find_time(dt, question)
    if mention is None:
        return False
    verdict = _date_matches(dt.date(), question, called_at)
    return verdict if verdict is not None else candidate_days == {dt.date()}


def _iso_dt(value: Any) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return dt.replace(tzinfo=KST) if dt.tzinfo is None else dt.astimezone(KST)


def _confirm_time(check: "_Checker", value: Any, n: Optional[int], candidate_days: set[date],
                  accept_plain_yes: bool) -> tuple[Optional[datetime], Optional[int]]:
    dt = _iso_dt(value)
    if dt is None:
        return None, None
    found, k = check.slot_time(dt.isoformat(), n, candidate_days)
    if found:
        return found, k
    if accept_plain_yes:
        for k in [n] + [i for i in check.broker_lines() if i != n]:
            if k is not None and _accepted_time(dt, check.lines, k, candidate_days, check.called_at):
                return dt, k
    return None, None


def _in_range(at: datetime, room) -> bool:
    if at == room.at:
        return True
    return any(w.start <= at <= w.end for w in room.alternatives)


def decide_confirm(request: CallRequest, raw: Optional[dict], lines: list[dict],
                   called_at: Optional[datetime] = None) -> dict:
    target_rooms = request.target.rooms
    if raw is None:
        result = empty_confirm_result(request, "unclear")
        result["outcome"] = "unclear"
        return result
    if raw.get("voicemail") or raw.get("declined"):
        outcome = "no_answer" if raw.get("voicemail") else "declined"
        result = empty_confirm_result(request, outcome)
        result["outcome"] = outcome
        return result

    check = _Checker(request, lines, called_at)
    raw_rooms = [r for r in (raw.get("rooms") or []) if isinstance(r, dict)]
    many = len(target_rooms) > 1
    rooms = []
    for i, room in enumerate(target_rooms):
        prefix = f"rooms[{i}]." if many else ""
        found = next((r for r in raw_rooms if _line_no(r.get("index")) == i), None)
        if found is None and not many and len(raw_rooms) == 1:
            found = raw_rooms[0]
        found = found or {}
        ev = found.get("evidence") or {}
        days = {room.at.date()} | {w.start.date() for w in room.alternatives} | {w.end.date() for w in room.alternatives}

        still = found.get("still_available") if isinstance(found.get("still_available"), bool) else None
        still = check.plain(prefix + "still_available", still, _line_no(ev.get("still_available")))
        same = found.get("same_listing") if isinstance(found.get("same_listing"), bool) else None
        same = check.plain(prefix + "same_listing", same, _line_no(ev.get("same_listing")))
        unit = check.text(prefix + "unit", "unit", found.get("unit"), _line_no(ev.get("unit")))

        agreed = found.get("agreed_visit") if isinstance(found.get("agreed_visit"), dict) else None
        proposed = found.get("proposed_visit") if isinstance(found.get("proposed_visit"), dict) else None
        agreed_at = proposal_at = None
        if agreed:
            agreed_at, k = _confirm_time(check, agreed.get("at"), _line_no(ev.get("visit.at")), days, True)
            if agreed_at:
                check.evidence[prefix + "visit.at"] = k
            else:
                check.unverified.append(prefix + "visit.at")
        if proposed:
            proposal_at, k = _confirm_time(check, proposed.get("at"), _line_no(ev.get("proposal.at")), days, False)
            if proposal_at:
                check.evidence[prefix + "proposal.at"] = k
            else:
                check.unverified.append(prefix + "proposal.at")

        visit = proposal = None
        if still is False:
            outcome = "unavailable"
        elif agreed_at and _in_range(agreed_at, room):
            outcome = "confirmed"
            place = agreed.get("place")
            if not (place and any(norm(w) in norm(" ".join(l.get("text") or "" for l in lines if l.get("speaker") == "broker"))
                                  for w in str(place).split() if len(w) >= 2)):
                place = room.place or f"{request.broker.name} 사무소"
            visit = {"at": agreed_at.isoformat(), "place": place, "listing_index": room.listing_index}
        elif agreed_at or proposal_at:
            outcome = "alternative"
            at = agreed_at or proposal_at
            note = (proposed or {}).get("note") if proposal_at else "범위 밖 시각에 합의함(사용자 승인 필요)"
            proposal = {"at": at.isoformat(), "note": note}
        elif still is True or same is not None or unit:
            outcome = "no_time"
        else:
            outcome = "unclear"
        rooms.append({"listing_index": room.listing_index, "at": room.at.isoformat(), "outcome": outcome,
                      "visit_status": room_status(outcome), "visit": visit, "proposal": proposal,
                      "still_available": still, "same_listing": same, "unit": unit})

    outcomes = [r["outcome"] for r in rooms]
    if all(o == "confirmed" for o in outcomes):
        overall = "confirmed"
    elif "confirmed" in outcomes:
        overall = "partial"
    elif "alternative" in outcomes:
        overall = "alternative"
    elif "no_time" in outcomes:
        overall = "no_time"
    elif all(o == "unavailable" for o in outcomes):
        overall = "unavailable"
    else:
        overall = "unclear"

    result = empty_confirm_result(request)
    result.update(rooms=rooms, visit_status=visit_status(overall), unverified=check.unverified,
                  evidence=check.evidence, quotes=_quotes(lines, check.evidence, check.corrections),
                  corrections=check.corrections, outcome=overall)
    result.update(_outer(rooms))
    return result


# ------------------------------------------------------------------ 입구


def decide(request: CallRequest, raw: Optional[dict], transcript: list[dict],
           called_at: Optional[datetime] = None, timing_transcript: Optional[list[dict]] = None) -> dict:
    """대화록과 추출 값 → 결과(outcome 포함). 문의·확정을 자동으로 고른다.
    timing_transcript: 줄마다 시각이 있는 대화록(사후 전사). 실시간 전사로 판정할 때 속도 측정에만 쓴다."""
    lines = label_speakers(transcript)
    if request.kind == "confirm":
        result = decide_confirm(request, raw, lines, called_at)
    else:
        result = decide_inquiry(request, raw, lines, called_at)
    result["timing"] = turn_timing(label_speakers(timing_transcript) if timing_transcript else lines)
    result["transcript"] = lines if request.keep_transcript else []
    result["warnings"] = call_warnings(lines)
    return result


# 상대에게 하는 말이 아닌 지시에 대한 대답·상태 보고(11-21: "네, 지금 하겠습니다", "통화 마쳤습니다")
_META_TALK = re.compile(r"(지금\s*하겠습니다|통화(를)?\s*(마쳤|마치겠|종료|끝났|끝내겠)|정리하겠습니다|마무리하겠습니다"
                        r"|종료하겠습니다|확인\s*말씀드릴게요|차근차근\s*여쭤볼게요)")
_DISCLOSURE = re.compile(r"(AI\s*비서|에이아이\s*비서|인공지능|살구)")


def call_warnings(lines: list[dict]) -> list[str]:
    """반드시 지킬 것을 어긴 통화 표시. ai_disclosure_missing: 첫 AI 말에 'AI 비서 살구' 고지가 없음
    (11-21 리허설에서 살구가 엉뚱한 이야기로 통화를 시작함)."""
    # 실시간 전사가 받는 쪽의 첫마디('네, 한빛입니다.')를 agent로 붙일 때가 있어 그런 줄은 건너뜀(11-21)
    first_ai = next((line for line in lines if line.get("speaker") == "ai"
                     and not (PICKUP.search(line.get("text") or "") and len(line.get("text") or "") <= 20
                              and not _DISCLOSURE.search(line.get("text") or ""))), None)
    warnings = []
    if first_ai is not None and not _DISCLOSURE.search(first_ai.get("text") or ""):
        warnings.append("ai_disclosure_missing")
    if any(_META_TALK.search(line.get("text") or "") for line in lines if line.get("speaker") == "ai"):
        warnings.append("ai_meta_talk")
    return warnings


# ------------------------------------------------------------------ LLM


def _spoken_now(dt: datetime) -> str:
    return when(dt.astimezone(KST))


def user_message(request: CallRequest, lines: list[dict], called_at: Optional[datetime]) -> str:
    called = called_at or datetime.now(KST)
    parts = [f"통화한 날: {_spoken_now(called)}"]
    s = request.search
    if request.kind == "confirm" and request.target:
        parts.append("확정하려는 방:")
        for i, room in enumerate(request.target.rooms):
            name = room.listing.location or " ".join(x for x in (room.listing.building, room.listing.floor) if x) or "문의한 방"
            alts = ", ".join(f"{window_text(w)} ({w.start.isoformat()} ~ {w.end.isoformat()})" for w in room.alternatives)
            parts.append(f"{i}) {name} / 요청 시각 {when(room.at)} ({room.at.isoformat()}) / 대안 범위: {alts or '없음'}")
    else:
        windows = request.windows
        if windows:
            text = ", ".join(f"{window_text(w)} ({w.start.isoformat()} ~ {w.end.isoformat()})" for w in windows)
        else:
            text = "없음"
        parts.append(f"손님이 가능한 방문 시간: {text}")
        place = f"{s.dong} {s.ref_building} 또는 그 근처" if s.ref_building else f"{s.dong} 또는 그 근처"
        parts.append(f"물어본 조건: {place}, 보증금 {s.deposit_manwon} / 월세 {s.monthly_rent_manwon} (만원) 정도")
    parts += ["", "대화록:"]
    parts += [f"{i} [{line.get('speaker')}] {line.get('text')}" for i, line in enumerate(lines)]
    return "\n".join(parts)


class LLMExtractor:
    """OpenAI 호환 chat/completions(JSON 응답)으로 값과 근거 줄 번호를 찾는다."""

    def __init__(self, settings: Settings, client: Optional[httpx.Client] = None):
        self.settings = settings
        self.client = client or httpx.Client(timeout=90)

    def extract(self, request: CallRequest, transcript: list[dict], called_at: Optional[datetime]) -> Optional[dict]:
        if not self.settings.openai_api_key or not transcript:
            return None
        lines = label_speakers(transcript)
        body = {
            "model": self.settings.llm_model or "gpt-6-luna",
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": CONFIRM_PROMPT if request.kind == "confirm" else INQUIRY_PROMPT},
                {"role": "user", "content": user_message(request, lines, called_at)},
            ],
        }
        try:
            response = self.client.post(
                f"{self.settings.openai_base_url.rstrip('/')}/chat/completions", json=body,
                headers={"Authorization": f"Bearer {self.settings.openai_api_key}"})
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            data = json.loads(content)
        except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError):
            return None
        return data if isinstance(data, dict) else None
