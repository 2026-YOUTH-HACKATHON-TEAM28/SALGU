"""조건 추론: 사용자 말 → 조건 카드 + 답 문장.

흐름
1. 앞단 방지 장치: 개인정보 가리기, 공격·관계없는 말은 Gemini 없이 고정 안내.
2. 규칙 파서가 말을 다 읽으면 바로 카드(빠른 길, Gemini 안 부름).
3. 아니면 Gemini 1회. 늦거나 한도에 걸리면 기다리지 않고 규칙 결과로 답한다.
4. 뒷단 방지 장치: 계약 밖 값 제거, 숫자 대조.
5. 이전 카드가 있으면 새 말로 고친 전체 카드를 만든다 ("홍대는 좀?" → 홍대 제외).
"""

import copy
import json
import re
import time
from pathlib import Path

from . import config, guards, llm, rules

_PROMPT = (Path(__file__).parent / "prompts" / "intake.md").read_text(encoding="utf-8")
_CONTRACT = (config.ROOT / "contracts" / "condition_card.md").read_text(encoding="utf-8")
SYSTEM = _PROMPT + "\n\n=== 조건 카드 계약 문서 ===\n" + _CONTRACT


def merge(prev_card, new_card):
    """이전 카드에 새 말의 조건을 덮어쓴다. 살 곳·피할 곳은 서로 정리한다."""
    if not prev_card:
        return new_card
    card = copy.deepcopy(prev_card)
    conds = card["conditions"]
    new = dict(new_card["conditions"])

    # 살 곳·피할 곳: 이전 것에 새 것을 더하되, 새로 피하라고 한 곳은 살 곳에서 빼고 그 반대도 같다
    def vals(d, key):
        return (d.get(key) or {}).get("value") or []
    new_pref, new_avoid = vals(new, "preferred_areas"), vals(new, "avoid_areas")
    areas = {
        "preferred_areas": [a for a in dict.fromkeys(vals(conds, "preferred_areas") + new_pref) if a not in new_avoid],
        "avoid_areas": [a for a in dict.fromkeys(vals(conds, "avoid_areas") + new_avoid) if a not in new_pref],
    }
    # "아니 강남역은 회사고 …": 회사 위치가 된 곳은 살 곳에서 뺀다
    work = (new.get("workplace") or {}).get("label")
    if work:
        areas["preferred_areas"] = [a for a in areas["preferred_areas"] if a != work]
    for key, value in areas.items():
        base = new.pop(key, None) or conds.get(key)
        if value:
            conds[key] = {**base, "value": value}
        else:
            conds.pop(key, None)
    new_leases = (new.get("lease_types") or {}).get("value") or []
    if new_leases == ["jeonse"] and "monthly_rent_manwon" not in new:
        conds.pop("monthly_rent_manwon", None)  # 전세로 바꾸면 이전 월세 조건은 뺀다
    conds.update(new)
    card["utterance"] = new_card["utterance"]
    card["priorities"] = list(dict.fromkeys(card.get("priorities", []) + new_card.get("priorities", [])))
    seen = {u["phrase"] for u in card.get("unverifiable", [])}
    card["unverifiable"] = card.get("unverifiable", []) + [u for u in new_card.get("unverifiable", [])
                                                         if u["phrase"] not in seen]
    card["clarifications"] = []
    if new_card.get("workplace_hint"):
        card["workplace_hint"] = new_card["workplace_hint"]
    if "workplace" in conds:
        card.pop("workplace_hint", None)
    return card


def _changed(prev_card, card):
    """이번 말로 바뀐 칸 목록."""
    before = (prev_card or {}).get("conditions", {})
    after = (card or {}).get("conditions", {})
    return sorted(k for k in set(before) | set(after)
                  if (before.get(k) or {}).get("value") != (after.get(k) or {}).get("value"))


def _won(manwon):
    """만 원 → 읽기 쉬운 글. 15000 → '1억 5천만', 1000 → '1000만'."""
    if manwon >= 10000:
        eok, rest = divmod(manwon, 10000)
        if not rest:
            return f"{eok}억"
        return f"{eok}억 " + (f"{rest // 1000}천만" if rest % 1000 == 0 else f"{rest}만")
    return f"{manwon}만"


def _josa(word, pair):
    """받침에 맞는 조사. pair: '은는', '이가', '으로로'."""
    last = word[-1] if word else ""
    if not ("가" <= last <= "힣"):
        return word + ("로" if pair == "으로로" else pair[1])
    jong = (ord(last) - 0xAC00) % 28
    if pair == "으로로":
        return word + ("로" if jong in (0, 8) else "으로")  # 받침 없음·ㄹ받침 → 로
    return word + (pair[0] if jong else pair[1])


# ---- 최소 조건: 지역(살 곳 또는 회사·학교) + 보증금 + 월세(전세면 월세 없음) ----
_CLARIFY = {
    "area": {"id": "area", "question": "어느 동네에서 살고 싶으세요?", "options": ["신촌", "강남역 근처", "잠실", "성수"]},
    "budget": {"id": "budget", "question": "보증금·월세는 어느 정도요?", "options": ["500/40", "1000/50", "2000/60", "전세 1억"]},
    "deposit": {"id": "deposit", "question": "보증금은 어느 정도요?", "options": ["보증금 500", "보증금 1000", "보증금 2000"]},
    "monthly_rent": {"id": "monthly_rent", "question": "월세는 얼마까지요?", "options": ["월세 40", "월세 50", "월세 60"]},
    "lease": {"id": "lease", "question": "전세로 찾을까요, 월세로 찾을까요?", "options": ["전세로", "월세로"]},
}


def missing_minimum(card):
    """검색에 꼭 필요한데 아직 모르는 것: area, deposit, monthly_rent."""
    c = card["conditions"]
    miss = []
    if "preferred_areas" not in c and "workplace" not in c:
        miss.append("area")
    if "deposit_manwon" not in c:
        miss.append("deposit")
    leases = (c.get("lease_types") or {}).get("value")
    if "monthly_rent_manwon" not in c and leases != ["jeonse"]:
        miss.append("monthly_rent")
    if leases == ["jeonse"] and "monthly_rent_manwon" in c:
        miss.insert(0, "lease")  # "1000/50인데 전세로": 전세와 월세가 부딪힘 → 어느 쪽인지 묻는다
    return miss


_WORK_OPTIONS = {"학교": ["고려대", "연세대", "홍익대", "서울대"], "학원": ["강남역", "노량진역", "종로"],
                 "회사": ["강남역", "여의도역", "광화문역", "판교"]}


def _ask(miss, hint=None):
    """빠진 최소 조건을 한 번에 자연스럽게 묻는 문장과 버튼.
    hint: 사용자가 이름 없이 말한 '학교'·'회사' → 지역 대신 그곳이 어디인지 묻는다."""
    if "lease" in miss:
        return "전세로 찾을까요, 월세로 찾을까요? 전세와 월세를 함께 말씀하셔서 여쭤봐요.", [_CLARIFY["lease"]]
    money = [m for m in miss if m != "area"]
    if "area" in miss and hint:
        q = (f"{_josa(hint, '은는')} 어디예요? {hint} 이름이나 가까운 역을 알려 주시면 그 근처로 찾아볼게요.")
        clar = [{"id": "workplace", "question": f"{_josa(hint, '은는')} 어디예요?", "options": _WORK_OPTIONS[hint]}]
        if len(money) == 2:
            q += " 보증금이랑 월세도 대략 알려 주세요. (예: 1000/50)"
        elif money == ["deposit"]:
            q += " 보증금은 어느 정도 생각하세요?"
        elif money:
            q += " 월세는 얼마까지 괜찮으세요?"
        if money:
            clar.append(_CLARIFY["budget"] if len(money) == 2 else _CLARIFY[money[0]])
        return q, clar
    if "area" in miss and money:
        return guards.ASK_MIN, [_CLARIFY["area"], _CLARIFY["budget"]]
    if "area" in miss:
        return "어느 동네에서 살고 싶으세요? 회사나 학교 근처도 좋아요.", [_CLARIFY["area"]]
    if money == ["deposit", "monthly_rent"]:
        return "보증금이랑 월세는 어느 정도 생각하세요? (예: 1000/50, 전세 1억)", [_CLARIFY["budget"]]
    if money == ["deposit"]:
        return "보증금은 어느 정도 생각하세요?", [_CLARIFY["deposit"]]
    return "월세는 얼마까지 괜찮으세요?", [_CLARIFY["monthly_rent"]]


def finalize(card):
    """카드에 최소 조건 확인 결과(missing, ready)와 버튼 되묻기를 넣는다."""
    miss = missing_minimum(card)
    card["missing"] = miss
    card["ready"] = not miss
    avoid = (card["conditions"].get("avoid_areas") or {}).get("value") or []
    card["clarifications"] = [
        {**q, "options": [o for o in q["options"] if not any(a in o for a in avoid)]}  # 피하라고 한 곳은 버튼에서 뺀다
        for q in (_ask(miss, card.get("workplace_hint"))[1] if miss else [])
    ]
    return card


def _fill_workplace_answer(text, prev_card, rule):
    """'학교는 어디예요?'라고 물은 뒤의 답("고려대", "강남역이요") → 학교·회사 위치로 받는다."""
    hint = (prev_card or {}).get("workplace_hint")
    conds = rule["card"]["conditions"]
    if not hint or "area" not in (prev_card or {}).get("missing", []) or "workplace" in conds:
        return rule
    pref = conds.get("preferred_areas")
    if pref and pref.get("source") == "inferred":  # 그냥 말한 역·동네 이름 → 살 곳이 아니라 학교·회사
        label = pref["value"][0]
        conds.pop("preferred_areas")
    elif not conds and len(text) <= 20:
        label = re.sub(r"\s*(?:이에요|예요|이요|요|입니다|이야|야|임|이고|다녀요|다녀|다니고\s*있어요?)?[\s.!~]*$", "", text)
        if not re.fullmatch(r"[가-힣A-Za-z0-9 ]{2,15}", label):
            return rule
    else:
        return rule
    conds["workplace"] = rules._cond("place", text, label=label, kind="school" if hint == "학교" else "work")
    rule["intent"], rule["covered"] = "search", True
    return rule


def _fill_bare_answer(text, prev_card, rule):
    """되물은 뒤 숫자만 답한 경우("500", "50 정도요") → 빠졌던 보증금 또는 월세로 채운다."""
    miss = [m for m in (prev_card or {}).get("missing", []) if m != "area"]
    if len(miss) != 1 or rule["card"]["conditions"]:
        return rule
    m = re.fullmatch(rf"\s*{rules._MONEY}\s*(?:정도|쯤|이하|까지)?\s*(?:요|이요)?\s*[.!~]*\s*", text)
    if not m:
        return rule
    key = "deposit_manwon" if miss[0] == "deposit" else "monthly_rent_manwon"
    rule["card"]["conditions"][key] = rules._cond(rules.money(m.group(1)), text)
    rule["intent"], rule["covered"] = "search", True
    return rule


def reply(card, follow_up=False):
    """카드를 보고 친근한 답 문장을 만든다 (Gemini 없이, 숫자는 카드 그대로).
    최소 조건이 다 있으면 '찾아볼게요', 빠졌으면 '알아둘게요' + 빠진 것만 묻는다."""
    c = card["conditions"]
    v = {k: x["value"] for k, x in c.items()}
    parts = []
    if "preferred_areas" in v:
        parts.append(f"{'·'.join(v['preferred_areas'])} 근처")
    if "workplace" in c:
        way = "통학" if c["workplace"].get("kind") == "school" else "출퇴근"
        parts.append(f"{c['workplace'].get('label')}까지 {way}하기 좋은")
    leases = v.get("lease_types", [])
    dep, rent = v.get("deposit_manwon"), v.get("monthly_rent_manwon")
    if "jeonse" in leases and len(leases) == 1 and dep:
        parts.append(f"전세 {_won(dep)} 이하")
    elif dep is not None and rent is not None:
        parts.append(f"보증금 {_won(dep)}·월세 {rent}만 이하")
    elif dep is not None:
        parts.append(f"보증금 {_won(dep)} 이하")
    elif rent is not None:
        parts.append(f"월세 {rent}만 이하")
    if "semi_jeonse" in leases:
        parts.append("반전세")
    if "price_band" in v:
        parts.append("시세보다 저렴한")
    if "max_building_age_years" in v:
        parts.append(f"지은 지 {v['max_building_age_years']}년 이내")
    if "min_area_m2" in v:
        parts.append(f"전용 {v['min_area_m2']:g}㎡(약 {v['min_area_m2'] / 3.3058:.0f}평) 이상")
    types = {"officetel": "오피스텔", "villa": "빌라"}
    noun = "·".join(types[t] for t in v.get("housing_types", [])) or "집"
    head = ", ".join(parts)
    lead = "알겠어요!" if follow_up else "좋아요!"
    miss = missing_minimum(card)
    verb = "알아둘게요" if miss else "찾아볼게요"
    text = f"{lead} {head + ' ' if head else ''}{_josa(noun, '으로로')} {verb}."

    extras = []
    if "max_walk_to_station_min" in v:
        extras.append(f"역까지 걸어서 {v['max_walk_to_station_min']}분 안쪽")
    if "max_commute_min" in v:
        extras.append(f"통근 {v['max_commute_min']}분 이내")
    if v.get("max_transfers") == 0:
        extras.append("환승 없이")
    elif "max_transfers" in v:
        extras.append(f"환승 {v['max_transfers']}번 이하")
    if "min_floor" in v:
        extras.append({1: "반지하는 빼고", 2: "1층은 빼고"}.get(v["min_floor"], f"{v['min_floor']}층 이상"))
    if "avoid_areas" in v:
        extras.append(f"{_josa('·'.join(v['avoid_areas']), '은는')} 빼고")
    if extras:
        text += " " + ", ".join(extras) + " 볼게요."
    outside = [u["phrase"] for u in card.get("unverifiable", []) if u.get("message") == rules.OUTSIDE_MESSAGE]
    others = [u["phrase"] for u in card.get("unverifiable", []) if u.get("message") != rules.OUTSIDE_MESSAGE]
    if outside:
        names = "·".join(outside)
        text += f" '{names}'{_josa(names, '은는')[len(names):]} 서울 밖이라 아직 찾아 드리지 못해요(서울만 가능)."
    if others:
        phrases = "·".join(others)
        text += f" '{phrases}'{_josa(phrases, '은는')[len(phrases):]} 데이터로 확인하기 어려워 참고만 할게요."
    if not c:
        text = f"{lead} 같이 찾아봐요." + (text.split("요.", 1)[1] if outside or others else "")
    if miss:
        text += " " + _ask(miss, card.get("workplace_hint"))[0]
    return text


def _result(intent, card, text, via, started, fixes=None, guard=None, prev_card=None):
    if card and intent == "search":
        finalize(card)
    return {"intent": intent, "card": card, "reply": text, "via": via, "guard": guard,
            "fixes": fixes or [], "changed": _changed(prev_card, card) if card else [],
            "seconds": round(time.time() - started, 3)}


def intake(message, prev_card=None, timeout=None):
    """사용자 말 → {intent, card, reply, via, guard, fixes, changed, seconds}."""
    started = time.time()
    text = rules.normalize(guards.mask_pii(message or ""))

    ok, reason, guide = guards.check_input(text, has_prev=bool(prev_card))
    if (not ok and reason == "off_topic" and (prev_card or {}).get("workplace_hint")
            and "area" in prev_card.get("missing", []) and len(text) <= 20):
        ok = True  # "학교는 어디예요?"에 대한 답("고려대")은 부동산 낱말이 없어도 받는다
    if not ok and reason == "injection":
        # 공격 문구가 섞여 있어도 집 조건은 규칙으로만 읽는다 (Gemini에는 보내지 않음)
        rule = rules.parse(text)
        if rule["card"]["conditions"]:
            card = merge(prev_card, rule["card"])
            text_out = guards.REFUSE + " " + reply(card, bool(prev_card))
            return _result("search", card, text_out, "rules(공격 문구는 무시)", started, guard=reason,
                           prev_card=prev_card)
    if not ok:
        return _result("other", prev_card, guide, "guard", started, guard=reason, prev_card=prev_card)

    rule = _fill_workplace_answer(text, prev_card, _fill_bare_answer(text, prev_card, rules.parse(text)))
    if rule["intent"] == "question" and not rule["card"]["conditions"]:
        return _result("question", prev_card, guards.QUESTION_GUIDE, "rules", started, prev_card=prev_card)
    note = "궁금하신 내용은 아직 설명해 드리지 못해요. " if rule.get("asked") else ""

    def from_rules(via):
        card = merge(prev_card, rule["card"])
        return _result("search", card, note + reply(card, bool(prev_card)), via, started, prev_card=prev_card)

    if rule["covered"]:
        return from_rules("rules")

    user = text if not prev_card else (
        f"이전 조건 카드:\n{json.dumps(prev_card, ensure_ascii=False)}\n\n새 말: {text}")
    hint = (prev_card or {}).get("workplace_hint")
    if hint and "area" in (prev_card or {}).get("missing", []):
        user += f"\n\n참고: 바로 전에 '{hint}는 어디예요?'라고 물었다. 이번 말에 나온 장소 이름은 {hint} 위치(workplace)다."
    user += '\n\n출력은 최상위 키가 "intent", "card" 두 개인 JSON 객체 하나다.'
    try:
        out, _ = llm.generate_json(SYSTEM, user, timeout=timeout)
    except llm.LLMError as e:
        if rule["intent"] == "search" or (prev_card and rule["card"]["conditions"]):
            return from_rules(f"rules(Gemini 실패: {e})")
        msg = guards.QUESTION_GUIDE if rule["intent"] == "question" else guards.GUIDE
        return _result(rule["intent"], prev_card, msg, f"rules(Gemini 실패: {e})", started, prev_card=prev_card)

    out = out if isinstance(out, dict) else {}
    if not isinstance(out.get("card"), dict) and "conditions" in out:
        # 카드만 주거나 intent와 카드 칸을 섞어 준 경우
        out = {"intent": out.get("intent") or "search", "card": out}
    intent = out.get("intent") if out.get("intent") in ("search", "question", "other") else "other"
    via = f"gemini({llm.last_model()})"
    if intent == "question":
        return _result("question", prev_card, guards.QUESTION_GUIDE, via, started, prev_card=prev_card)
    if intent == "other":
        return _result("other", prev_card, guards.GUIDE, via, started, guard="off_topic", prev_card=prev_card)

    card = guards.normalize_card(out.get("card"), text, prev_card)
    if card is None:
        return from_rules(f"rules(Gemini 카드 없음)")
    card, fixes = guards.check_card(card, rule["card"], text, prev_card)
    if prev_card and not card["conditions"] and prev_card.get("conditions"):
        card = merge(prev_card, rule["card"])  # Gemini가 이전 조건을 다 잃어버린 경우
    if "workplace" not in card["conditions"]:
        # '학교 근처'처럼 이름 없는 학교·회사 표시는 Gemini 카드에 없으므로 규칙·이전 카드에서 이어 준다
        hint = rule["card"].get("workplace_hint") or (prev_card or {}).get("workplace_hint")
        if hint:
            card["workplace_hint"] = hint
    return _result("search", card, note + reply(card, bool(prev_card)), via, started, fixes=fixes, prev_card=prev_card)
