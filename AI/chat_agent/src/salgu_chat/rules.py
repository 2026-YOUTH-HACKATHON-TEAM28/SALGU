"""규칙 파서: 사용자 말에서 숫자·회사 위치·주택 유형 등을 LLM 없이 바로 뽑아 조건 카드를 만든다.

두 군데서 쓴다.
1. 빠른 길: 흔한 말("회사 강남역, 1000/50 오피스텔")이면 Gemini를 부르지 않고 바로 카드를 만든다.
2. 방지 장치 기준값: Gemini 카드의 숫자가 사용자가 실제로 말한 숫자와 같은지 대조한다.
"""

import re

_MONEY = r"(\d+(?:\.\d+)?\s*억(?:\s*\d[\d,]*\s*천?)?|\d[\d,]*\s*천|\d[\d,]*)"
_LABEL = r"[가-힣A-Za-z0-9]+"
_WORD = r"[가-힣A-Za-z][가-힣A-Za-z0-9]*"
_STOP_LABELS = {"지역", "구역", "역", "우리", "내", "제", "저희", "다니는", "다녀", "근처", "회사", "직장", "학교", "사무실", "저는", "나는", "난"}
_VERBISH = re.compile(r"다니|다녀|는데|어요|아요|해요|니다|에서$|으로$")
# 어떤 말이 있으면 규칙만으로 확정하지 않고 Gemini에 맡긴다 (부정·대체·살 곳 지정 등)
_NEEDS_LLM = re.compile(r"말고|아니|대신|빼고|제외|살고\s*싶|근처에\s*살|쪽에\s*살|동네(?:에서|로)|\?|상관없")
_QUESTION = re.compile(r"뭐(?:예요|에요|야|지)|뭔가요|무엇|이란|란\s*$|어떻게|왜|차이|설명|가능해|되나요|돼요\?")
_SEARCH_VERB = re.compile(r"찾아|구해|알아봐|추천|보여|살\s*집|집\s*좀|매물")
_UNVERIFIABLE = {"조용": "조용한", "채광": "채광", "햇빛": "햇빛", "밝은": "밝은", "뷰": "뷰", "치안": "치안", "분위기": "분위기"}
_FILLER = re.compile(r"찾아\s*줘?|구해\s*줘?|알아봐\s*줘?|추천해?\s*줘?|보여\s*줘?|해\s*줘|원해요?|싶어요?|정도로?|이하|이내|"
                     r"까지|안쪽|으로|이고|인데|는데|하고|그리고|있는|살\s*곳|살\s*집|집|방|매물|원룸|좀|주세요|해요|"
                     r"회사|직장|학교|사무실|다녀요|다니는|근무|저는|나는|요")

_WORKPLACE_PATTERNS = [
    re.compile(rf"({_LABEL}역)(?!세권)"),
    re.compile(rf"({_WORD})\s*(?:에\s*있는\s*)?(?:회사|직장|학교|사무실)"),
    re.compile(rf"(?:회사|직장|학교|사무실)(?:가|는|이)?\s*({_WORD})"),
    re.compile(rf"({_WORD}(?:\s+{_WORD})?)\s*(?:에|에서|로)?\s*(?:다녀|다니|근무|출근하)"),
]
_LABEL_TAIL = re.compile(r"(이고|인데|이에요|예요|이라|라서|이야|야)$")


def money(s):
    """금액 글 → 만 원 정수. 예: "1억 5천"→15000, "2천"→2000, "1,000"→1000."""
    s = re.sub(r"[\s,]|만\s*원?", "", s)
    if "억" in s:
        front, back = s.split("억", 1)
        return int(float(front) * 10000) + (money(back) if back else 0)
    if s.endswith("천"):
        return int(float(s[:-1] or 1) * 1000)
    return int(float(s)) if s else 0


def _cond(value, evidence, source="stated", reason=None, **extra):
    """조건 항목 하나."""
    c = {"value": value, "source": source, "evidence": evidence.strip(), **extra}
    if reason:
        c["reason"] = reason
    return c


def _workplace(t):
    """회사·학교 위치 → (label, 근거 구절). 없으면 (None, None)."""
    for pat in _WORKPLACE_PATTERNS:
        for m in pat.finditer(t):
            label = _LABEL_TAIL.sub("", m.group(1))
            if len(label) >= 2 and label not in _STOP_LABELS and not _VERBISH.search(label):
                return label, m.group(0)
    return None, None


def parse(text):
    """사용자 말 → {"intent", "card", "complete", "covered"}."""
    t = text.strip()
    conds, priorities, unverifiable = {}, [], []

    approx = bool(re.search(r"정도|쯤|안팎|내외|언저리", t))
    extra = {"approx": True} if approx else {}

    # 보증금/월세
    m = re.search(rf"{_MONEY}\s*/\s*(\d{{1,3}})(?!\d)", t)
    if m:
        conds["deposit_manwon"] = _cond(money(m.group(1)), m.group(0), **extra)
        conds["monthly_rent_manwon"] = _cond(int(m.group(2)), m.group(0), **extra)
    m = re.search(rf"보증금\s*(?:은|는|이|이고)?\s*{_MONEY}", t)
    if m:
        conds["deposit_manwon"] = _cond(money(m.group(1)), m.group(0))
    m = re.search(r"월세\s*(?:는|은|가|이)?\s*(\d{1,3})(?!\d)", t)
    if m:
        conds["monthly_rent_manwon"] = _cond(int(m.group(1)), m.group(0))

    # 주택 유형
    types = []
    if "오피스텔" in t:
        types.append("officetel")
    if re.search(r"빌라|연립|다세대", t):
        types.append("villa")
    if types:
        conds["housing_types"] = _cond(types, " ".join(re.findall(r"오피스텔|빌라|연립|다세대", t)))
    if "아파트" in t:
        unverifiable.append({"phrase": "아파트", "message": "아파트는 아직 지원하지 않아요(오피스텔·빌라만)"})

    # 회사 위치
    label, evidence = _workplace(t)
    if label:
        conds["workplace"] = _cond("place", evidence, label=label)

    # 통근 시간
    m = (re.search(r"(?:통근|출퇴근|출근|회사까지)[^\d]{0,12}(\d{1,3})\s*분", t)
         or re.search(r"(\d{1,3})\s*분\s*(?:안에|이내|안쪽|까지)?\s*(?:통근|출퇴근|출근)", t))
    if m:
        conds["max_commute_min"] = _cond(int(m.group(1)), m.group(0))

    # 환승
    m = re.search(r"환승\s*(\d)\s*(?:번|회)", t)
    if m:
        conds["max_transfers"] = _cond(int(m.group(1)), m.group(0))
    else:
        m = re.search(r"환승\s*(?:은|는|이)?\s*(?:없이|없는|없었|싫|안\s*하|노|0)[^\s,.]*|한\s*번에\s*(?:가|출근)", t)
        if m:
            conds["max_transfers"] = _cond(0, m.group(0))

    # 건물 연식
    m = re.search(r"(\d{1,2})\s*년\s*(?:이내|안|이하|안쪽|미만|안\s*된)", t)
    if m:
        conds["max_building_age_years"] = _cond(int(m.group(1)), m.group(0))
    elif re.search(r"신축|새\s*건물|새\s*집", t):
        conds["max_building_age_years"] = _cond(5, "신축", "inferred", "신축을 준공 5년 이내로 해석")
    elif "깨끗" in t:
        conds["max_building_age_years"] = _cond(10, "깨끗", "inferred", "깨끗한 집을 준공 10년 이내로 해석")
        if "housing_types" not in conds:
            conds["housing_types"] = _cond(["officetel", "villa"], "깨끗", "inferred", "깨끗한 집을 오피스텔·빌라로 해석")

    # 가격 구간
    m = re.search(r"싼|저렴|싸게", t)
    if m:
        conds["price_band"] = _cond("median_or_below", m.group(0), "inferred", "같은 조건 실거래의 가운데~아래 구간")
        priorities.append("price")

    # 출퇴근 편하게
    m = re.search(r"출퇴근\s*편|통근\s*편|교통\s*(?:좋|편)", t)
    if m:
        if "max_commute_min" not in conds:
            conds["max_commute_min"] = _cond(40, m.group(0), "inferred", "출근 시간대 통근 40분 이내")
        if "max_transfers" not in conds:
            conds["max_transfers"] = _cond(1, m.group(0), "inferred", "환승 1회 이하")
        priorities.append("commute")

    # 데이터로 확인할 수 없는 바람
    for key, phrase in _UNVERIFIABLE.items():
        if key in t:
            unverifiable.append({"phrase": phrase, "message": "데이터로 확인할 수 없어요"})

    if conds or _SEARCH_VERB.search(t):
        intent = "search"
    elif _QUESTION.search(t):
        intent = "question"
    else:
        intent = "other"

    card = {"version": "0.1-draft", "utterance": t, "conditions": conds, "priorities": priorities,
            "unverifiable": unverifiable, "clarifications": []}
    plain = intent == "search" and not _NEEDS_LLM.search(t)
    complete = plain and "workplace" in conds and ("deposit_manwon" in conds or "monthly_rent_manwon" in conds)
    covered = plain and _all_read(t, conds, unverifiable)
    return {"intent": intent, "card": card, "complete": complete, "covered": covered}


def _all_read(t, conds, unverifiable):
    """규칙이 말을 다 읽었으면 True(Gemini가 더 알아낼 것 없음)."""
    rest = t
    for c in conds.values():
        if c.get("evidence"):
            rest = rest.replace(c["evidence"], " ")
    for u in unverifiable:
        rest = rest.replace(u["phrase"], " ")
    rest = _FILLER.sub(" ", rest)
    return not re.search(r"[가-힣]{2,}", rest)


def ask_missing(card):
    """검색에 꼭 필요한 회사 위치·예산이 없으면 버튼 되묻기를 넣는다."""
    conds = card.get("conditions", {})
    if "workplace" not in conds:
        card["clarifications"] = [{"id": "workplace", "question": "회사나 학교는 어디예요? 가까운 역 이름도 좋아요.",
                                   "options": ["강남역", "여의도역", "종각역"]}]
    elif "deposit_manwon" not in conds and "monthly_rent_manwon" not in conds:
        card["clarifications"] = [{"id": "budget", "question": "보증금과 월세는 얼마까지 생각하세요?",
                                   "options": ["500/40", "1000/50", "2000/60"]}]
    return card
