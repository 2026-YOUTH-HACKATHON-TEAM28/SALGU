"""출처가 다른 매물의 중복 후보 묶기 (specs/07-mcp-dedupe.md).

- 서로 다른 사무소의 방끼리만 비교한다. 같은 사무소 안의 방은 묶지 않는다.
- 같은 건물 이름(오피스텔·빌라 같은 일반 단어를 뺀 뒤)이어야 한다. 층·호수는 둘 다 있을 때 다르면 묶지 않고,
  한쪽이 모르면 막지 않는다 → suspected.
- 확정 통화에서 받은 호수(confirmed_unit)로 다시 계산: 모두 같은 호수로 확인되면 likely_same, 다르면 묶음에서 빠짐.
- 최종 판정은 등기부 소재지(등기 담당).
"""

from __future__ import annotations

import re
from typing import Optional

GENERIC = ("오피스텔", "빌라", "주택", "원룸", "건물", "아파트")
_SPACE = re.compile(r"[\s·,.\-()]+")


def building_key(name: Optional[str]) -> str:
    """'해든빌라' → '해든', '해든 오피스텔' → '해든'."""
    key = _SPACE.sub("", name or "")
    for word in GENERIC:
        key = key.replace(word, "")
    return key


def _digits(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    m = re.search(r"\d+", value)
    return m.group(0) if m else _SPACE.sub("", value)


def _unit(item: dict) -> Optional[str]:
    return item.get("confirmed_unit") or (item.get("listing") or {}).get("unit")


def _compatible(a: dict, b: dict) -> bool:
    la, lb = a.get("listing") or {}, b.get("listing") or {}
    for x, y in ((_digits(la.get("floor")), _digits(lb.get("floor"))), (_digits(_unit(a)), _digits(_unit(b)))):
        if x and y and x != y:
            return False
    return True


def _reasons(members: list[dict]) -> list[str]:
    listings = [m.get("listing") or {} for m in members]
    reasons = [f"같은 건물: {listings[0].get('building')}"]
    floors = {l.get("floor") for l in listings}
    if None not in floors and len(floors) == 1:
        reasons.append(f"같은 층: {floors.pop()}")
    units = {_unit(m) for m in members}
    if None not in units and len(units) == 1:
        reasons.append(f"같은 호수: {units.pop()}")
    prices = [(l.get("deposit_manwon"), l.get("monthly_rent_manwon")) for l in listings]
    if all(None not in p for p in prices):
        reasons.append("보증금·월세 같음" if len(set(prices)) == 1 else "보증금·월세 다름")
    return reasons


def duplicate_groups(items: list[dict]) -> list[dict]:
    """items: {call_id, listing_index, broker, listing, confirmed_unit?} → duplicate_groups."""
    groups: list[list[dict]] = []
    for item in items:
        key = building_key((item.get("listing") or {}).get("building"))
        if not key:
            continue
        for group in groups:
            same_building = building_key(group[0]["listing"].get("building")) == key
            other_broker = all(m["call_id"] != item["call_id"] and m["broker"] != item["broker"] for m in group)
            if same_building and other_broker and all(_compatible(m, item) for m in group):
                group.append(item)
                break
        else:
            groups.append([item])

    result = []
    for members in (g for g in groups if len(g) >= 2):
        confirmed = [m.get("confirmed_unit") for m in members]
        status = "likely_same" if all(confirmed) and len({_digits(u) for u in confirmed}) == 1 else "suspected"
        result.append({
            "group_id": f"dup{len(result) + 1}",
            "status": status,
            "members": [{"call_id": m["call_id"], "listing_index": m["listing_index"], "broker": m["broker"]}
                        for m in members],
            "reasons": _reasons(members),
        })
    return result
