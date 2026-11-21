"""중개사무소 전화 요청 '초안' 만들기. 챗봇은 전화를 걸지 않는다.

사용자가 추천 매물을 보고 "이 집 보고 싶어", "2번 문의해 줘"라고 하면, 그 매물이 있는 동의 중개사무소를
실거래 DB(real_estate_agencies)에서 골라 전화 서버(AI/phone_agent) 문의 요청 형식으로 초안을 만든다.
실제 전화는 사용자가 화면에서 방문 가능 시간·공개할 정보를 고르고 승인한 뒤 BE가 전화 서버에 보낸다.

초안 형식(action):
{"type": "broker_call_request", "status": "needs_approval", "listing": {...추천 매물...},
 "needs_user_input": ["visit_windows", "share", "approval_id"],
 "request": {전화 서버 POST /api/broker-call-batches 본문, approval_id·visit_windows만 비어 있음}}
"""

import re

from . import config, recommender

MAX_BROKERS = 3  # 기본으로 제안할 사무소 수 (전화 서버는 최대 10곳)


def normalize_phone(phone):
    """'313-1234' → '02-313-1234' (서울 번호에 지역번호가 빠진 경우). 숫자가 너무 적으면 빈 값."""
    p = re.sub(r"[^\d-]", "", str(phone or "")).strip("-")
    digits = re.sub(r"\D", "", p)
    if len(digits) < 7:
        return ""
    if not digits.startswith("0"):
        p = "02-" + p
    return p


def split_address(address):
    """'서울특별시 서대문구 대현동 37-18' → ('서대문구', '대현동')."""
    parts = str(address or "").split()
    gu = next((x for x in parts if x.endswith("구")), "")
    dong = next((x for x in parts if re.search(r"(동|가)$", x) and x != gu), "")
    return gu, dong


async def _find(gu, dong, limit):
    """같은 동에서 영업 중이고 전화번호가 있는 사무소를 조회 수 많은 순으로. 모자라면 같은 구에서 채운다."""
    from sqlalchemy import text
    sql = text("""
        SELECT registration_no, agency_name, phone, legal_dong_name
        FROM public.real_estate_agencies
        WHERE district_name = :gu AND status = '영업중' AND coalesce(trim(phone), '') <> ''
        ORDER BY (legal_dong_name = :dong) DESC, source_query_count DESC NULLS LAST, registration_no
        LIMIT :limit""")
    async with recommender._runner._db().connect() as conn:
        rows = (await conn.execute(sql, {"gu": gu, "dong": dong, "limit": limit * 3})).all()
    out = []
    for reg, name, phone, d in rows:
        phone = normalize_phone(phone)
        if phone and reg and name and all(b["reg"] != reg for b in out):
            out.append({"reg": reg, "name": name, "phone": phone, "dong": d})
        if len(out) >= limit:
            break
    return out


def find_agencies(address, limit=MAX_BROKERS):
    """추천 매물 주소 → 전화할 중개사무소 목록. DB가 없으면 빈 목록."""
    gu, dong = split_address(address)
    if not gu or not recommender.configured():
        return []
    import asyncio
    fut = asyncio.run_coroutine_threadsafe(_find(gu, dong, limit), recommender._runner._start())
    return fut.result(timeout=recommender.TIMEOUT_S)


def build(card, listing, agencies):
    """조건 카드 + 고른 추천 매물 + 중개사무소 → 전화 요청 초안(action)."""
    conds = (card or {}).get("conditions") or {}
    v = {k: c.get("value") for k, c in conds.items()}
    gu, dong = split_address(listing.get("address"))
    jeonse = v.get("lease_types") == ["jeonse"]
    name = listing.get("name") or ""
    request = {
        "approval_id": None,  # 사용자가 승인할 때 BE가 만든다 (같은 값이면 전화 서버가 다시 걸지 않음)
        "search": {
            "dong": dong or gu,
            "ref_building": "" if re.match(r".+동 [\d-]+$", name) else name,  # 건물명 없는 매물은 참고 건물 없이
            "housing_type": listing.get("housing_type") or (v.get("housing_types") or ["villa"])[0],
            "deposit_manwon": int(v.get("deposit_manwon") or 0),
            "monthly_rent_manwon": 0 if jeonse else int(v.get("monthly_rent_manwon") or 0),
            "area_m2": listing.get("area_m2"),
        },
        "prep": {"move_in": "", "term": "", "pet": False, "surname": ""},
        "share": {"conditions": True, "visit_time": True, "surname": False, "contact": False},
        "keep_transcript": False,
        "brokers": [{"reg": a["reg"], "name": a["name"], "phone": a["phone"], "visit_windows": []} for a in agencies],
    }
    if any(u.get("phrase") == "반려동물" for u in (card or {}).get("unverifiable", [])):
        request["prep"]["pet"] = True  # 전화 서버가 반려동물 가능 여부를 물어본다
    return {
        "type": "broker_call_request",
        "status": "needs_approval" if agencies else "no_agencies",
        "listing": {k: listing.get(k) for k in ("name", "address", "housing_type", "deposit_manwon",
                                                  "monthly_rent_manwon", "area_m2", "floor")},
        "needs_user_input": ["visit_windows", "share", "approval_id"],
        "request": request,
        "phone_agent": {"endpoint": "POST /api/broker-call-batches", "contract": "AI/phone_agent/contracts/io.md"},
    }
