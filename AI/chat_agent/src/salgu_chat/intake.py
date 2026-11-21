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
    new = new_card["conditions"]
    for key in ("preferred_areas", "avoid_areas"):
        if key in new:
            other = "avoid_areas" if key == "preferred_areas" else "preferred_areas"
            if other in conds:
                conds[other]["value"] = [a for a in conds[other]["value"] if a not in new[key]["value"]]
                if not conds[other]["value"]:
                    conds.pop(other)
            if key in conds:
                merged = list(dict.fromkeys(conds[key]["value"] + new[key]["value"]))
                new[key] = {**new[key], "value": merged}
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


def reply(card, follow_up=False):
    """카드를 보고 친근한 답 문장을 만든다 (Gemini 없이, 숫자는 카드 그대로)."""
    c = card["conditions"]
    v = {k: x["value"] for k, x in c.items()}
    parts = []
    if "preferred_areas" in v:
        parts.append(f"{'·'.join(v['preferred_areas'])} 근처")
    if "workplace" in c:
        parts.append(f"{c['workplace'].get('label')}까지 출퇴근하기 좋은")
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
    text = f"{lead} {head + ' ' if head else ''}{_josa(noun, '으로로')} 찾아볼게요."

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
    if card.get("unverifiable"):
        phrases = "·".join(u["phrase"] for u in card["unverifiable"])
        particle = _josa(phrases, "은는")[len(phrases):]
        text += f" '{phrases}'{particle} 데이터로 확인하기 어려워 참고만 할게요."
    if not c:
        text = f"{lead} 서울에서 살 집을 찾아볼게요. 원하는 동네나 예산을 말해 주시면 더 잘 맞춰 드릴게요."
    return text


def _result(intent, card, text, via, started, fixes=None, guard=None, prev_card=None):
    return {"intent": intent, "card": card, "reply": text, "via": via, "guard": guard,
            "fixes": fixes or [], "changed": _changed(prev_card, card) if card else [],
            "seconds": round(time.time() - started, 3)}


def intake(message, prev_card=None, timeout=None):
    """사용자 말 → {intent, card, reply, via, guard, fixes, changed, seconds}."""
    started = time.time()
    text = guards.mask_pii(message or "").strip()

    ok, reason, guide = guards.check_input(text, has_prev=bool(prev_card))
    if not ok:
        return _result("other", prev_card, guide, "guard", started, guard=reason, prev_card=prev_card)

    rule = rules.parse(text)
    if rule["intent"] == "question" and not rule["card"]["conditions"]:
        return _result("question", None, guards.QUESTION_GUIDE, "rules", started)

    def from_rules(via):
        card = merge(prev_card, rule["card"])
        return _result("search", card, reply(card, bool(prev_card)), via, started, prev_card=prev_card)

    if rule["covered"]:
        return from_rules("rules")

    user = text if not prev_card else (
        f"이전 조건 카드:\n{json.dumps(prev_card, ensure_ascii=False)}\n\n새 말: {text}")
    try:
        out, _ = llm.generate_json(SYSTEM, user, timeout=timeout)
    except llm.LLMError as e:
        if rule["intent"] == "search" or (prev_card and rule["card"]["conditions"]):
            return from_rules(f"rules(Gemini 실패: {e})")
        msg = guards.QUESTION_GUIDE if rule["intent"] == "question" else guards.GUIDE
        return _result(rule["intent"], prev_card, msg, f"rules(Gemini 실패: {e})", started, prev_card=prev_card)

    out = out if isinstance(out, dict) else {}
    if "intent" not in out and "conditions" in out:
        out = {"intent": "search", "card": out}
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
    return _result("search", card, reply(card, bool(prev_card)), via, started, fixes=fixes, prev_card=prev_card)
