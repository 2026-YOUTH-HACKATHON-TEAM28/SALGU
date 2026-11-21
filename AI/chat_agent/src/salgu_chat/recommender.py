"""매물 추천 연동: 조건 카드 → 추천 엔진(AI/property_recommendation) → 챗봇이 전할 결과.

추천 계산은 추천 엔진(수정 담당)이 한다. 이 모듈은 둘 사이의 차이만 맞춘다.
- 동네 이름: 엔진은 DB 주소(region_address)에서 글자로 찾는다. "홍대"·"강남역"은 주소에 없으므로
  동 이름(서교동·역삼동)으로 바꿔 찾고, 결과가 없으면 그 구 전체로 넓힌다.
- 회사·학교: 카카오 REST 키(KAKAO_REST_API_KEY)가 있으면 엔진에 카카오 통근 계산기(KakaoCommuteProvider)와
  교통 공공데이터(버스·지하철 DB)를 넘겨 실제 통근·배차·주변 정류장까지 계산한다. 살 곳을 말하지 않았으면
  엔진이 회사 기준 10→20→40km로 넓혀 찾는다. 키가 없으면 통근 조건을 빼고 알리고, 회사·학교가 있는 구에서 찾는다.
- 중개사무소: realtors(주소)가 엔진의 find_nearest_realtors(카카오 AG2 거리순 + 중개업소 DB 대조)를 부른다.
- 결과: 엔진 출력(RecommendationOutput)을 챗봇 후보 형식으로 바꾼다. 숫자는 엔진 값 그대로.

DB 접속 정보(.env): SALGU_DB_HOST, SALGU_DB_USER, SALGU_DB_PASSWORD, SALGU_DB_PORT(5432), SALGU_DB_NAME(postgres)
"""

import asyncio
import copy
import os
import re
import sys
import threading
import time

from . import config

ENGINE_SRC = config.ROOT.parent / "property_recommendation" / "src"
TIMEOUT_S = config._int("RECOMMEND_TIMEOUT_S", 20)
LIMIT = 5

# 라벨 → (동 이름들, 구). 라벨에 '역'·'입구'가 붙어도 찾는다. 서울 밖·모르는 곳은 없음.
AREA_MAP = {
    "홍대": (["서교동", "동교동", "합정동", "연남동"], "마포구"), "홍익대": (["서교동", "상수동"], "마포구"),
    "합정": (["합정동"], "마포구"), "망원": (["망원동"], "마포구"), "연남": (["연남동"], "마포구"),
    "상수": (["상수동"], "마포구"), "상암": (["상암동"], "마포구"), "공덕": (["공덕동"], "마포구"),
    "서강대": (["신수동", "대흥동"], "마포구"), "마포": ([], "마포구"),
    "신촌": (["창천동", "대현동", "신촌동"], "서대문구"), "연세대": (["신촌동", "창천동"], "서대문구"),
    "연대": (["신촌동", "창천동"], "서대문구"), "이대": (["대현동"], "서대문구"), "이화여대": (["대현동"], "서대문구"),
    "신림": (["신림동"], "관악구"), "봉천": (["봉천동"], "관악구"), "서울대": (["신림동", "봉천동"], "관악구"),
    "낙성대": (["봉천동"], "관악구"), "건대": (["화양동", "자양동"], "광진구"), "건국대": (["화양동"], "광진구"),
    "성수": (["성수동"], "성동구"), "왕십리": (["행당동", "하왕십리동", "상왕십리동"], "성동구"),
    "한양대": (["행당동", "사근동"], "성동구"), "잠실": (["잠실동"], "송파구"), "여의도": (["여의도동"], "영등포구"),
    "당산": (["당산동"], "영등포구"), "문래": (["문래동"], "영등포구"), "영등포": ([], "영등포구"),
    "이태원": (["이태원동"], "용산구"), "한남": (["한남동"], "용산구"), "용산": ([], "용산구"),
    "회기": (["회기동"], "동대문구"), "경희대": (["회기동"], "동대문구"), "외대": (["이문동"], "동대문구"),
    "혜화": (["혜화동", "명륜"], "종로구"), "대학로": (["혜화동", "명륜", "동숭동"], "종로구"),
    "성균관대": (["명륜"], "종로구"), "종각": ([], "종로구"), "광화문": ([], "종로구"), "종로": ([], "종로구"),
    "을지로": (["을지로"], "중구"), "충무로": (["충무로"], "중구"), "명동": (["명동"], "중구"),
    "시청": ([], "중구"), "동국대": (["필동", "장충동"], "중구"), "서울역": ([], "중구"),
    "사당": (["사당동"], "동작구"), "노량진": (["노량진동"], "동작구"), "중앙대": (["흑석동"], "동작구"),
    "숭실대": (["상도동"], "동작구"), "목동": (["목동"], "양천구"), "신도림": (["신도림동"], "구로구"),
    "구디": (["구로동"], "구로구"), "구로디지털단지": (["구로동"], "구로구"), "가산": (["가산동"], "금천구"),
    "강남": (["역삼동", "논현동"], "강남구"), "역삼": (["역삼동"], "강남구"), "선릉": (["대치동", "삼성동", "역삼동"], "강남구"),
    "삼성": (["삼성동"], "강남구"), "논현": (["논현동"], "강남구"), "신사": (["신사동"], "강남구"),
    "압구정": (["압구정동"], "강남구"), "청담": (["청담동"], "강남구"), "대치": (["대치동"], "강남구"),
    "교대": (["서초동"], "서초구"), "서초": ([], "서초구"), "방배": (["방배동"], "서초구"), "송파": ([], "송파구"),
    "마곡": (["마곡동"], "강서구"), "수유": (["수유동"], "강북구"), "미아": (["미아동"], "강북구"),
    "창동": (["창동"], "도봉구"), "길음": (["길음동"], "성북구"), "성신여대": (["동선동", "돈암동"], "성북구"),
    "안암": (["안암동"], "성북구"), "고대": (["안암동"], "성북구"), "고려대": (["안암동"], "성북구"),
}
_GU = {"종로", "중", "용산", "성동", "광진", "동대문", "중랑", "성북", "강북", "도봉", "노원", "은평", "서대문", "마포",
       "양천", "강서", "구로", "금천", "영등포", "동작", "관악", "서초", "강남", "송파", "강동"}


def _clean(label):
    """'홍대입구역' → '홍대', '강남역' → '강남', '망원동' 그대로."""
    name = re.sub(r"\s+", "", str(label))
    name = re.sub(r"(입구)?역$", "", name)
    return re.sub(r"(근처|쪽|부근|인근|주변)$", "", name)


def _gu_name(name):
    """'마포', '마포구' → '마포구'. 구 이름이 아니면 None."""
    if name.endswith("구") and name[:-1] in _GU:
        return name
    return name + "구" if name in _GU else None


def resolve_area(label):
    """라벨 → (좁게 찾을 이름들, 넓게 찾을 구 또는 None).
    '강남'·'마포구'처럼 구를 말하면 구 전체, '강남역'·'홍대'처럼 역·동네를 말하면 동부터 찾는다."""
    raw = re.sub(r"\s+", "", str(label))
    name = _clean(label)
    station = bool(re.search(r"역$", raw))
    if _gu_name(name) and not (station and name in AREA_MAP):
        gu = _gu_name(name)
        return [gu], gu
    if name in AREA_MAP:
        dongs, gu = AREA_MAP[name]
        # 엔진은 주소에 글자가 들어 있는지로 찾는다: '창동'만 주면 염창동·평창동도 걸리므로 '도봉구 창동'으로 넘긴다
        return ([f"{gu} {d}" for d in dongs] or [gu]), gu
    return [name], None  # 동 이름("역삼동") 등은 그대로 주소에서 찾는다


def avoid_names(label):
    """피할 곳: 구를 말하면 구 전체, 동네를 말하면 그 동들만 뺀다 ('홍대 빼고'가 마포구 전체를 빼지 않게)."""
    name = _clean(label)
    return [_gu_name(name)] if _gu_name(name) else resolve_area(label)[0]


def _env(name, default=""):
    return config.ENV.get(name) or os.environ.get(name) or default


def configured():
    """DB 접속 정보가 있으면 True (실제 추천 엔진을 쓴다)."""
    return bool(_env("SALGU_DB_HOST") and _env("SALGU_DB_USER") and _env("SALGU_DB_PASSWORD"))


def _engine_modules():
    """추천 엔진 패키지를 불러온다 (AI/property_recommendation/src). 의존성이 없으면 ImportError."""
    if str(ENGINE_SRC) not in sys.path:
        sys.path.insert(0, str(ENGINE_SRC))
    import property_recommendation as pr
    return pr


def commute_ready():
    """카카오 통근 계산기를 쓸 수 있는지(REST 키가 있는지)."""
    return bool(_env("KAKAO_REST_API_KEY"))


def plan(card, commute=None):
    """조건 카드 → 엔진에 넘길 카드 단계들(좁게 → 넓게)과 알릴 말.
    commute: 통근 계산기를 쓸 수 있는지(None 이면 키 유무로 판단).
    반환: (stages: [(card, note_or_None)], notes)"""
    base = copy.deepcopy(card)
    conds = base.setdefault("conditions", {})
    notes = []
    work = (conds.get("workplace") or {}).get("label")
    way = "통학" if (conds.get("workplace") or {}).get("kind") == "school" else "통근"
    commute = commute_ready() if commute is None else commute

    # 통근 계산기가 있으면 회사·통근 조건을 그대로 엔진에 넘긴다(통근권 10→20→40km 확장은 엔진이 한다)
    if work and commute:
        pref = (conds.get("preferred_areas") or {}).get("value") or []
        avoid = (conds.get("avoid_areas") or {}).get("value") or []
        if avoid:
            conds["avoid_areas"] = {**conds["avoid_areas"],
                                    "value": list(dict.fromkeys(n for a in avoid for n in avoid_names(a)))}
        if not pref:
            return [(base, f"{work}까지 실제 {way} 경로로 찾았어요.")], notes
        narrow = []
        for label in pref:
            names, _gu = resolve_area(label)
            narrow += names
        base["conditions"]["preferred_areas"] = {"value": list(dict.fromkeys(narrow)), "source": "stated"}
        return [(base, None)], notes

    # 통근 계산기가 아직 없다: 통근 조건을 빼고 알린다
    if work:
        for key in ("workplace", "max_commute_min", "max_transfers", "max_bus_headway_min"):
            conds.pop(key, None)
        base["priorities"] = [p for p in base.get("priorities") or [] if p not in ("commute", "bus_headway")]
        notes.append(f"{work}까지 {way} 시간·환승은 아직 계산하지 못해요(교통 데이터 연결 전).")
    # 엔진은 workplace 없이 역 도보·배차 조건이 오면 오류를 낸다 → 빼고 알린다(회사·학교 유무와 상관없이)
    said = [k for k in ("max_walk_to_station_min", "max_bus_headway_min") if conds.pop(k, None)]
    if said:
        base["priorities"] = [p for p in base.get("priorities") or [] if p != "bus_headway"]
        what = "·".join({"max_walk_to_station_min": "역까지 걷는 시간", "max_bus_headway_min": "버스 배차"}[k] for k in said)
        notes.append(f"{what} 조건은 아직 확인하지 못해요(교통 데이터 연결 전).")

    pref = (conds.get("preferred_areas") or {}).get("value") or []
    avoid = (conds.get("avoid_areas") or {}).get("value") or []
    if avoid:
        conds["avoid_areas"] = {**conds["avoid_areas"],
                                "value": list(dict.fromkeys(n for a in avoid for n in avoid_names(a)))}

    labels, where = pref, None
    if not pref and work:
        labels, where = [work], f"{work} 주변"
    if not labels:
        return [(base, None)], notes

    narrow, wide = [], []
    for label in labels:
        names, gu = resolve_area(label)
        narrow += names
        wide.append(gu or names[0])
    stages = []
    first = copy.deepcopy(base)
    first["conditions"]["preferred_areas"] = {"value": list(dict.fromkeys(narrow)), "source": "stated"}
    stages.append((first, f"{where}에서 찾았어요." if where else None))
    wide = list(dict.fromkeys(wide))
    if wide != list(dict.fromkeys(narrow)):
        second = copy.deepcopy(base)
        second["conditions"]["preferred_areas"] = {"value": wide, "source": "inferred"}
        shown = "·".join(_clean(l) for l in labels)
        stages.append((second, f"{shown} 바로 근처에는 조건에 맞는 실거래가 없어 {'·'.join(wide)} 전체에서 찾았어요."))
    return stages, notes


def to_candidate(item):
    """엔진 후보(PropertyRecommendation) → 챗봇 후보 dict."""
    d = item.model_dump(mode="json")
    name = d["name"]
    if re.fullmatch(r"\(.*\)|[\d-]+", name or ""):  # 건물명이 없으면 엔진이 지번을 이름으로 쓴다 → '창천동 4-121'
        parts = d["address"].split()
        name = f"{parts[-2]} {name.strip('()')}" if len(parts) >= 2 else name
    return {
        "name": name, "address": d["address"], "housing_type": d["housing_type"], "rent_type": d["rent_type"],
        "deposit_manwon": d["deposit_manwon"], "monthly_rent_manwon": d["monthly_rent_manwon"],
        "area_m2": d["area_m2"], "floor": d["floor"], "construction_year": d["construction_year"],
        "contract_date": d["contract_date"], "transaction_count": d["transaction_count"],
        "score": d["score"], "reasons": d["reasons"],
        "market_median_deposit_manwon": d["market_median_deposit_manwon"],
        "market_median_monthly_rent_manwon": d["market_median_monthly_rent_manwon"],
        "commute_minutes": d["commute_minutes"], "transfers": d["transfers"],
        "station": d.get("station"), "walk_to_station_min": d.get("walk_to_station_min"),
        "commute_distance_km": d.get("commute_distance_km"), "transit_fare_won": d.get("transit_fare_won"),
        "route_url": d.get("route_url"), "transit_legs": d.get("transit_legs") or [],
        "nearby_bus_stops": d.get("nearby_bus_stops") or [],
        "source_table": d["source_table"], "source_row": d["source_row"], "is_live_listing": False,
    }


async def recommend_async(card, repository, commute_provider=None, public_data=None):
    """엔진을 단계별로 부른다(좁게 → 결과 없으면 넓게). repository는 엔진의 PropertyRepository.
    commute_provider·public_data 가 있으면 실제 통근 경로와 버스·지하철 공공데이터를 붙인다."""
    pr = _engine_modules()
    stages, notes = plan(card, commute=commute_provider is not None)
    out, used_note = None, None
    for stage_card, note in stages:
        criteria = pr.RecommendationInput.from_condition_card(stage_card, limit=LIMIT)
        out = await pr.PropertyRecommendationService(repository, commute_provider, public_data).recommend(criteria)
        used_note = note
        if out.count:
            break
    caps = [t.split(" 상한")[0] for t in out.applied_tolerances]  # ["보증금 상한 +10%", "월세 상한 +10%"]
    tolerance = [f"예산을 '정도'로 말씀하셔서 {'·'.join(caps)} 상한을 10% 넉넉히 봤어요."] if caps else []
    notes = ([used_note] if used_note else []) + notes + list(out.unapplied_conditions) + tolerance
    return {"count": out.count, "candidates": [to_candidate(c) for c in out.candidates], "notes": notes,
            "query": out.query.model_dump(mode="json")}


class _Runner:
    """DB 연결을 한 번만 만들고, 따로 도는 이벤트 루프에서 추천을 실행한다 (FastAPI 동기 핸들러에서 부르기 위해)."""

    def __init__(self):
        self._loop = None
        self._engine = None
        self._commute = None
        self._lock = threading.Lock()

    def _provider(self):
        """카카오 통근 계산기(한 번만 만들어 경로·좌표 캐시를 재사용). 키가 없으면 None."""
        if self._commute is None and commute_ready():
            pr = _engine_modules()
            self._commute = pr.KakaoCommuteProvider(pr.KakaoCommuteConfig(api_key=_env("KAKAO_REST_API_KEY")))
        return self._commute

    def _start(self):
        with self._lock:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                threading.Thread(target=self._loop.run_forever, name="recommender-loop", daemon=True).start()
        return self._loop

    def _db(self):
        if self._engine is None:
            from sqlalchemy import URL
            from sqlalchemy.ext.asyncio import create_async_engine
            url = URL.create("postgresql+asyncpg", username=_env("SALGU_DB_USER"),
                             password=_env("SALGU_DB_PASSWORD"), host=_env("SALGU_DB_HOST"),
                             port=int(_env("SALGU_DB_PORT", "5432")), database=_env("SALGU_DB_NAME", "postgres"))
            # 공용 Supabase 풀러(세션 모드)는 팀 전체 동시 접속이 15개로 제한된다.
            # 기본 풀(최대 15개)이면 한도를 혼자 다 쓸 수 있어, 챗봇 서버는 최대 3개만 쓴다.
            # 포트 6543(트랜잭션 모드)은 이 한도를 받지 않지만, 요청마다 다른 실제 연결로 갈 수 있어
            # 이름 있는 준비 문장(prepared statement)을 캐시하면 안 된다 → 캐시를 끄고 이름을 매번 새로 만든다.
            args = {"ssl": "require"}
            if int(_env("SALGU_DB_PORT", "5432")) == 6543:
                import uuid
                args.update(statement_cache_size=0, prepared_statement_cache_size=0,
                            prepared_statement_name_func=lambda: f"__salgu_{uuid.uuid4().hex}__")
            self._engine = create_async_engine(url, connect_args=args, hide_parameters=True,
                                               pool_pre_ping=True, pool_size=2, max_overflow=1,
                                               pool_recycle=300, pool_timeout=10)
        return self._engine

    async def _run(self, card):
        from sqlalchemy.ext.asyncio import AsyncSession
        _engine_modules()
        from property_recommendation.repository import SqlPropertyRepository
        from property_recommendation.public_data import SqlPublicDataRepository
        async with AsyncSession(self._db()) as session:
            provider = self._provider()
            return await recommend_async(card, SqlPropertyRepository(session), provider,
                                         SqlPublicDataRepository(session) if provider else None)

    async def _realtors(self, address, limit, max_distance_m):
        from sqlalchemy.ext.asyncio import AsyncSession
        pr = _engine_modules()
        from property_recommendation.public_data import SqlPublicDataRepository
        provider = self._provider()
        if provider is None:
            raise RuntimeError("KAKAO_REST_API_KEY 가 없어 중개사무소를 찾을 수 없어요")
        async with AsyncSession(self._db()) as session:
            service = pr.DatabaseRealtorService(SqlPublicDataRepository(session), provider)
            criteria = pr.RealtorSearchInput(property_address=address, limit=limit, max_distance_m=max_distance_m)
            out = await service.find_nearest(criteria)
            return out.model_dump(mode="json")

    def realtors(self, address, limit, max_distance_m, timeout=TIMEOUT_S):
        fut = asyncio.run_coroutine_threadsafe(self._realtors(address, limit, max_distance_m), self._start())
        return fut.result(timeout=timeout)

    async def _warm(self):
        from sqlalchemy import text
        async with self._db().connect() as conn:
            await conn.execute(text("SELECT 1"))

    def run(self, card, timeout=TIMEOUT_S):
        fut = asyncio.run_coroutine_threadsafe(self._run(card), self._start())
        return fut.result(timeout=timeout)

    def warm(self):
        """첫 요청이 느린 것(콜드 스타트)을 줄이려고 서버 시작 때 DB 연결을 미리 연다."""
        return asyncio.run_coroutine_threadsafe(self._warm(), self._start())


_runner = _Runner()


def search(card):
    """→ backend.search 결과 형식 {"ok", "mock", "source", "count", "candidates", "notes", "error", "seconds"}"""
    started = time.time()
    try:
        res = _runner.run(card)
        return {"ok": True, "mock": False, "source": "추천 엔진(실거래 DB)", "error": None, **res,
                "seconds": round(time.time() - started, 3)}
    except Exception as e:  # 접속 실패·시간 초과·엔진 오류 → 챗봇은 '답이 오지 않았다'고 알린다
        msg = str(e).replace(_env("SALGU_DB_PASSWORD") or "\0", "***")[:200]
        return {"ok": False, "mock": False, "source": "추천 엔진(실거래 DB)", "error": f"{type(e).__name__}: {msg}",
                "count": 0, "candidates": [], "notes": [], "seconds": round(time.time() - started, 3)}


def realtors(address, limit=3, max_distance_m=None):
    """확정 매물 주소 → 가까운 공인중개사(카카오 AG2 거리순 + 중개업소 DB 대조, 폐업·휴업 제외).
    → {"ok", "count", "offices", "error", "seconds"}"""
    started = time.time()
    try:
        res = _runner.realtors(address, limit, max_distance_m)
        return {"ok": True, "error": None, "count": res["count"], "offices": res["offices"],
                "seconds": round(time.time() - started, 3)}
    except Exception as e:
        msg = str(e).replace(_env("SALGU_DB_PASSWORD") or "\0", "***")[:200]
        return {"ok": False, "error": f"{type(e).__name__}: {msg}", "count": 0, "offices": [],
                "seconds": round(time.time() - started, 3)}


def warm():
    if configured():
        try:
            _runner.warm()
        except Exception:
            pass
