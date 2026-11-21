"""BE 집 검색 요청. 챗봇은 계산하지 않는다: ready인 조건 카드를 BE에 보내고 받은 결과를 그대로 전한다.

어디에 요청하나 (위에서부터 먼저 있는 것)
1. config.BACKEND_SEARCH_URL이 있으면: POST {"session_id", "keywords", "card"} → BE 응답(아래 형식)
2. DB 접속 정보(SALGU_DB_*)가 있으면: 추천 엔진(AI/property_recommendation)을 직접 부른다 (recommender.py)
3. 둘 다 없으면(로컬 시험): 로컬 예시 응답. mock=true로 표시하며 실제 매물이 아니다.

BE 응답 형식 (초안, BE와 합의 필요). 후보는 BE가 추천 순서대로 정렬해 준다.
{"count": 3, "candidates": [{"name": "...", "address": "...", "housing_type": "officetel",
  "deposit_manwon": 1000, "monthly_rent_manwon": 48, "area_m2": 23.1, "floor": 3,
  "station": "신촌역", "walk_to_station_min": 4}]}
"""

import json
import time
import urllib.request

from . import config, recommender


def search(card, session_id=None):
    """→ {"ok", "mock", "source", "count", "candidates", "notes", "error", "seconds"}"""
    started = time.time()
    if not config.BACKEND_SEARCH_URL and recommender.configured():
        return recommender.search(card)
    if not config.BACKEND_SEARCH_URL:
        res = mock_search(card)
        return {"ok": True, "mock": True, "source": "로컬 예시 응답", "error": None, "notes": [], **res,
                "seconds": round(time.time() - started, 3)}
    req = urllib.request.Request(
        config.BACKEND_SEARCH_URL,
        data=json.dumps({"session_id": session_id, "keywords": _keywords(card), "card": card},
                        ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=config.BACKEND_TIMEOUT_S) as r:
            data = json.loads(r.read().decode("utf-8"))
        cands = data.get("candidates") or []
        return {"ok": True, "mock": False, "source": "BE 검색 API", "error": None,
                "count": int(data.get("count", len(cands))), "candidates": cands, "notes": data.get("notes") or [],
                "seconds": round(time.time() - started, 3)}
    except Exception as e:
        return {"ok": False, "mock": False, "source": "BE 검색 API", "error": f"{type(e).__name__}: {e}", "count": 0,
                "candidates": [], "notes": [], "seconds": round(time.time() - started, 3)}


def _keywords(card):
    conds = card.get("conditions") or {}
    return {k: (c.get("label") if k == "workplace" else c.get("value")) for k, c in sorted(conds.items())}


def mock_search(card):
    """로컬 예시 응답. 카드 조건을 넘지 않는 가짜 후보 3곳 (실제 매물 아님)."""
    c = {k: x.get("label") if k == "workplace" else x.get("value") for k, x in card["conditions"].items()}
    area = (c.get("preferred_areas") or [c.get("workplace") or "서울"])[0]
    station = area if area.endswith("역") else f"{area}역"
    kind = (c.get("housing_types") or ["officetel"])[0]
    deposit = c.get("deposit_manwon") or 0
    rent = 0 if c.get("lease_types") == ["jeonse"] else (c.get("monthly_rent_manwon") or 0)
    walk_max = c.get("max_walk_to_station_min") or 10
    base_area = max(c.get("min_area_m2") or 0, 20)
    floor_min = max(c.get("min_floor") or 0, 2)
    label = {"officetel": "오피스텔", "villa": "빌라"}[kind]
    cands = []
    for i, (rent_cut, walk) in enumerate(((2, 4), (0, 7), (5, 9))):
        cands.append({
            "name": f"{area} 예시 {label} {'ABC'[i]}", "address": f"{area} 근처 (예시)", "housing_type": kind,
            "deposit_manwon": deposit, "monthly_rent_manwon": max(rent - rent_cut, 0) if rent else 0,
            "area_m2": round(base_area + i * 3.3, 1), "floor": floor_min + i,
            "station": station, "walk_to_station_min": min(walk, walk_max),
        })
    return {"count": len(cands), "candidates": cands}
