"""세션 캐시 시험. 임시 폴더에 쓰고 Gemini는 가짜로 바꾼다."""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from salgu_chat import config, dialog, llm, session_cache  # noqa: E402


class SessionCacheTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for target, value in ((session_cache, ("CACHE_DIR", Path(tmp.name))), (config, ("BACKEND_SEARCH_URL", ""))):
            p = mock.patch.object(target, value[0], value[1])
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(llm, "generate_json", side_effect=llm.LLMError("시험: Gemini 없음"))
        p.start()
        self.addCleanup(p.stop)
        session_cache._mem.clear()
        self.addCleanup(session_cache._mem.clear)

    def talk(self, sid, *messages):
        for m in messages:
            cache = session_cache.get_or_new(sid)
            r = dialog.turn(m, cache["card"], session_id=sid)
            session_cache.add_turn(cache, m, r)
        return session_cache.load(sid)

    def test_keywords_follow_the_conversation(self):
        cache = self.talk("s1", "신촌에 원하는 매물좀 찾아줘")
        self.assertFalse(cache["ready"])
        self.assertEqual(cache["missing"], ["deposit", "monthly_rent"])
        cache = self.talk("s1", "1000/50", "홍대는 좀?")
        self.assertTrue(cache["ready"])
        kw = session_cache.keywords("s1")
        self.assertEqual((kw["preferred_areas"], kw["avoid_areas"], kw["deposit_manwon"], kw["monthly_rent_manwon"]),
                         (["신촌"], ["홍대"], 1000, 50))
        self.assertEqual(cache["turn_count"], 3)
        self.assertTrue(cache["history"][1]["searched"])
        self.assertTrue(cache["last_search"]["mock"])

    def test_file_survives_restart(self):
        self.talk("s2", "마포 쪽 전세 2억")
        session_cache._mem.clear()  # 서버를 다시 켠 것처럼
        data = json.loads((session_cache.CACHE_DIR / "s2.json").read_text(encoding="utf-8"))
        self.assertEqual(data["keywords"]["deposit_manwon"], 20000)
        self.assertTrue(session_cache.load("s2")["ready"])

    def test_expired_cache_is_dropped(self):
        cache = self.talk("s3", "신촌 1000/50")
        cache["expires_at"] = (datetime.now().astimezone() - timedelta(minutes=1)).isoformat()
        session_cache.save(cache)
        self.assertIsNone(session_cache.load("s3"))
        self.assertFalse((session_cache.CACHE_DIR / "s3.json").exists())

    def test_bad_session_id(self):
        with self.assertRaises(ValueError):
            session_cache.load("../../etc/passwd")


if __name__ == "__main__":
    unittest.main()
