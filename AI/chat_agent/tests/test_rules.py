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

    def test_question_words_only(self):
        for t in ("반전세가 뭐예요", "확정일자 뭐임", "전세사기 어떻게 피해?", "오피스텔이랑 빌라 차이가 뭐야"):
            with self.subTest(text=t):
                self.assertEqual(rules.parse(t)["intent"], "question")
        r = rules.parse("보증금 1000이면 월세 얼마가 적당해?")
        self.assertEqual((r["intent"], r["asked"]), ("search", True))

    def test_outside_seoul(self):
        card = rules.parse("분당 쪽 전세 2억")["card"]
        self.assertEqual(card["unverifiable"][0]["message"], rules.OUTSIDE_MESSAGE)
        self.assertNotIn("preferred_areas", card["conditions"])
        # 회사 위치로는 서울 밖도 괜찮다
        card = rules.parse("회사가 판교인데 1000/50")["card"]
        self.assertEqual(card["conditions"]["workplace"]["label"], "판교")
        self.assertEqual(card["unverifiable"], [])

    def test_control(self):
        cases = {"아니 그냥 처음부터 다시": ("reset", None), "취소": ("stop", None), "됐어 안 해": ("stop", None),
                 "ㅇㅇ": ("ack", None), "좋아요!": ("ack", None), "다른 거 더 보여줘": ("more", None),
                 "2번째꺼 자세히": ("pick", 2), "두 번째 집 어때": ("pick", 2), "신촌 1000/50": (None, None)}
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(rules.control(text), want)

    def test_workplace_tail(self):
        label = rules.parse("회사가 판교라서 1000/50")["card"]["conditions"]["workplace"]["label"]
        self.assertEqual(label, "판교")


if __name__ == "__main__":
    unittest.main()
