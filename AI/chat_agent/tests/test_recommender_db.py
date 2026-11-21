"""실제 실거래 DB로 추천 연동 확인 (기본은 건너뜀).

    SALGU_RUN_DB_TESTS=1 AI/chat_agent/.venv/Scripts/python -m unittest AI/chat_agent/tests/test_recommender_db.py

AI/chat_agent/.env에 SALGU_DB_* 접속 정보가 있어야 한다. DB는 읽기만 한다.
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from salgu_chat import intake, recommender  # noqa: E402

RUN = os.environ.get("SALGU_RUN_DB_TESTS") == "1" and recommender.configured()


@unittest.skipUnless(RUN, "실제 DB 시험은 SALGU_RUN_DB_TESTS=1일 때만")
class RealDatabaseTest(unittest.TestCase):
    def search(self, *messages):
        card = None
        for m in messages:
            card = intake.intake(m, card)["card"]
        res = recommender.search(card)
        self.assertTrue(res["ok"], res["error"])
        return res

    def test_neighborhood_budget_and_order(self):
        res = self.search("신촌 1000/50")
        self.assertGreater(res["count"], 0)
        for c in res["candidates"]:
            self.assertIn("서대문구", c["address"])
            self.assertLessEqual(c["deposit_manwon"], 1000)
            self.assertLessEqual(c["monthly_rent_manwon"], 50)
            self.assertFalse(c["is_live_listing"])
        scores = [c["score"] for c in res["candidates"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_exact_dong_no_substring_mixups(self):
        res = self.search("창동 빌라 전세 2억")
        for c in res["candidates"]:
            self.assertIn("도봉구 창동", c["address"])  # 염창동·평창동이 섞이지 않는다
            self.assertEqual(c["monthly_rent_manwon"], 0)

    def test_school_without_commute_provider(self):
        res = self.search("학교 근처 원룸 1000/60", "연세대")
        self.assertGreater(res["count"], 0)
        self.assertTrue(any("통학 시간" in n for n in res["notes"]))


if __name__ == "__main__":
    unittest.main()
