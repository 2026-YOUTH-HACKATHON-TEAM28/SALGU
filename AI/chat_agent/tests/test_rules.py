"""규칙 파서 시험. LLM·네트워크 없이 돈다."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from salgu_chat import rules  # noqa: E402


def vals(text):
    """(parse 결과, {키: label 또는 value})."""
    r = rules.parse(text)
    return r, {k: c.get("label", c["value"]) for k, c in r["card"]["conditions"].items()}


class RulesTest(unittest.TestCase):
    def test_basic(self):
        r, v = vals("회사 강남역이고 1000/50 정도로 깨끗한 오피스텔 찾아줘. 환승은 싫어")
        self.assertTrue(r["complete"])
        self.assertEqual((v["deposit_manwon"], v["monthly_rent_manwon"]), (1000, 50))
        self.assertEqual(v["workplace"], "강남역")
        self.assertEqual(v["housing_types"], ["officetel"])
        self.assertEqual(v["max_transfers"], 0)

    def test_money_units(self):
        self.assertEqual(rules.money("1억 5천"), 15000)
        self.assertEqual(rules.money("2천"), 2000)
        self.assertEqual(rules.money("1,000"), 1000)
        _, v = vals("회사가 판교인데 보증금 1억 5천, 월세 30 이하")
        self.assertEqual((v["deposit_manwon"], v["monthly_rent_manwon"], v["workplace"]), (15000, 30, "판교"))

    def test_place_before_company(self):
        _, v = vals("여의도 회사 다니는데 보증금 2000에 월세 60 이하 빌라 찾아줘")
        self.assertEqual(v["workplace"], "여의도")
        self.assertEqual(v["housing_types"], ["villa"])

    def test_dahnyeoyo(self):
        _, v = vals("삼성전자 서초사옥 다녀요 보증금 2천 월세 70 통근 40분 이내 조용한 곳")
        self.assertEqual(v["workplace"], "삼성전자 서초사옥")
        self.assertEqual((v["deposit_manwon"], v["monthly_rent_manwon"], v["max_commute_min"]), (2000, 70, 40))
        r, v = vals("회사 다녀요 1000/50")
        self.assertNotIn("workplace", v)
        r, _ = vals("삼성전자 서초사옥 다녀요 보증금 2천 월세 70 통근 40분 이내 조용한 곳")
        self.assertTrue(r["complete"])

    def test_needs_llm(self):
        self.assertFalse(rules.parse("강남역 말고 선릉역 근처에 살고 싶어 1000/50")["complete"])
        self.assertFalse(rules.parse("여의도 쪽 조용한 오피스텔 찾아줘")["complete"])

    def test_intent(self):
        self.assertEqual(rules.parse("확정일자가 뭐예요?")["intent"], "question")
        self.assertEqual(rules.parse("오늘 점심 뭐 먹지?")["intent"], "other")

    def test_ask_missing(self):
        card = rules.ask_missing(rules.parse("1000/50 오피스텔 찾아줘")["card"])
        self.assertEqual(card["clarifications"][0]["id"], "workplace")


if __name__ == "__main__":
    unittest.main()
