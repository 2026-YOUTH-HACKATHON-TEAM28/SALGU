"""전화 요청 초안 시험. 챗봇은 전화를 걸지 않고 초안만 만든다. DB·Gemini는 가짜로 바꾼다."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from salgu_chat import call_request, config, dialog, llm, recommender, rules, session_cache  # noqa: E402

AGENCIES = [{"reg": "92360000-0001", "name": "가나공인중개사사무소", "phone": "02-313-0001", "dong": "대현동"},
            {"reg": "92360000-0002", "name": "다라공인중개사사무소", "phone": "02-313-0002", "dong": "대현동"}]
CANDS = [{"name": "엔트라리움", "address": "서울특별시 서대문구 대현동 37-18", "housing_type": "officetel",
          "deposit_manwon": 100, "monthly_rent_manwon": 30, "area_m2": 16.07, "floor": 7},
         {"name": "대현동 4-121", "address": "서울특별시 서대문구 대현동 4-121", "housing_type": "villa",
          "deposit_manwon": 300, "monthly_rent_manwon": 40, "area_m2": 11.5, "floor": 3}]


class CallRequestTest(unittest.TestCase):
    def setUp(self):
        patches = [mock.patch.object(llm, "generate_json", side_effect=llm.LLMError("시험")),
                   mock.patch.object(recommender, "configured", return_value=False),  # 네트워크 없이
                   mock.patch.object(call_request, "find_agencies", return_value=AGENCIES)]
        started = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.found = started[2]
        self.saved = config.BACKEND_SEARCH_URL
        config.BACKEND_SEARCH_URL = ""
        self.addCleanup(setattr, config, "BACKEND_SEARCH_URL", self.saved)
        self.card = dialog.turn("신촌 1000/50")["card"]
        self.last = {"candidates": CANDS}

    def test_detects_call_words(self):
        self.assertEqual(rules.control("2번 집 보고 싶어"), ("call", 2))
        self.assertEqual(rules.control("전화해 줘"), ("call", None))
        self.assertEqual(rules.control("첫번째꺼 보러 갈래"), ("call", 1))
        self.assertEqual(rules.control("2번째꺼 자세히"), ("pick", 2))  # 자세히 보기는 전화가 아니다

    def test_draft_not_a_call(self):
        r = dialog.turn("2번 집 보고 싶어", self.card, last_search=self.last)
        a = r["action"]
        self.assertEqual((a["type"], a["status"]), ("broker_call_request", "needs_approval"))
        self.assertIsNone(r["backend"])  # 검색도 전화도 하지 않는다
        self.assertIn("승인한 뒤에만", r["reply"])
        req = a["request"]
        self.assertIsNone(req["approval_id"])  # 승인 때 BE가 채운다
        self.assertEqual(req["search"]["dong"], "대현동")
        self.assertEqual(req["search"]["ref_building"], "")  # 건물명 없는 매물은 참고 건물 없이
        self.assertEqual((req["search"]["deposit_manwon"], req["search"]["monthly_rent_manwon"]), (1000, 50))  # 사용자 예산
        self.assertEqual([b["reg"] for b in req["brokers"]], ["92360000-0001", "92360000-0002"])
        self.assertTrue(all(b["visit_windows"] == [] for b in req["brokers"]))  # 사용자가 고른다
        self.assertEqual(req["share"], {"conditions": True, "visit_time": True, "surname": False, "contact": False})
        self.assertIn("visit_windows", a["needs_user_input"])

    def test_default_is_top_candidate(self):
        a = dialog.turn("전화해 줘", self.card, last_search=self.last)["action"]
        self.assertEqual(a["listing"]["name"], "엔트라리움")
        self.assertEqual(a["request"]["search"]["ref_building"], "엔트라리움")

    def test_no_results_yet(self):
        r = dialog.turn("전화해 줘", self.card, last_search=None)
        self.assertIsNone(r["action"])
        self.assertIn("먼저", r["reply"])
        # 아직 보여 준 집이 없는데 조건을 말하면 집 찾기로
        self.assertEqual(dialog.turn("성수 원룸 보고 싶어")["intent"], "search")

    def test_no_agencies(self):
        self.found.return_value = []
        r = dialog.turn("전화해 줘", self.card, last_search=self.last)
        self.assertEqual(r["action"]["status"], "no_agencies")
        self.assertIn("불러오지 못해", r["reply"])

    def test_session_cache_keeps_pending_action(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with mock.patch.object(session_cache, "CACHE_DIR", Path(tmp.name)):
            cache = session_cache.new("s-call")
            cache["card"], cache["last_search"] = self.card, self.last
            r = dialog.turn("2번 집 보고 싶어", cache["card"], session_id="s-call", last_search=cache["last_search"])
            session_cache.add_turn(cache, "2번 집 보고 싶어", r)
            self.assertEqual(session_cache.load("s-call")["pending_action"]["type"], "broker_call_request")
            self.assertEqual(session_cache.load("s-call")["history"][-1]["action"], "broker_call_request")


class HelperTest(unittest.TestCase):
    def test_phone_and_address(self):
        self.assertEqual(call_request.normalize_phone("313-1234"), "02-313-1234")
        self.assertEqual(call_request.normalize_phone("02-3123-4567"), "02-3123-4567")
        self.assertEqual(call_request.normalize_phone(""), "")
        self.assertEqual(call_request.split_address("서울특별시 성동구 성수동1가 13-1"), ("성동구", "성수동1가"))


@unittest.skipUnless((Path(__file__).resolve().parents[2] / "phone_agent" / "src").exists(), "AI/phone_agent가 없으면 건너뜀")
class PhoneAgentSchemaTest(unittest.TestCase):
    """기하님 전화 서버의 요청 형식(BatchRequest)에 초안이 그대로 맞는지 (승인 때 BE가 채울 값만 넣어서)."""

    def test_matches_phone_agent_schema(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "phone_agent" / "src"))
        try:
            from phone_agent.schemas import BatchRequest
        except ImportError:
            self.skipTest("전화 서버 의존성이 없음")
        req = call_request.build({"conditions": {"deposit_manwon": {"value": 1000}, "monthly_rent_manwon": {"value": 50}}},
                                 CANDS[0], AGENCIES)["request"]
        req["approval_id"] = "ap-test"
        for b in req["brokers"]:
            b["visit_windows"] = [{"start": "2026-11-23T14:00:00+09:00", "end": "2026-11-23T17:00:00+09:00"}]
        self.assertEqual(len(BatchRequest.model_validate(req).calls()), 2)


if __name__ == "__main__":
    unittest.main()
