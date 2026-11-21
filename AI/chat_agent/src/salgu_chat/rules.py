"""규칙 파서: 사용자 말에서 예산·위치·유형 등을 LLM 없이 바로 뽑아 조건 카드를 만든다.

원칙
- 확실한 것만 읽는다. 읽은 값은 틀리면 안 된다.
- 못 읽은 말이 조금이라도 남으면 covered=False → Gemini가 이어서 이해한다.
- 사용자에게 처음부터 다 묻지 않는다. 가장 자연스러운 뜻으로 카드를 만들고, 사용자는 다음 말로 고친다.

두 군데서 쓴다.
1. 빠른 길: 규칙이 말을 다 읽으면(covered) Gemini를 부르지 않고 바로 카드를 만든다.
2. 방지 장치 기준값: Gemini 카드의 숫자가 사용자가 실제로 말한 숫자와 같은지 대조한다.
"""

import re

from .districts import DISTRICT_NAME

VERSION = "0.2-draft"

# ---- 숫자·금액 (만 원 단위). 아라비아 숫자와 한글 숫자(천, 오십 등)를 모두 읽는다 ----
_D = r"\d[\d,]*(?:\.\d+)?"
_K = r"[일이삼사오육칠팔구]"
_KEND = rf"(?:(?!이[가-힣]){_K})?"  # 끝자리 숫자. "천이고"의 '이'는 조사이므로 숫자로 읽지 않는다
_UNDER = (rf"(?:(?:{_D}|{_K})?천(?:(?:{_D}|{_K})?백)?(?:{_K}?십)?{_KEND}"
          rf"|(?:{_D}|{_K})?백(?:{_K}?십)?{_KEND}"
          rf"|{_K}?십{_KEND}"
          rf"|{_D})")
_MONEY = rf"((?:{_D}|{_K})\s*억(?:\s*{_UNDER})?(?:\s*만)?(?:\s*원)?|{_UNDER}(?:\s*만)?(?:\s*원)?)"
_RENT = rf"({_K}?십{_KEND}|{_K}?백|\d{{1,3}})(?!\d)"
_NOT_MONEY_UNIT = r"(?!\s*(?:분|평|층|년|번|개|살|세|%|㎡|m|억|천))"
_KD = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9}
_UNIT = {"천": 1000, "백": 100, "십": 10}

# ---- 위치 ----
_LABEL = r"[가-힣A-Za-z0-9]+"
_WORD = r"[가-힣A-Za-z][가-힣A-Za-z0-9]*"
_TOKEN = r"(?<![가-힣A-Za-z0-9])([가-힣A-Za-z0-9]+?)"
_STOP_LABELS = {"지역", "구역", "역", "우리", "내", "제", "저희", "다니는", "다녀", "근처", "회사", "직장", "학교", "사무실",
                "저는", "나는", "난", "지하철역", "전철역", "기차역", "가까운역", "서울", "다른데", "다른"}
_VERBISH = re.compile(r"다니|다녀|는데|어요|아요|해요|니다|에서$|으로$")
_WORK_HINT = re.compile(r"회사|직장|학교|사무실|다니|다녀|근무|출근|출퇴근|통근")
_NEAR = r"(?:근처|쪽|부근|인근|주변|일대|라인|권)"
_LIVE = r"(?:살고\s*싶|살\s*거|살래|살았으면|자취|원룸|투룸|쓰리룸|오피스텔|빌라|방\s*구|집\s*구|집\s*찾|방\s*찾|매물|집\s*좀|방\s*좀)"
_AVOID = (r"(?:말고|빼고|빼줘|제외|싫|별로|피해|피하고|안\s*돼|노노"
          r"|좀\s*(?:\?|별로|그래|그렇|아닌|아니|$|[.,!~ㅠㅜ]))")
_KNOWN_AREAS = {name[:-1] for name in DISTRICT_NAME.values() if len(name) > 2} | {
    "홍대", "신촌", "이대", "합정", "망원", "연남", "상수", "신림", "봉천", "건대", "성수", "왕십리", "잠실", "여의도",
    "이태원", "한남", "회기", "혜화", "대학로", "종각", "을지로", "충무로", "명동", "사당", "노량진", "목동", "신도림",
    "문래", "당산", "선릉", "역삼", "삼성", "논현", "신사", "압구정", "청담", "방배", "교대", "안암", "대치",
    "광화문", "시청", "마곡", "상암", "가산", "구디", "서울역", "수유", "미아", "창동", "길음", "성신여대", "외대",
}
# 서울 밖 지명: 살 곳으로는 받지 않고 '아직 서울만'이라고 알린다 (회사 위치로는 괜찮음)
_OUTSIDE_SEOUL = {"판교", "분당", "일산", "부산", "해운대", "인천", "송도", "수원", "광교", "용인", "성남", "고양", "부천",
                  "광명", "하남", "안양", "평촌", "의정부", "김포", "대전", "대구", "광주", "울산", "제주", "세종", "천안",
                  "파주", "남양주", "구리", "과천", "동탄", "경기", "경기도"}
OUTSIDE_MESSAGE = "서울 밖은 아직 찾아 드리지 못해요(서울만)"
# 흔한 오타·줄임말 → 바른 말 (말을 읽기 전에 바꾼다)
_TYPOS = [(r"오피스탤|오피스땔|오피스텔ㄹ|옵텔|오피(?=\s|$)", "오피스텔"), (r"보증굼|보증검|보즘금|보증금금|보증ㄱ", "보증금"),
          (r"월쎄|월새|윌세|월셰", "월세"), (r"전쎄|젼세", "전세"), (r"빌러|빌나", "빌라"), (r"원룸ㅁ|원룸룸", "원룸")]

# 어떤 말이 있으면 규칙만으로 확정하지 않고 Gemini에 맡긴다 (부정·대체·살 곳 지정·물음 등)
# 물음표는 여기 넣지 않는다: "홍대는 좀?"처럼 규칙이 다 읽은 물음은 바로 답하고, 못 읽은 말이 남으면 어차피 Gemini로 간다
_NEEDS_LLM = re.compile(r"말고|아니|대신|빼고|제외|살고\s*싶|근처에\s*살|쪽에\s*살|동네(?:에서|로)|상관없")
_QUESTION = re.compile(r"뭐(?:예요|에요|야|지|임)|머임|뭔데|뭔가요|무엇|이란|란\s*$|어떻게|어케|왜|차이|설명|가능해|되나요|돼요\?|적당")
_SEARCH_VERB = re.compile(r"찾아|찾고|찾는|구해|구하|구함|알아봐|알아보|추천|보여|살\s*집|집\s*좀|매물|자취|이사|원룸|투룸|쓰리룸|오피스텔|빌라|집\s*있|방\s*있")
_UNVERIFIABLE = {"조용": "조용한", "채광": "채광", "햇빛": "햇빛", "밝은": "밝은", "뷰": "뷰", "치안": "치안",
                 "분위기": "분위기", "강아지": "반려동물", "고양이": "반려동물", "반려": "반려동물", "주차": "주차",
                 "엘리베이터": "엘리베이터", "엘베": "엘리베이터", "풀옵션": "풀옵션", "옵션": "옵션"}
_FILLER = re.compile(r"찾아\s*줘?|구해\s*줘?|알아봐\s*줘?|추천해?\s*줘?|보여\s*줘?|해\s*줘|원해요?|싶어요?|정도로?|이하|이내|"
                     r"까지|안쪽|으로|이고|인데|는데|하고|그리고|있는|살\s*곳|살\s*집|집|방|매물|원룸|좀|주세요|해요|"
                     r"회사|직장|학교|사무실|다녀요|다니는|근무|저는|나는|요")
# 남아도 뜻이 없는 낱말(조사·어미·맞장구)
_OK_TOKEN = re.compile(r"(?:은|는|이|가|을|를|에|에서|도|로|으로|와|과|랑|이랑|고|의|만|면|이면|서|게|한|인|곳|데|거|것|"
                       r"원하는|괜찮은|좋은|되는|되고|되면|가능한|가능|좋겠어|좋겠다|좋겠|좋아|괜찮아|이었으면|였으면|했으면|쯤|짜리|낼|수|"
                       r"있어|이상|더|어때요|어때|어요|어|아요|아|예요|예|에요|이에요|야|임|구함|구합니다|합니다|부탁|자취방|자취|ㅎ+|ㅋ+|ㅠ+|ㅜ+|ㄱㄱ|ㄱ)+")


def _small(s):
    """억 아래 금액 글 → 숫자. 예: "2천5백"→2500, "오십"→50."""
    total, cur = 0.0, ""
    for ch in s:
        if ch.isdigit() or ch == ".":
            cur += ch
        elif ch in _KD:
            cur = str(_KD[ch])
        elif ch in _UNIT:
            total += float(cur or 1) * _UNIT[ch]
            cur = ""
        else:
            raise ValueError(s)
    return total + float(cur or 0)


def money(s):
    """금액 글 → 만 원 정수. 예: "1억 5천"→15000, "2천"→2000, "1,000"→1000, "천"→1000, "500만원"→500."""
    s = re.sub(r"[\s,]|원|만", "", s)
    if "억" in s:
        front, back = s.split("억", 1)
        return int(round(_small(front or "1") * 10000 + _small(back)))
    return int(round(_small(s))) if s else 0


def _cond(value, evidence, source="stated", reason=None, **extra):
    """조건 항목 하나."""
    c = {"value": value, "source": source, "evidence": evidence.strip(), **extra}
    if reason:
        c["reason"] = reason
    return c


def _clean_label(label):
    return re.sub(r"(이고|인데|이에요|예요|이라서|이라|라서|이니까|니까|이야|야|임|고)$", "", label)


def _is_area(label):
    """살 곳·피할 곳으로 쓸 수 있는 이름인지 (구·동·역 이름이나 잘 알려진 동네)."""
    if not label or label in _STOP_LABELS or len(label) < 2 or label in _OUTSIDE_SEOUL:
        return False
    return label in _KNOWN_AREAS or (label[-1] in "역동구" and not _VERBISH.search(label)) or bool(re.search(r"\d가$", label))


def _workplace(t):
    """회사·학교 위치 → (label, 근거 구절). 없으면 (None, None)."""
    patterns = [
        rf"(?:회사|직장|학교|사무실)(?:가|는|이|은)?\s*({_WORD})",
        rf"({_WORD})\s*(?:에\s*있는\s*)?(?:회사|직장|학교|사무실)",
        rf"({_WORD}(?:\s+{_WORD})?)\s*(?:에|에서|로)?\s*(?:다녀|다니|근무|출근하)",
    ]
    if _WORK_HINT.search(t):
        # 역 이름은 회사라는 말이 있을 때만 회사 위치로 본다. "○○역 근처 원룸"처럼 살 곳이면 건너뛴다.
        patterns.insert(0, rf"({_LABEL}역)(?!세권)(?!\s*{_NEAR}\s*(?:에\s*)?{_LIVE})(?!\s*(?:에서|에)?\s*{_LIVE})")
    for pat in patterns:
        for m in re.finditer(pat, t):
            label = _clean_label(m.group(1))
            if re.match(r"근처|쪽|부근|주변|인근|가까|어디|다니|다녀|이랑|에서|으로|로$", label):
                continue  # "직장 근처로", "학교 어디" 같은 말은 이름이 아니다
            if len(label) >= 2 and label not in _STOP_LABELS and not _VERBISH.search(label):
                return label, m.group(0)
    return None, None


def _near_work_word(t, start, end):
    """이름 바로 앞뒤에 회사라는 말이 있으면 살 곳이 아니라 회사 위치를 설명하는 것."""
    return bool(_WORK_HINT.search(t[max(0, start - 5):start]) or _WORK_HINT.search(t[end:end + 6]))


def _listed_before(t, start):
    """"망원이나 합정 쪽"처럼 앞에 나열된 이름들 → [(label, 구절)]."""
    out = []
    while True:
        m = re.search(r"(?<![가-힣A-Za-z0-9])([가-힣A-Za-z0-9]+?)(?:\s*(?:이나|나|이랑|랑|하고|와|과|,|/|or)\s*|\s+)$", t[:start])
        if not m or not _is_area(m.group(1)):
            return out
        out.append((m.group(1), t[m.start():start]))
        start = m.start()


def _areas(t, work_label):
    """(살 곳 [(label, 근거)], 피할 곳 [(label, 근거)], 추론한 살 곳 [(label, 근거)])."""
    avoid, prefer, used = [], [], set()
    for m in re.finditer(rf"{_TOKEN}\s*(?:은|는|이랑|랑|쪽은|쪽|근처는|근처)?\s*{_AVOID}", t):
        label = m.group(1)
        if _is_area(label) and label not in used:
            for prev, phrase in reversed(_listed_before(t, m.start(1))):
                if prev not in used:
                    avoid.append((prev, phrase))
                    used.add(prev)
            avoid.append((label, m.group(0)))
            used.add(label)
    for pat in (rf"{_TOKEN}\s*{_NEAR}(?:\s*(?:에서|에|으로|로))?(?:\s*{_LIVE})?",
                rf"{_TOKEN}\s*(?:에서|에)?\s*{_LIVE}"):
        for m in re.finditer(pat, t):
            label = m.group(1)
            if (_is_area(label) and label not in used and label != work_label
                    and not _near_work_word(t, m.start(1), m.end())):
                for prev, phrase in reversed(_listed_before(t, m.start(1))):
                    if prev not in used and prev != work_label:
                        prefer.append((prev, phrase))
                        used.add(prev)
                prefer.append((label, m.group(0)))
                used.add(label)
    # 회사라는 말이 전혀 없을 때 그냥 말한 동네·역 이름은 살고 싶은 곳으로 본다 (되묻지 않음)
    guessed = []
    if not _WORK_HINT.search(t):
        for m in re.finditer(r"[가-힣A-Za-z0-9]+", t):
            label = re.sub(r"(?:에서|에|은|는|이|가|쪽|이랑|랑|으로|로)$", "", m.group(0))
            if _is_area(label) and label not in used:
                guessed.append((label, label))
                used.add(label)
    return prefer, avoid, guessed


def normalize(text):
    """흔한 오타·줄임말을 바른 말로 바꾼다 (예: 오피스탤 → 오피스텔, 보증굼 → 보증금)."""
    t = (text or "").strip()
    for pat, good in _TYPOS:
        t = re.sub(pat, good, t)
    return t


# 대화를 이끄는 짧은 말 (조건이 아니라 대화 동작)
_CONTROL = [
    ("reset", re.compile(r"(?:아니\s*)?(?:그냥\s*)?(?:처음부터(?:\s*다시)?|다시\s*처음부터|다시\s*시작|새로\s*시작|리셋|초기화|"
                         r"(?:전부|다)\s*지워)(?:\s*(?:할래|하자|해\s*줘|해줘|해요|할게요?))?[\s!.~ㅠㅜ]*")),
    ("stop", re.compile(r"(?:취소|그만|그만할래|됐어|됐어요|됐다|안\s*할래|안\s*해|나중에|다음에)(?:\s*(?:할게요?|해요|안\s*해|할래))?[\s!.~ㅠㅜ]*")),
    ("ack", re.compile(r"(?:ㅇㅇ|ㅇㅋ|응+|웅|네+|넹|넵|예|오케이|ok|okay|좋아요?|좋네요?|괜찮아요?|그래요?|맞아요?|알겠어요?|굿|굳)"
                       r"[\s!.~ㅎㅋ^]*", re.I)),
    ("more", re.compile(r".{0,6}(?:다른\s*(?:거|것|곳|데|집|매물)|더\s*(?:보여|있어|없어|찾아|추천)|또\s*(?:있어|없어|보여)|"
                        r"다음\s*(?:거|꺼|곳)).{0,10}")),
    ("pick", re.compile(r".{0,4}?(\d|첫|두|세|네|다섯)\s*(?:번째|번|째)\s*(?:거|꺼|곳|집|매물)?.{0,12}")),
]
_ORDINAL = {"첫": 1, "두": 2, "세": 3, "네": 4, "다섯": 5}


def control(text):
    """'처음부터 다시', '취소', 'ㅇㅇ', '다른 거 더 보여줘', '2번째꺼 자세히' → (종류, 번호) 또는 (None, None)."""
    t = normalize(text)
    if len(t) > 30:
        return None, None
    for kind, pat in _CONTROL:
        m = pat.fullmatch(t)
        if m:
            if kind == "pick":
                g = m.group(1)
                return kind, int(g) if g.isdigit() else _ORDINAL[g]
            return kind, None
    return None, None


def parse(text):
    """사용자 말 → {"intent", "card", "covered", "asked"}. asked: 집 찾기 말 속에 질문이 섞여 있음."""
    t = normalize(text)
    conds, priorities, unverifiable, used = {}, [], [], []
    conflict = False

    approx = {"approx": True} if re.search(r"정도|쯤|안팎|내외|언저리", t) else {}

    # ---- 보증금·월세 ----
    m = (re.search(rf"{_MONEY}\s*/\s*{_RENT}", t)
         or re.search(rf"{_MONEY}\s*에\s*(?:월세\s*)?{_RENT}(?:\s*만\s*원?)?{_NOT_MONEY_UNIT}", t))
    if m and money(m.group(1)) >= money(m.group(2)):
        conds["deposit_manwon"] = _cond(money(m.group(1)), m.group(0), **approx)
        conds["monthly_rent_manwon"] = _cond(money(m.group(2)), m.group(0), **approx)
    m = re.search(rf"보증금\s*(?:은|는|이|가|이고)??\s*{_MONEY}", t)
    if m:
        conds["deposit_manwon"] = _cond(money(m.group(1)), m.group(0))
    m = re.search(rf"(?<!반)전세(?:금|보증금)?\s*(?:은|는|이|가|로)??\s*{_MONEY}", t)
    if m:
        conds["deposit_manwon"] = _cond(money(m.group(1)), m.group(0))
    m = re.search(rf"(?<![\d일이삼사오육칠팔구십])월(?:세)?\s*(?:는|은|가|이)??\s*{_RENT}(?:\s*만\s*원?)?{_NOT_MONEY_UNIT}", t)
    if m:
        conds["monthly_rent_manwon"] = _cond(money(m.group(1)), m.group(0))
    # "월세 좀만 더 올려도 돼 60까지"처럼 사이에 말이 끼어 있어도 끝에 '까지·이하·정도' 등이 붙으면 읽는다
    _until = r"\s*(?:만\s*원?)?\s*(?:까지|이하|정도|쯤|로|면|선|안쪽|가능)"
    if "monthly_rent_manwon" not in conds:
        m = re.search(rf"(?<![\d일이삼사오육칠팔구십])월세(?:(?!보증|전세)[^\d/\n]){{1,14}}?{_RENT}{_until}", t)
        if m:
            conds["monthly_rent_manwon"] = _cond(money(m.group(1)), m.group(0))
    if "deposit_manwon" not in conds:
        m = re.search(rf"보증금(?:(?!월세|월\s)[^\d/\n]){{1,14}}?{_MONEY}{_until}", t)
        if m:
            conds["deposit_manwon"] = _cond(money(m.group(1)), m.group(0))
    # "원룸 50만원 이하"처럼 '월세'라는 말 없이 작은 금액만 말하면 월세로 해석 (추론 표시)
    if "monthly_rent_manwon" not in conds and "deposit_manwon" not in conds and not re.search(r"전세|보증", t):
        m = re.search(r"(?<![\d/])(\d{1,3})\s*만\s*원?\s*(?:이하|까지|안쪽|정도|쯤|선)", t)
        if m and int(m.group(1)) <= 150:
            conds["monthly_rent_manwon"] = _cond(int(m.group(1)), m.group(0), "inferred", "금액이 작아 월세로 해석")
    # 말하다가 고친 값: "월세 50 아니 60", "보증금 500 아니다 1000으로" → 뒤의 값
    _fix = r"\s*(?:아니|아니다|아니고|아니야|아냐|말고)[,.\s]*"
    m = re.search(rf"월(?:세)?\s*(?:는|은)?\s*{_RENT}(?:\s*만\s*원?)?{_fix}(?:월세\s*)?{_RENT}(?:\s*만\s*원?)?", t)
    if m:
        conds["monthly_rent_manwon"] = _cond(money(m.group(2)), m.group(0))
    m = re.search(rf"보증금\s*(?:은|는)?\s*{_MONEY}{_fix}(?:보증금\s*)?{_MONEY}", t)
    if m:
        conds["deposit_manwon"] = _cond(money(m.group(2)), m.group(0))

    # ---- 월세·전세·반전세 ----
    leases = re.findall(r"반전세|(?<!반)전세(?!\s*(?:대출|사기|보험|자금|계약|권|금\s*반환))|월세", t)
    lease_types = [k for k, word in (("monthly", "월세"), ("jeonse", "전세"), ("semi_jeonse", "반전세")) if word in leases]
    if lease_types == ["jeonse"] and "monthly_rent_manwon" in conds:
        conflict = True  # "1000/50인데 전세로": 전세와 월세가 부딪힘 → Gemini가 판단, 규칙은 숫자만 둔다
        lease_types = []
    if lease_types:
        conds["lease_types"] = _cond(lease_types, " ".join(dict.fromkeys(leases)))

    # ---- 주택 유형 ----
    types = []
    if "오피스텔" in t:
        types.append("officetel")
    if re.search(r"빌라|연립|다세대", t):
        types.append("villa")
    if types:
        conds["housing_types"] = _cond(types, " ".join(re.findall(r"오피스텔|빌라|연립|다세대", t)))
    if "아파트" in t:
        unverifiable.append({"phrase": "아파트", "message": "아파트는 아직 지원하지 않아요(오피스텔·빌라만)"})
        used.append("아파트")

    # ---- 회사 위치, 살 곳, 피할 곳 ----
    label, evidence = _workplace(t)
    if label:
        kind = "school" if re.search(r"학교|캠퍼스|다니는\s*학교|대학", evidence) or re.search(r"대$|대학교$", label) else "work"
        conds["workplace"] = _cond("place", evidence, label=label, kind=kind)
    prefer, avoid, guessed = _areas(t, label)
    if prefer:
        conds["preferred_areas"] = _cond([a for a, _ in prefer], " ".join(e for _, e in prefer))
    elif guessed:
        conds["preferred_areas"] = _cond([a for a, _ in guessed], " ".join(e for _, e in guessed), "inferred",
                                         "회사라는 말이 없어 살고 싶은 곳으로 해석")
    if avoid:
        conds["avoid_areas"] = _cond([a for a, _ in avoid], " ".join(e for _, e in avoid))
    used.extend(e for _, e in prefer + avoid + guessed)  # 나열된 이름은 구절이 따로 떨어져 있다
    for m in re.finditer(r"[가-힣]+", t):  # 서울 밖 지명 (회사 위치가 아니면)
        name = re.sub(r"(?:에서|에|은|는|이|가|쪽|이랑|랑|으로|로|근처)$", "", m.group(0))
        if name in _OUTSIDE_SEOUL and name != label and all(u["phrase"] != name for u in unverifiable):
            unverifiable.append({"phrase": name, "message": OUTSIDE_MESSAGE})
            used.append(m.group(0))

    # ---- 통근 ----
    m = (re.search(r"(?:통근|출퇴근|출근|회사까지)[^\d]{0,12}(\d{1,3})\s*분", t)
         or re.search(r"(\d{1,3})\s*분\s*(?:안에|이내|안쪽|까지)?\s*(?:통근|출퇴근|출근)", t))
    if m:
        conds["max_commute_min"] = _cond(int(m.group(1)), m.group(0))
    m = re.search(r"환승\s*(\d)\s*(?:번|회)", t)
    if m:
        conds["max_transfers"] = _cond(int(m.group(1)), m.group(0))
    else:
        m = re.search(r"환승\s*(?:은|는|이)?\s*(?:없이|없는|없었|싫|안\s*하|노|0)[^\s,.]*|한\s*번에\s*(?:가|출근)", t)
        if m:
            conds["max_transfers"] = _cond(0, m.group(0))

    # ---- 역까지 걸어서 ----
    m = (re.search(r"(?<![가-힣A-Za-z0-9])(?:지하철|전철|가까운\s*)?역(?:까지|에서|이랑|과|와|은|이)?\s*"
                   r"(?:걸어서|도보로?|걸어)?\s*(\d{1,2})\s*분", t)
         or re.search(r"(?:걸어서|도보로?)\s*(\d{1,2})\s*분\s*(?:거리\s*)?(?:안에|이내|안쪽)?\s*(?:역|지하철|전철)", t))
    if m:
        conds["max_walk_to_station_min"] = _cond(int(m.group(1)), m.group(0))
    elif "초역세권" in t:
        conds["max_walk_to_station_min"] = _cond(5, "초역세권", "inferred", "초역세권을 역까지 걸어서 5분 이내로 해석")
    elif "역세권" in t:
        conds["max_walk_to_station_min"] = _cond(10, "역세권", "inferred", "역세권을 역까지 걸어서 10분 이내로 해석")

    # ---- 면적·방 ----
    m = (re.search(r"(\d{1,3}(?:\.\d+)?)\s*평(?!\s*(?:이하|미만|까지|아래|이내|보다\s*작|안))"
                   r"\s*(이상|넘는|넘게|넘|부터|보다\s*넓은?|정도|쯤|대)?", t))
    if m:
        extra = {"approx": True} if m.group(2) in ("정도", "쯤", "대") else {}
        conds["min_area_m2"] = _cond(round(float(m.group(1)) * 3.3058, 1), m.group(0), **extra)
    else:
        m = re.search(r"(\d{1,3}(?:\.\d+)?)\s*(?:㎡|m2|m²|제곱미터|평방미터)"
                      r"(?!\s*(?:이하|미만|까지|아래|이내|보다\s*작|안))\s*(?:이상|넘는|넘게|넘|부터)?", t)
        if m:
            v = float(m.group(1))
            conds["min_area_m2"] = _cond(int(v) if v.is_integer() else v, m.group(0))
    if "min_area_m2" not in conds:
        m = re.search(r"쓰리룸|방\s*(?:3|세)\s*개", t)
        if m:
            conds["min_area_m2"] = _cond(50, m.group(0), "inferred", "쓰리룸을 전용 50㎡ 이상으로 해석")
        else:
            m = re.search(r"투룸|방\s*(?:2|두)\s*개", t)
            if m:
                conds["min_area_m2"] = _cond(33, m.group(0), "inferred", "투룸을 전용 33㎡(약 10평) 이상으로 해석")

    # ---- 층 ----
    floors = []
    for pat, value in ((r"반\s*지하\s*(?:는|은)?\s*(?:싫|안|제외|빼|말고|노|별로|피|아닌|x|X)", 1),
                       (r"(?<!\d)(?:1|일)\s*층\s*(?:은|는)?\s*(?:싫|안|제외|빼|말고|별로|피|아닌)"
                        r"|저층\s*(?:은|는)?\s*(?:싫|별로|피|빼|말고)", 2)):
        m = re.search(pat, t)
        if m:
            floors.append((value, m.group(0)))
    m = re.search(r"(\d{1,2})\s*층\s*(?:이상|부터|넘는|넘게|위로?)", t)
    if m:
        floors.append((int(m.group(1)), m.group(0)))
    if floors:
        value, evidence = max(floors)
        conds["min_floor"] = _cond(value, evidence)
        used.extend(e for _, e in floors)

    # ---- 연식 ----
    m = re.search(r"(\d{1,2})\s*년\s*(?:이내|안|이하|안쪽|미만|안\s*된)", t)
    clean = re.search(r"깨끗|깔끔", t)
    if m:
        conds["max_building_age_years"] = _cond(int(m.group(1)), m.group(0))
    elif re.search(r"신축|새\s*건물|새\s*집", t):
        word = re.search(r"신축|새\s*건물|새\s*집", t).group(0)
        conds["max_building_age_years"] = _cond(5, word, "inferred", "신축을 준공 5년 이내로 해석")
    elif clean:
        conds["max_building_age_years"] = _cond(10, clean.group(0), "inferred", "깨끗한 집을 준공 10년 이내로 해석")
        if "housing_types" not in conds:
            conds["housing_types"] = _cond(["officetel", "villa"], clean.group(0), "inferred",
                                           "깨끗한 집을 오피스텔·빌라로 해석")

    # ---- 가격 구간 ----
    m = re.search(r"싼|싸게|싸면|싸고|저렴|가성비", t)
    if m:
        conds["price_band"] = _cond("median_or_below", m.group(0), "inferred", "같은 조건 실거래의 가운데~아래 구간")
        priorities.append("price")

    # ---- 출퇴근 편하게 ----
    m = re.search(r"출퇴근\s*편|통근\s*편|교통\s*(?:좋|편)", t)
    if m:
        if "max_commute_min" not in conds:
            conds["max_commute_min"] = _cond(40, m.group(0), "inferred", "출근 시간대 통근 40분 이내")
        if "max_transfers" not in conds:
            conds["max_transfers"] = _cond(1, m.group(0), "inferred", "환승 1회 이하")
        priorities.append("commute")

    # ---- 데이터로 확인할 수 없는 바람 ----
    hits = []
    for key, phrase in _UNVERIFIABLE.items():
        if key in t and not any(key in h for h in hits):
            hits.append(key)
            if all(u["phrase"] != phrase for u in unverifiable):
                unverifiable.append({"phrase": phrase, "message": "데이터로 확인할 수 없어요"})
    used.extend(hits)

    asked = bool(_QUESTION.search(t))
    if asked and set(conds) <= {"lease_types", "housing_types", "price_band"} and not unverifiable:
        intent = "question"  # "반전세가 뭐예요", "오피스텔이랑 빌라 차이가 뭐야": 낱말만 나온 질문
    elif conds or unverifiable or _SEARCH_VERB.search(t):
        intent = "search"
    elif asked:
        intent = "question"
    else:
        intent = "other"

    card = {"version": VERSION, "utterance": t, "conditions": conds, "priorities": priorities,
            "unverifiable": unverifiable, "clarifications": []}
    # "학교 근처 원룸"처럼 학교·회사를 말했는데 이름이 없으면, 어디인지 물을 수 있게 표시한다
    if "workplace" not in conds:
        m = re.search(r"학교|캠퍼스|학원|회사|직장|사무실|일터", t)
        if m:
            card["workplace_hint"] = "학교" if m.group(0) in ("학교", "캠퍼스") else (
                "학원" if m.group(0) == "학원" else "회사")
    used.extend(c["evidence"] for c in conds.values() if c.get("evidence"))
    covered = intent == "search" and not conflict and not _NEEDS_LLM.search(t) and _all_read(t, used)
    return {"intent": intent, "card": card, "covered": covered, "asked": asked and intent == "search"}


def _all_read(t, used):
    """규칙이 말을 다 읽었으면 True(Gemini가 더 알아낼 것 없음). 숫자·낱말이 하나라도 남으면 False."""
    rest = t
    for piece in sorted(set(used), key=len, reverse=True):
        rest = rest.replace(piece, " ")
    rest = _FILLER.sub(" ", rest)
    tokens = re.findall(r"[가-힣ㄱ-ㅎㅏ-ㅣA-Za-z0-9]+", rest)
    return all(_OK_TOKEN.fullmatch(tok) for tok in tokens)
