"""교통 지표(transit.py), 주소 → 좌표(geocode.py), 추천 결과에 붙이기(recommender.apply_transit) 시험.

DB·외부 API 없이 가짜 행과 가짜 지오코더로 돈다.
"""

import asyncio
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from salgu_chat import dialog, geocode, intake, recommender, transit  # noqa: E402

# 신촌역 근처 실제 좌표 근사값
SINCHON = (126.9368, 37.5552)


def route(name, headway, kind="지선", lo=None, hi=None):
    return {"route_name": name, "route_type": kind, "headway": headway, "min_headway": lo or headway,
            "max_headway": hi or headway, "first_time": "05:00", "last_time": "23:30"}


def make_index():
    lon, lat = SINCHON
    return transit.TransitIndex.from_rows(
        [route("서대문03", 5, "마을", 4, 7), route("7016", 12), route("273", 9, "간선")],
        [
            {"node_id": "1", "stop_name": "신촌오거리", "lon": lon + 0.001, "lat": lat, "routes": ["7016", "서대문03"]},
            {"node_id": "2", "stop_name": "연세로", "lon": lon, "lat": lat + 0.002, "routes": ["273", "심야A21"]},
            {"node_id": "3", "stop_name": "먼정류소", "lon": lon + 0.02, "lat": lat, "routes": ["273"]},
        ],
        [  # '신촌역'이 이름에 든 정류소 세 곳 + 멀리 떨어진 동명 정류소 하나(버려야 함) + 다른 역
            {"stop_name": "신촌역", "lon": lon + 0.003, "lat": lat},
            {"stop_name": "신촌역.신촌오거리", "lon": lon + 0.0032, "lat": lat + 0.0002},
            {"stop_name": "지하철2호선신촌역", "lon": lon + 0.0031, "lat": lat - 0.0001},
            {"stop_name": "신촌역(경의선)", "lon": lon + 0.15, "lat": lat},
            {"stop_name": "이대신촌역사거리", "lon": lon + 0.0001, "lat": lat},  # '신촌'으로 보지 않음
        ],
        [{"station_name": "신촌", "lines": ["02호선"]}],
        [{"station_name": "신촌", "first_s": 19950, "last_s": 89880}],
    )


class IndexTest(unittest.TestCase):
    def test_near_picks_most_frequent_route_and_nearest_station(self):
        m = make_index().near(*SINCHON)
        bus = m["bus"]
        self.assertEqual((bus["route"], bus["headway_min"], bus["headway_range"]), ("서대문03", 5, [4, 7]))
        self.assertEqual(bus["stop"], "신촌오거리")
        self.assertEqual(bus["stops_nearby"], 2)  # 먼정류소(약 1.8km)는 반경 밖
        self.assertEqual(bus["routes_nearby"], 3)  # 심야A21은 노선 표에 없어 빠짐
        self.assertEqual(bus["frequent_routes"], ["서대문03", "273"])
        st = m["station"]
        self.assertEqual((st["name"], st["lines"], st["last"]), ("신촌역", ["02호선"], "00:58"))
        self.assertLess(st["distance_m"], 320)  # 멀리 떨어진 동명 정류소는 역 위치 계산에서 빠짐
        self.assertEqual(st["walk_min"], transit.walk_min(st["distance_m"]))

    def test_station_from_geocode_cache(self):
        # 정류소 이름으로 위치를 못 찾은 역(망원)은 지오코딩 캐시 좌표를 쓴다. 노선 표에 없는 이름은 무시
        lon, lat = 126.9104, 37.5560
        idx = transit.TransitIndex.from_rows([], [], [], [{"station_name": "망원", "lines": ["06호선"]}], [],
                                             {"망원": (lon, lat), "없는역": (lon, lat)})
        self.assertEqual([s["name"] for s in idx.stations], ["망원"])
        self.assertEqual(idx.near(lon + 0.001, lat)["station"]["name"], "망원역")

    def test_nothing_nearby(self):
        self.assertEqual(make_index().near(127.10, 37.60), {"bus": None, "station": None})

    def test_station_names_in_stop(self):
        known = {"신촌", "구로", "남구로", "홍대입구", "역삼"}
        self.assertEqual(transit.station_names_in("경의선숲길공원(홍대입구역3번출구)", known), ["홍대입구"])
        self.assertEqual(transit.station_names_in("남구로역", known), ["남구로"])
        self.assertEqual(transit.station_names_in("역삼역.포스코사거리", known), ["역삼"])
        self.assertEqual(transit.station_names_in("이대신촌역사거리", known), [])
        self.assertEqual(transit.station_names_in("신촌오거리", known), [])

    def test_helpers(self):
        self.assertEqual(transit.clock(89580), "00:53")
        self.assertEqual(transit.clock(19020), "05:17")
        self.assertEqual(transit.walk_min(0), 1)
        self.assertEqual(transit.walk_min(400), 7)  # 400m × 1.3 ÷ 75m/분
        self.assertAlmostEqual(transit.distance_m(126.9368, 37.5552, 126.9368, 37.5652), 1112, delta=5)

    def test_passes_and_describe(self):
        m = make_index().near(*SINCHON)
        self.assertTrue(transit.passes(m, max_bus_headway_min=5))
        self.assertFalse(transit.passes(m, max_bus_headway_min=4))
        self.assertFalse(transit.passes(m, max_walk_to_station_min=1))
        self.assertIsNone(transit.passes(None, max_bus_headway_min=10))  # 모르면 거르지 않음
        self.assertFalse(transit.passes({"bus": None, "station": None}, max_bus_headway_min=10))
        self.assertTrue(transit.describe(m).startswith("신촌역(2호선) 걸어서 "))
        self.assertTrue(transit.describe(m).endswith("버스 서대문03 배차 5분"))


class GeocoderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = Path(self.tmp.name) / "coords.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_cache_and_not_found(self):
        calls = []

        def lookup(addr, key):
            calls.append(addr)
            return SINCHON if "창천동" in addr else None

        g = geocode.Geocoder("kakao", key="k", cache_file=self.file, lookup=lookup)
        self.assertEqual(g.locate("서울특별시  서대문구 창천동 4-121"), SINCHON)
        self.assertIsNone(g.locate("서울특별시 서대문구 없는동 1"))
        g.locate("서울특별시 서대문구 창천동 4-121")
        g.locate("서울특별시 서대문구 없는동 1")
        self.assertEqual(len(calls), 2)  # 찾은 곳도 못 찾은 곳도 다시 묻지 않음
        g.save()
        g2 = geocode.Geocoder("kakao", key="", cache_file=self.file)
        self.assertFalse(g2.can_lookup)
        self.assertEqual(g2.locate("서울특별시 서대문구 창천동 4-121"), SINCHON)  # 키 없어도 캐시는 씀

    def test_place_lookup_is_cached_separately(self):
        g = geocode.Geocoder("kakao", key="k", cache_file=self.file, lookup=lambda a, k: None)
        orig = geocode.kakao_place
        geocode.kakao_place = lambda name, key: (126.9104, 37.5560) if name == "망원역" else None
        try:
            self.assertEqual(g.locate_place("망원역"), (126.9104, 37.5560))
        finally:
            geocode.kakao_place = orig
        self.assertFalse(g.known("망원역"))  # 주소 캐시와 섞이지 않음
        self.assertEqual(g.station_coords(), {"망원": (126.9104, 37.5560)})

    def test_outside_seoul_rejected(self):
        g = geocode.Geocoder("kakao", key="k", cache_file=self.file, lookup=lambda a, k: (129.07, 35.18))
        self.assertIsNone(g.locate("부산 어딘가"))

    def test_rejected_key_stops_lookups(self):
        calls = []

        def lookup(addr, key):
            calls.append(addr)
            raise urllib.error.HTTPError("u", 403, "Forbidden", {}, None)

        g = geocode.Geocoder("kakao", key="k", cache_file=self.file, lookup=lookup)
        self.assertIsNone(g.locate("a"))
        self.assertIsNone(g.locate("b"))
        self.assertEqual(calls, ["a"])
        self.assertIn("403", g.disabled)
        self.assertFalse(g.known("a"))  # 거부는 '못 찾음'으로 캐시하지 않음


class FakeMeasurer:
    """주소에 '창천동'이 있으면 신촌역 근처, '먼동'이면 교통 불편한 곳, 그 외는 위치 모름."""

    def __init__(self, reason=None):
        self.index = make_index()
        self.reason = reason

    async def measure(self, addresses):
        out = []
        for a in addresses:
            if "창천동" in a:
                out.append(self.index.near(*SINCHON))
            elif "먼동" in a:
                out.append({"bus": {"route": "9999", "headway_min": 25, "headway_range": [20, 30]}, "station": None})
            else:
                out.append(None)
        return out


def cand(name, dong):
    return {"name": name, "address": f"서울특별시 서대문구 {dong} 1-1", "housing_type": "officetel",
            "deposit_manwon": 1000, "monthly_rent_manwon": 45, "station": None, "walk_to_station_min": None}


def limits(bus=None, walk=None):
    return {"max_bus_headway_min": bus, "max_walk_to_station_min": walk}


class ApplyTest(unittest.TestCase):
    def apply(self, cands, lim, **kw):
        return asyncio.run(recommender.apply_transit(cands, FakeMeasurer(kw.pop("reason", None)), lim, **kw))

    def test_annotates_without_limits(self):
        out, notes = self.apply([cand("살구", "창천동")], limits())
        self.assertEqual(notes, [])
        c = out[0]
        self.assertEqual((c["station"], c["transit"]["bus"]["route"]), ("신촌역", "서대문03"))
        text = dialog.describe(c)
        self.assertIn("신촌역까지 걸어서", text)
        self.assertIn("버스 서대문03 배차 5분", text)

    def test_filters_failed_keeps_unknown(self):
        out, notes = self.apply([cand("먼집", "먼동"), cand("살구", "창천동"), cand("모름", "대현동")],
                                limits(bus=10), reason="kakao 키 거부(403)")
        self.assertEqual([c["name"] for c in out], ["살구", "모름"])
        self.assertIn("버스 배차 10분 이하 조건에 맞지 않는 1곳은 뺐어요.", notes)
        self.assertTrue(any("1곳은 매물 위치 정보가 아직 없어" in n for n in notes))
        self.assertFalse(any("403" in n or "키" in n for n in notes))  # 기술 사유는 사용자 말에 넣지 않음

    def test_all_fail_shows_best_with_note(self):
        out, notes = self.apply([cand("먼집", "먼동"), cand("살구", "창천동")], limits(bus=3, walk=1))
        self.assertEqual([c["name"] for c in out], ["살구", "먼집"])  # 배차 짧은 순
        self.assertIn("찾지 못해", notes[0])

    def test_priority_sorts_by_headway(self):
        out, _ = self.apply([cand("먼집", "먼동"), cand("살구", "창천동")], limits(), by_headway=True)
        self.assertEqual([c["name"] for c in out], ["살구", "먼집"])


class PlanTest(unittest.TestCase):
    def test_transit_limits_never_reach_engine(self):
        # 엔진은 workplace 없이 배차·도보 조건이 오면 오류를 낸다 → 엔진 카드에서는 빼고 이 모듈이 거른다
        card = intake.intake("신촌 1000/50 역에서 걸어서 10분 이내, 버스 배차 10분 이하")["card"]
        self.assertEqual(recommender.transit_limits(card), limits(bus=10, walk=10))
        for stage, _ in recommender.plan(card)[0]:
            self.assertNotIn("max_walk_to_station_min", stage["conditions"])
            self.assertNotIn("max_bus_headway_min", stage["conditions"])


try:
    recommender._engine_modules()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_recommender import FakeRepository
    HAS_ENGINE = True
except ImportError:
    HAS_ENGINE = False


@unittest.skipIf(not HAS_ENGINE, "추천 엔진 의존성이 없어 건너뜀 (.venv 파이썬으로 실행)")
class EngineFlowTest(unittest.TestCase):
    def test_walk_limit_without_workplace_runs(self):
        card = intake.intake("신촌 1000/50 역에서 걸어서 10분 이내")["card"]
        repo = FakeRepository()
        res = asyncio.run(recommender.recommend_async(card, repo, FakeMeasurer()))
        self.assertEqual(repo.calls[-1].limit, recommender.TRANSIT_POOL)  # 거를 몫까지 넉넉히
        self.assertIsNone(repo.calls[-1].max_walk_to_station_min)
        self.assertEqual(res["count"], 2)  # 가짜 후보 주소(서대문구 1-1)는 위치 모름 → 거르지 않고 알림
        self.assertTrue(any("위치 정보가 아직 없어" in n for n in res["notes"]))
        self.assertEqual((res["transit"]["available"], res["transit"]["located"]), (True, 0))

    def test_without_measurer_says_unchecked(self):
        card = intake.intake("신촌 1000/50 버스 자주 오는 곳")["card"]
        res = asyncio.run(recommender.recommend_async(card, FakeRepository()))
        self.assertTrue(any("확인하지 못했어요" in n for n in res["notes"]))
        self.assertEqual(res["count"], 2)


if __name__ == "__main__":
    unittest.main()
