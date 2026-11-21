"""여러 말투를 제대로 이해하는지 보는 시험 문장 모음.

규칙 파서가 지켜야 할 약속:
1. 읽은 값은 틀리지 않는다 (기대값과 다르면 실패).
2. 기대값에 None인 칸은 만들지 않는다 (예: 살 곳을 회사로 착각하지 않기).
3. 기대한 칸을 하나라도 못 읽었으면 covered가 False여야 한다 → Gemini가 이어서 이해한다.
4. fast=True인 문장은 규칙만으로 다 읽어야 한다 (Gemini 없이 바로 답하는 흔한 말).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from salgu_chat import rules  # noqa: E402

OT, VI = "officetel", "villa"

# (사용자 말, {칸: 기대값 또는 None(만들면 안 됨)}, fast)
CASES = [
    # 기본 흐름
    ("회사 강남역이고 1000/50 정도로 깨끗한 오피스텔 찾아줘. 환승은 싫어",
     {"workplace": "강남역", "deposit_manwon": 1000, "monthly_rent_manwon": 50, "housing_types": [OT],
      "max_transfers": 0, "max_building_age_years": 10}, True),
    ("회사가 판교인데 보증금 1억 5천, 월세 30 이하", {"workplace": "판교", "deposit_manwon": 15000, "monthly_rent_manwon": 30}, True),
    ("여의도 회사 다니는데 보증금 2000에 월세 60 이하 빌라 찾아줘",
     {"workplace": "여의도", "deposit_manwon": 2000, "monthly_rent_manwon": 60, "housing_types": [VI]}, True),
    ("삼성전자 서초사옥 다녀요 보증금 2천 월세 70 통근 40분 이내 조용한 곳",
     {"workplace": "삼성전자 서초사옥", "deposit_manwon": 2000, "monthly_rent_manwon": 70, "max_commute_min": 40}, True),
    ("1000/50 오피스텔 찾아줘", {"deposit_manwon": 1000, "monthly_rent_manwon": 50, "housing_types": [OT], "workplace": None}, True),
    ("싼 집 찾아줘", {"price_band": "median_or_below"}, True),

    # 금액 말투
    ("보증금 천에 월세 오십 정도요", {"deposit_manwon": 1000, "monthly_rent_manwon": 50}, True),
    ("월 50 이하 보증금 500", {"deposit_manwon": 500, "monthly_rent_manwon": 50}, True),
    ("보증금 500만원 월세 45만원", {"deposit_manwon": 500, "monthly_rent_manwon": 45, "lease_types": ["monthly"]}, True),
    ("보증금 이천에 월세 육십", {"deposit_manwon": 2000, "monthly_rent_manwon": 60}, True),
    ("보증금이 천이고 월세는 사십오", {"deposit_manwon": 1000, "monthly_rent_manwon": 45}, True),
    ("1000에 50 오피스텔", {"deposit_manwon": 1000, "monthly_rent_manwon": 50, "housing_types": [OT]}, True),
    ("보증금 1억5000만원 월세 20", {"deposit_manwon": 15000, "monthly_rent_manwon": 20}, True),
    ("매월 40 정도 낼 수 있어요 보증금 300", {"deposit_manwon": 300, "monthly_rent_manwon": 40}, None),
    ("5월에 이사하는데 보증금 1000", {"deposit_manwon": 1000, "monthly_rent_manwon": None}, None),
    ("ㅂㅈㄱ 1000 ㅇㅅ 50", {"deposit_manwon": 1000, "monthly_rent_manwon": 50}, False),

    # 전세·반전세
    ("전세 2억 이하로 구해요", {"lease_types": ["jeonse"], "deposit_manwon": 20000, "monthly_rent_manwon": None}, True),
    ("전세금 1억 5천까지 빌라", {"lease_types": ["jeonse"], "deposit_manwon": 15000, "housing_types": [VI]}, True),
    ("반전세 5천에 30", {"lease_types": ["semi_jeonse"], "deposit_manwon": 5000, "monthly_rent_manwon": 30}, True),
    ("전세나 월세 둘 다 괜찮아요", {"lease_types": ["monthly", "jeonse"]}, None),
    ("전세대출 되는 집", {"lease_types": None}, False),

    # 살 곳 vs 회사
    ("홍대입구역 근처 원룸 1000에 50",
     {"preferred_areas": ["홍대입구역"], "workplace": None, "deposit_manwon": 1000, "monthly_rent_manwon": 50}, True),
    ("강남역 1000/50", {"workplace": None, "preferred_areas": ["강남역"], "deposit_manwon": 1000}, True),
    ("여자친구랑 같이 살 집 강남역 1000/50", {"workplace": None, "deposit_manwon": 1000}, False),
    ("회사 판교고 마포 근처 살고싶음 ㅎㅎ", {"workplace": "판교", "preferred_areas": ["마포"]}, False),
    ("학교가 고대라서 안암동 쪽 자취방", {"workplace": "고대", "preferred_areas": ["안암동"]}, None),
    ("회사가 강남역 근처예요 1000/50", {"workplace": "강남역", "preferred_areas": None}, None),
    ("마포구쪽 오피스텔 보증금 1000", {"preferred_areas": ["마포구"], "housing_types": [OT], "workplace": None}, True),
    ("강남역 말고 선릉역 근처에 살고 싶어 1000/50", {"avoid_areas": ["강남역"], "preferred_areas": ["선릉역"]}, False),
    ("망원이나 합정 쪽 원룸", {"preferred_areas": ["망원", "합정"]}, True),
    ("신촌이랑 홍대는 별로", {"avoid_areas": ["신촌", "홍대"]}, True),
    ("좀 더 싸면 좋겠어", {"price_band": "median_or_below"}, True),
    ("신림 말고 다른데 1000/40", {"avoid_areas": ["신림"], "deposit_manwon": 1000, "monthly_rent_manwon": 40}, False),

    # 다음 말로 고치기 (처음부터 다 묻지 않음)
    ("홍대는 좀?", {"avoid_areas": ["홍대"], "preferred_areas": None}, True),
    ("망원 쪽은 어때?", {"preferred_areas": ["망원"]}, True),
    ("1000/50도 가능해?", {"deposit_manwon": 1000}, False),
    ("홍대는 좀 별로", {"avoid_areas": ["홍대"], "preferred_areas": None}, True),
    ("신촌 쪽은 싫어요", {"avoid_areas": ["신촌"]}, True),

    # 면적·방·층
    ("10평 이상 오피스텔", {"min_area_m2": 33.1, "housing_types": [OT]}, True),
    ("20㎡ 넘는 원룸", {"min_area_m2": 20}, True),
    ("10평 이하", {"min_area_m2": None}, False),
    ("투룸 구해요 1000/60", {"min_area_m2": 33, "deposit_manwon": 1000, "monthly_rent_manwon": 60}, True),
    ("방 두 개짜리 빌라", {"min_area_m2": 33, "housing_types": [VI]}, None),
    ("반지하는 싫어요", {"min_floor": 1, "avoid_areas": None}, True),
    ("1층은 별로예요 오피스텔", {"min_floor": 2, "housing_types": [OT]}, True),
    ("3층 이상이면 좋겠어", {"min_floor": 3}, True),

    # 역까지 걸어서
    ("역에서 걸어서 5분 이내", {"max_walk_to_station_min": 5, "workplace": None}, True),
    ("지하철역까지 도보 10분", {"max_walk_to_station_min": 10, "workplace": None}, True),
    ("역세권 오피스텔 1000/50", {"max_walk_to_station_min": 10, "housing_types": [OT]}, True),
    ("강남역에서 30분 이내면 좋겠어", {"max_walk_to_station_min": None}, False),

    # QA에서 나온 말들 (2026-11-21)
    ("오피스탤 보증굼 1000 월쎄 50", {"housing_types": [OT], "deposit_manwon": 1000, "monthly_rent_manwon": 50}, True),
    ("월세 50 아니 60", {"monthly_rent_manwon": 60}, False),
    ("보증금 500 아니다 1000으로 월세 40", {"deposit_manwon": 1000, "monthly_rent_manwon": 40}, False),
    ("월세 좀만 더 올려도 돼 60까지", {"monthly_rent_manwon": 60}, None),
    ("강남 서초 송파 쪽 아무데나 월세 100 보증금 1억",
     {"preferred_areas": ["강남", "서초", "송파"], "monthly_rent_manwon": 100, "deposit_manwon": 10000}, None),
    ("1000/50인데 전세로", {"lease_types": None, "deposit_manwon": 1000}, False),
    ("판교 근처 오피스텔 1000/60", {"preferred_areas": None, "housing_types": [OT]}, None),
    ("부산 해운대 1000/50", {"preferred_areas": None, "deposit_manwon": 1000}, None),
    ("전세사기 어떻게 피해?", {"lease_types": None}, False),
    ("학교 근처 원룸 50만원 이하", {"monthly_rent_manwon": 50}, None),
    ("직장 근처로 집 구해요", {"workplace": None}, None),
    ("보증금 1000에 월세 60 정도", {"deposit_manwon": 1000, "monthly_rent_manwon": 60}, True),
    ("점심 뭐 먹지 그리고 홍대 원룸 1000/50", {"preferred_areas": ["홍대"], "deposit_manwon": 1000}, False),

    # 확인 불가
    ("강아지 키울 수 있는 집", {}, False),
    ("주차 되는 오피스텔 1000/50", {"housing_types": [OT]}, True),
]


def produced(text):
    r = rules.parse(text)
    return r, {k: c.get("label", c["value"]) for k, c in r["card"]["conditions"].items()}


class UnderstandingTest(unittest.TestCase):
    def test_cases(self):
        for text, expected, fast in CASES:
            with self.subTest(text=text):
                r, got = produced(text)
                missed = []
                for key, want in expected.items():
                    if want is None:
                        self.assertNotIn(key, got, f"만들면 안 되는 칸 {key}={got.get(key)}")
                    elif key in got:
                        self.assertEqual(got[key], want, f"{key} 값이 틀림")
                    else:
                        missed.append(key)
                if missed:
                    self.assertFalse(r["covered"], f"{missed}를 못 읽었는데 covered=True")
                if fast is True:
                    self.assertEqual(missed, [], "흔한 말인데 규칙이 못 읽음")
                    self.assertTrue(r["covered"], "흔한 말인데 Gemini로 넘어감")
                if fast is False:
                    self.assertFalse(r["covered"], "애매한 말인데 Gemini를 건너뜀")


if __name__ == "__main__":
    unittest.main()
