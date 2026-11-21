"""방지 장치. 부동산(집 찾기)과 관계없는 내용이 들어오거나 나가지 않게 한다.

앞단(Gemini에 보내기 전)
- 개인정보(전화번호·주민등록번호·이메일)를 가린다.
- 프롬프트 공격("이전 지시 무시해" 등)과 집 찾기와 관계없는 말은 Gemini를 부르지 않고 고정 안내로 답한다.

뒷단(Gemini가 답한 뒤)
- 카드는 계약 문서에 있는 칸·값만 남긴다.
- 카드의 숫자는 사용자가 실제로 한 말과 대조해 고친다.
- 카드의 글(이름·근거)은 사용자가 한 말에 있는 것만 남긴다. Gemini가 쓴 자유 문장은 사용자에게 보여 주지 않는다.
"""

import re

from . import rules

MAX_LEN = 500

# ---- 고정 안내 문구 ----
ASK_MIN = "어느 동네에서 살고 싶으세요? 보증금이랑 월세도 대략 알려 주시면 바로 찾아볼게요. (예: 신촌, 1000/50)"
GUIDE = "저는 서울에서 살 집 찾기를 도와 드려요. " + ASK_MIN
GREETING = "안녕하세요! 살구예요. 서울에서 살 집을 같이 찾아 드릴게요. " + ASK_MIN
THANKS = "천만에요! 더 원하는 조건이 있으면 편하게 말해 주세요."
QUESTION_GUIDE = ("용어나 제도 설명은 아직 도와 드리지 못해요. 원하는 집을 편하게 말해 주시면 바로 찾아 드릴게요. "
                  "예: '신촌 쪽 깨끗한 원룸, 월세 50 이하'")
REFUSE = "그 요청은 도와 드릴 수 없어요."
BLOCKED = REFUSE + " " + GUIDE
TOO_LONG = "말이 너무 길어요. 원하는 집을 짧게 말해 주세요. 예: '회사 강남역, 1000/50 오피스텔'"
EMPTY = "원하는 집을 말해 주세요. 예: '회사 강남역, 1000/50 오피스텔'"

# ---- 앞단 ----
_PHONE = re.compile(r"01[016789][-\s]?\d{3,4}[-\s]?\d{4}")
_RRN = re.compile(r"\d{6}\s*-\s*[1-4]\d{6}")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_INJECTION = re.compile(
    r"(?:이전|위|앞|기존)(?:의)?\s*(?:지시|명령|규칙|프롬프트)|시스템\s*프롬프트|프롬프트\s*(?:알려|보여|출력)|"
    r"(?:지시|규칙|명령)(?:을|를)?\s*무시|너는\s*이제|역할\s*(?:을|를)?\s*(?:바꿔|바꾸)|개발자\s*모드|탈옥|"
    r"ignore\s+(?:all|previous|the\s+above|prior)|system\s*prompt|jailbreak|\bDAN\b|you\s+are\s+now",
    re.I)
_HOUSING = re.compile(
    r"집|방|월세|전세|반전세|보증금|오피스텔|빌라|연립|다세대|원룸|투룸|쓰리룸|자취|이사|매물|부동산|중개|계약|"
    r"확정일자|전입|등기|관리비|역세권|역|동네|통근|출퇴근|출근|회사|직장|학교|평|층|반지하|살\s*곳|살고|구해|찾아|"
    r"전월세|임대|세입자|집주인|입주|신축|구축|ㅂㅈㄱ|ㅇㅅ|ㅈㅅ|ㅇㅍㅅㅌ|ㅂㄹ")
_GREETING = re.compile(r"\s*(?:안녕(?:하세요|하십니까)?|하이|ㅎㅇ|헬로|hello|hi|반가워요?|반갑습니다|처음이에요|저기요?|살구야?)\s*[!.~?ㅎㅋ^]*\s*", re.I)
_THANKS = re.compile(r"\s*(?:고마워요?|감사(?:합니다|해요)?|땡큐|thanks?|thank\s*you|ㄱㅅ|ㄳ)\s*[!.~ㅎㅋ^]*\s*", re.I)
# 이전 카드가 있을 때 고치는 말 (예: "더 싼 데는?", "홍대는 좀?")
_FOLLOW_UP = re.compile(r"더|말고|빼고|대신|별로|좀|싫|좋아|괜찮|바꿔|추가|넓|좁|싼|비싸|가까|멀|상관없|아니|그럼|그거|거기")


def mask_pii(text):
    """LLM에 보내거나 기록하기 전에 개인정보를 가린다."""
    text = _RRN.sub("******-*******", text)
    text = _PHONE.sub("010-****-****", text)
    return _EMAIL.sub("***@***", text)


def check_input(text, has_prev=False):
    """앞단 확인 → (통과 여부, 사유, 안내 문구). 사유: empty, too_long, injection, greeting, thanks, off_topic."""
    t = text.strip()
    if not t:
        return False, "empty", EMPTY
    if len(t) > MAX_LEN:
        return False, "too_long", TOO_LONG
    if _INJECTION.search(t):
        return False, "injection", BLOCKED
    if _GREETING.fullmatch(t):
        return False, "greeting", GREETING
    if _THANKS.fullmatch(t):
        return False, "thanks", THANKS
    card = rules.parse(t)["card"]
    if _HOUSING.search(t) or card["conditions"] or card["unverifiable"]:
        return True, None, None
    if has_prev and (_FOLLOW_UP.search(t) or re.search(r"\d|[십백천억]", t)):
        return True, None, None  # 이전 카드를 고치거나 되물음에 답하는 말("500")일 수 있다
    return False, "off_topic", GUIDE


# ---- 뒷단 ----
ALLOWED = {
    "housing_types", "max_building_age_years", "deposit_manwon", "monthly_rent_manwon", "price_band", "workplace",
    "max_commute_min", "max_transfers", "max_bus_headway_min", "lease_types", "preferred_areas", "avoid_areas",
    "min_area_m2", "min_floor", "max_walk_to_station_min",
}
_INT_KEYS = {"max_building_age_years", "deposit_manwon", "monthly_rent_manwon", "max_commute_min", "max_transfers",
             "max_bus_headway_min", "min_floor", "max_walk_to_station_min"}
_ENUM_LISTS = {"housing_types": {"officetel", "villa"}, "lease_types": {"monthly", "jeonse", "semi_jeonse"}}
_NAME_LISTS = {"preferred_areas", "avoid_areas"}
PRIORITIES = {"price", "commute", "bus_headway", "building_age"}
_PRIORITY_ALIASES = {"monthly_rent": "price", "rent": "price", "deposit": "price", "cost": "price",
                     "commute_time": "commute", "transfer": "commute", "age": "building_age"}
# 사용자가 숫자로 직접 말해야 하는 칸. 말하지 않은 금액은 지운다(지어낸 예산 방지).
_MONEY_KEYS = ("deposit_manwon", "monthly_rent_manwon")
_SAID_NUMBER_KEYS = ("max_commute_min", "max_building_age_years", "max_walk_to_station_min", "max_bus_headway_min")


def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str) and re.fullmatch(r"\d+(?:\.\d+)?", v.strip()):
        return float(v)
    return None


def _from_user(s, sources):
    """글이 사용자가 한 말(또는 이전 카드)에 들어 있으면 True."""
    s = str(s).strip()
    return bool(s) and any(s.replace(" ", "") in src.replace(" ", "") for src in sources)


def normalize_card(card, utterance, prev_card=None):
    """Gemini 카드에서 계약 밖 칸·값을 버린다. dict가 아니면 None."""
    if not isinstance(card, dict):
        return None
    sources = [utterance] + ([_card_text(prev_card)] if prev_card else [])
    conds = {}
    outside = []
    for key, c in (card.get("conditions") or {}).items():
        if key not in ALLOWED or not isinstance(c, dict) or c.get("value") in (None, "", []):
            continue
        c = dict(c)
        v = c["value"]
        if key in _INT_KEYS:
            n = _num(v)
            if n is None or n < 0:
                continue
            c["value"] = int(n)
        elif key == "min_area_m2":
            n = _num(v)
            if n is None or n <= 0:
                continue
            c["value"] = round(float(n), 1)
        elif key in _ENUM_LISTS:
            vals = [x for x in (v if isinstance(v, list) else [v]) if x in _ENUM_LISTS[key]]
            if not vals:
                continue
            c["value"] = list(dict.fromkeys(vals))
        elif key in _NAME_LISTS:
            vals = [str(x).strip() for x in (v if isinstance(v, list) else [v]) if _from_user(x, sources)
                    and str(x).strip() not in ("서울", "서울시", "서울특별시")]  # 서울 전체는 살 곳 조건이 아니다
            for x in [x for x in vals if x in rules._OUTSIDE_SEOUL]:  # 서울 밖은 살 곳이 아니라 '아직 서울만'
                vals.remove(x)
                outside.append(x)
            if not vals:
                continue
            c["value"] = list(dict.fromkeys(vals))
        elif key == "price_band":
            if v != "median_or_below":
                continue
        elif key == "workplace":
            label = c.get("label") or (v if isinstance(v, str) and v != "place" else None)
            if not label or not _from_user(label, sources):
                continue
            c = {**c, "value": "place", "label": str(label).strip()}
            c.pop("place", None)  # 위치 찾기는 계산하는 쪽이 한다
        if c.get("source") not in ("stated", "inferred"):
            c["source"] = "inferred"
        if not _from_user(c.get("evidence", ""), sources):
            c["evidence"] = ""
        c = {k: c[k] for k in ("value", "label", "kind", "source", "evidence", "reason", "approx") if k in c}
        if c["source"] == "inferred" and not isinstance(c.get("reason"), str):
            c.pop("reason", None)
        conds[key] = c
    _reconcile_areas(conds)
    pri = []
    for p in card.get("priorities") or []:
        p = _PRIORITY_ALIASES.get(p, p)
        if p in PRIORITIES and p not in pri:
            pri.append(p)
    unver = [{"phrase": str(u["phrase"]).strip(), "message": "데이터로 확인할 수 없어요"}
             for u in card.get("unverifiable") or []
             if isinstance(u, dict) and _from_user(u.get("phrase", ""), sources)]
    unver = [u for u in unver if u["phrase"] not in outside]
    unver += [{"phrase": x, "message": rules.OUTSIDE_MESSAGE} for x in dict.fromkeys(outside)]
    return {"version": rules.VERSION, "utterance": utterance, "conditions": conds, "priorities": pri,
            "unverifiable": unver, "clarifications": []}


def _card_text(card):
    """이전 카드에 들어 있던 글(이름·근거·말)을 한 덩어리로."""
    parts = [card.get("utterance", "")]
    for c in (card.get("conditions") or {}).values():
        parts += [str(c.get("label", "")), str(c.get("evidence", ""))]
        if isinstance(c.get("value"), list):
            parts += [str(x) for x in c["value"]]
    parts += [u.get("phrase", "") for u in card.get("unverifiable") or []]
    return " ".join(parts)


def _reconcile_areas(conds):
    """같은 곳이 살 곳과 피할 곳에 함께 있으면 피할 곳을 따른다."""
    pref, avoid = conds.get("preferred_areas"), conds.get("avoid_areas")
    if pref and avoid:
        pref["value"] = [a for a in pref["value"] if a not in avoid["value"]]
        if not pref["value"]:
            conds.pop("preferred_areas")


def _said_numbers(utterance, prev_card=None):
    """사용자가 말한 숫자(아라비아·한글 금액)와 이전 카드의 숫자."""
    nums = {float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*(?:\.\d+)?", utterance)}
    for m in re.finditer(rules._MONEY, utterance):
        try:
            nums.add(float(rules.money(m.group(1))))
        except ValueError:
            pass
    for c in ((prev_card or {}).get("conditions") or {}).values():
        if _num(c.get("value")) is not None:
            nums.add(float(c["value"]))
    return nums


def check_card(card, rule_card, utterance, prev_card=None):
    """Gemini 카드를 사용자가 실제로 한 말과 대조해 고친다 → (card, 고친 내용 목록)."""
    if not card:
        return card, []
    fixes = []
    conds = card["conditions"]
    rconds = rule_card.get("conditions", {})
    said = _said_numbers(utterance, prev_card)
    for key in _MONEY_KEYS + _SAID_NUMBER_KEYS + ("max_transfers", "min_floor", "min_area_m2"):
        rc, gc = rconds.get(key), conds.get(key)
        if rc and rc.get("source") == "stated":
            if not gc or gc.get("value") != rc["value"]:
                conds[key] = {**(gc or {}), **rc}
                fixes.append(f"{key}: {gc['value'] if gc else '없음'} → {rc['value']} (사용자가 말한 값)")
        elif gc and gc.get("source") == "stated" and float(gc["value"]) not in said:
            if key in _MONEY_KEYS:
                conds.pop(key)
                fixes.append(f"{key}: 말하지 않은 금액 {gc['value']} 삭제")
            elif key in _SAID_NUMBER_KEYS:
                gc["source"] = "inferred"
                gc.setdefault("reason", "사용자 말에서 해석한 값")
                fixes.append(f"{key}: 숫자를 직접 말하지 않아 추론으로 표시")
    for key in ("housing_types", "lease_types"):
        rc = rconds.get(key)
        if rc and rc.get("source") == "stated" and conds.get(key, {}).get("value") != rc["value"]:
            conds[key] = rc
            fixes.append(f"{key} → {rc['value']} (사용자가 말한 값)")
    if "workplace" not in conds and "workplace" in rconds:
        conds["workplace"] = rconds["workplace"]
        fixes.append(f"workplace: 빠진 회사 위치 '{rconds['workplace']['label']}' 추가")
    _reconcile_areas(conds)
    return card, fixes
