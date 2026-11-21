"""대화 한 턴(말 이해 → BE 검색 요청 → 답) 시험. Gemini·BE는 가짜로 바꿔 네트워크 없이 돈다."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from salgu_chat import config, dialog, llm  # noqa: E402


class DialogTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(llm, "generate_json", side_effect=llm.LLMError("시험: Gemini 없음"))
        p.start()
        self.addCleanup(p.stop)
        self.saved_url = config.BACKEND_SEARCH_URL
        config.BACKEND_SEARCH_URL = ""
        self.addCleanup(setattr, config, "BACKEND_SEARCH_URL", self.saved_url)

    def kinds(self, r):
        return [m["kind"] for m in r["messages"]]

    def test_not_ready_only_asks(self):
        r = dialog.turn("신촌에 원하는 매물좀 찾아줘")
        self.assertEqual(self.kinds(r), ["reply"])
        self.assertIsNone(r["backend"])

    def test_ready_requests_backend_then_answers(self):
        card = dialog.turn("신촌에 원하는 매물좀 찾아줘")["card"]
        r = dialog.turn("1000/50", card)
        self.assertEqual(self.kinds(r), ["reply", "backend_request", "backend_response", "answer"])
        self.assertIn("요청했습니다", r["messages"][1]["text"])
        self.assertIn("있다고 합니다", r["messages"][2]["text"])
        self.assertTrue(r["backend"]["mock"])
        for c in r["backend"]["candidates"]:  # 예시 응답도 조건을 넘지 않는다
            self.assertLessEqual(c["monthly_rent_manwon"], 50)
            self.assertLessEqual(c["deposit_manwon"], 1000)

    def test_no_change_no_backend_call(self):
        card = dialog.turn("신촌 1000/50")["card"]
        r = dialog.turn("고마워", card)
        self.assertIsNone(r["backend"])

    def test_avoid_replaces_previous_area(self):
        card = dialog.turn("신촌 1000/50")["card"]
        r = dialog.turn("신촌 말고 망원 쪽", card)
        c = r["card"]["conditions"]
        self.assertEqual(c["preferred_areas"]["value"], ["망원"])
        self.assertEqual(c["avoid_areas"]["value"], ["신촌"])
        self.assertTrue(r["backend"]["candidates"][0]["name"].startswith("망원"))

    def test_backend_failure_is_reported(self):
        config.BACKEND_SEARCH_URL = "http://127.0.0.1:9/search"
        with mock.patch("urllib.request.urlopen", side_effect=ConnectionError("거절")):
            r = dialog.turn("신촌 1000/50")
        self.assertFalse(r["backend"]["ok"])
        self.assertIn("답이 오지 않았다고 합니다", r["messages"][2]["text"])


if __name__ == "__main__":
    unittest.main()
