"""규칙 파서 기본 시험. LLM·네트워크 없이 돈다. 여러 말투 시험은 test_understanding.py."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from salgu_chat import rules  # noqa: E402


class RulesTest(unittest.TestCase):
    def test_money_units(self):
        cases = {"1억 5천": 15000, "2천": 2000, "1,000": 1000, "천": 1000, "오십": 50, "사십오": 45,
                 "이천": 2000, "천오백": 1500, "1억5000만원": 15000, "500만원": 500, "1.5억": 15000}
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(rules.money(text), want)

    def test_card_shape(self):
        card = rules.parse("회사 강남역이고 1000/50 정도로 깨끗한 오피스텔 찾아줘")["card"]
        self.assertEqual(card["version"], "0.2-draft")
        self.assertEqual(set(card), {"version", "utterance", "conditions", "priorities", "unverifiable", "clarifications"})
        dep = card["conditions"]["deposit_manwon"]
        self.assertEqual((dep["value"], dep["source"], dep.get("approx")), (1000, "stated", True))
        age = card["conditions"]["max_building_age_years"]
        self.assertEqual((age["source"], age["evidence"]), ("inferred", "깨끗"))
        self.assertIn("reason", age)

    def test_no_clarifications(self):
        # 처음부터 다 묻지 않는다: 회사·예산이 없어도 되묻지 않고 카드를 만든다
        r = rules.parse("오피스텔 찾아줘")
        self.assertEqual(r["intent"], "search")
        self.assertEqual(r["card"]["clarifications"], [])

    def test_intent(self):
        self.assertEqual(rules.parse("확정일자가 뭐예요?")["intent"], "question")
        self.assertEqual(rules.parse("오늘 점심 뭐 먹지?")["intent"], "other")
        self.assertEqual(rules.parse("자취방 알아보는 중")["intent"], "search")

    def test_workplace_tail(self):
        label = rules.parse("회사가 판교라서 1000/50")["card"]["conditions"]["workplace"]["label"]
        self.assertEqual(label, "판교")


if __name__ == "__main__":
    unittest.main()
