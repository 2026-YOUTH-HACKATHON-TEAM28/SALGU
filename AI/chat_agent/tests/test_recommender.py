"""매물 추천 엔진 연동 시험. 실제 엔진(AI/property_recommendation)을 쓰고 DB만 가짜로 바꾼다.

엔진 의존성(pydantic, sqlalchemy)이 없으면 건너뛴다 → AI/chat_agent/.venv의 파이썬으로 돌린다.
"""

import asyncio
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from salgu_chat import dialog, intake, recommender  # noqa: E402

try:
    pr = recommender._engine_modules()
    from property_recommendation.models import PropertyCandidate
except ImportError:  # 엔진 의존성이 없는 파이썬
    pr = None


def candidate(region, name, rent=45, deposit=1000, row=7):
    return PropertyCandidate(
        source_table="officetel_rentals", source_row=row, housing_type="officetel",
        region_address=region, lot_address="1-1", building_name=name, rent_type="월세",
        deposit_manwon=deposit, monthly_rent_manwon=rent, area_m2=23.1, floor=4, construction_year=2021,
        contract_date=date(2026, 10, 15), median_deposit_manwon=1000, median_monthly_rent_manwon=47,
        transaction_count=8, area_bucket_m2=20)


class FakeRepository:
    """엔진의 PropertyRepository 자리. 받은 조건을 기록하고, 서대문구 전체로 찾을 때만 결과를 준다."""

    def __init__(self, hit_word="서대문구"):
        self.calls = []
        self.hit_word = hit_word

    async def find_regions(self, criteria, start_date, end_date):
        return ["서울특별시 서대문구"]

    async def find_candidates(self, criteria, start_date, end_date, pool_size, per_region_limit, allowed_regions=None):
        self.calls.append(criteria)
        if self.hit_word in criteria.preferred_areas or not criteria.preferred_areas:
            return [candidate("서울특별시 서대문구", "살구오피스텔"), candidate("서울특별시 서대문구", "자두빌", rent=40, row=8)]
        return []


@unittest.skipIf(pr is None, "추천 엔진 의존성이 없어 건너뜀 (.venv 파이썬으로 실행)")
class RecommenderTest(unittest.TestCase):
    def run_engine(self, text, repo=None):
        repo = repo or FakeRepository()
        card = intake.intake(text)["card"]
        return asyncio.run(recommender.recommend_async(card, repo)), repo

    def test_area_labels_become_dong_then_gu(self):
        res, repo = self.run_engine("신촌 1000/50 오피스텔")
        self.assertEqual(repo.calls[0].preferred_areas, ["서대문구 창천동", "서대문구 대현동", "서대문구 신촌동"])  # 먼저 동으로
        self.assertEqual(repo.calls[1].preferred_areas, ["서대문구"])  # 없으면 구 전체로
        self.assertEqual(res["count"], 2)
        self.assertIn("서대문구 전체에서", res["notes"][0])

    def test_numbers_come_from_engine(self):
        res, _ = self.run_engine("신촌 1000/50 정도 오피스텔")
        top = res["candidates"][0]
        self.assertEqual((top["deposit_manwon"], top["is_live_listing"]), (1000, False))
        self.assertTrue(top["reasons"])
        self.assertTrue(any("10%" in n for n in res["notes"]))  # '정도' → 엔진이 상한 +10%

    def test_workplace_without_commute_provider(self):
        # 엔진은 통근 계산기 없이 workplace가 오면 오류 → 통근 조건을 빼고, 회사가 있는 구에서 찾는다
        res, repo = self.run_engine("회사 강남역이고 1000/50, 출퇴근 30분 이내", FakeRepository(hit_word="강남구"))
        crit = repo.calls[-1]
        self.assertIsNone(crit.workplace)
        self.assertIsNone(crit.max_commute_min)
        self.assertEqual(crit.preferred_areas, ["강남구"])
        self.assertTrue(any("통근 시간" in n for n in res["notes"]))

    def test_walk_and_headway_limits_without_workplace(self):
        # 엔진은 workplace 없이 역 도보·배차 조건이 오면 ValueError → 빼고 알린다
        # 두 조건을 카드에 직접 넣는다(문장 해석이 Gemini 유무에 따라 달라지지 않게)
        card = intake.intake("신촌 1000/50")["card"]
        card["conditions"]["max_walk_to_station_min"] = {"value": 10, "source": "stated"}
        card["conditions"]["max_bus_headway_min"] = {"value": 10, "source": "stated"}
        repo = FakeRepository()
        res = asyncio.run(recommender.recommend_async(card, repo))
        self.assertIsNone(repo.calls[-1].max_walk_to_station_min)
        self.assertIsNone(repo.calls[-1].max_bus_headway_min)
        self.assertEqual(res["count"], 2)
        self.assertTrue(any("역까지 걷는 시간·버스 배차 조건" in n for n in res["notes"]))

    def test_avoid_neighborhood_not_whole_gu(self):
        stages, _ = recommender.plan(intake.intake("마포구 1000/50 홍대는 빼고")["card"])
        conds = stages[0][0]["conditions"]
        self.assertEqual(conds["avoid_areas"]["value"], ["마포구 서교동", "마포구 동교동", "마포구 합정동", "마포구 연남동"])
        self.assertEqual(conds["preferred_areas"]["value"], ["마포구"])

    def test_jeonse_card(self):
        res, repo = self.run_engine("서대문구 전세 2억")
        self.assertEqual([t.value for t in repo.calls[0].lease_types], ["jeonse"])
        self.assertIsNone(repo.calls[0].monthly_rent_manwon)

    def test_answer_mentions_past_transactions(self):
        res, _ = self.run_engine("신촌 1000/50")
        res.update(ok=True, mock=False)
        text = dialog.answer(res)
        # 순서는 엔진 점수 그대로: 월세가 더 싼 '자두빌'이 1순위
        self.assertEqual(res["candidates"][0]["name"], "자두빌")
        self.assertGreater(res["candidates"][0]["score"], res["candidates"][1]["score"])
        self.assertIn("'자두빌'", text)
        self.assertIn("과거 실거래 기준", text)
        self.assertIn("2026년 10월 계약", text)


@unittest.skipIf(pr is None, "추천 엔진 의존성이 없어 건너뜀 (.venv 파이썬으로 실행)")
class OutputTest(unittest.TestCase):
    def test_lot_only_name_and_school_wording(self):
        class Repo(FakeRepository):
            async def find_candidates(self, criteria, *a, **k):
                c = candidate("서울특별시 서대문구 창천동", None)
                return [c.model_copy(update={"building_name": None, "lot_address": "4-121"})]
        card = intake.intake("학교 근처 원룸 1000/50")["card"]
        card = intake.intake("연세대", card)["card"]
        res = asyncio.run(recommender.recommend_async(card, Repo()))
        self.assertEqual(res["candidates"][0]["name"], "창천동 4-121")
        self.assertTrue(any("통학 시간" in n for n in res["notes"]))


class AreaTest(unittest.TestCase):
    def test_resolve(self):
        self.assertEqual(recommender.resolve_area("홍대입구역"),
                         (["마포구 서교동", "마포구 동교동", "마포구 합정동", "마포구 연남동"], "마포구"))
        self.assertEqual(recommender.resolve_area("창동")[0], ["도봉구 창동"])  # 염창동·평창동이 섞이지 않게
        self.assertEqual(recommender.resolve_area("강남"), (["강남구"], "강남구"))
        self.assertEqual(recommender.resolve_area("강남역")[1], "강남구")
        self.assertEqual(recommender.resolve_area("마포구"), (["마포구"], "마포구"))
        self.assertEqual(recommender.resolve_area("역삼동"), (["역삼동"], None))


if __name__ == "__main__":
    unittest.main()
