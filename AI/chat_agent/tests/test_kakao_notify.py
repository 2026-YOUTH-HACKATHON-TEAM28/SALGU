"""카카오톡 알림(kakao_notify.py) 시험. 카카오 API는 부르지 않고 _call을 가짜로 바꾼다."""

import json
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from salgu_chat import kakao_notify as kn  # noqa: E402


class FakeKakao:
    def __init__(self):
        self.calls = []

    def __call__(self, url, data=None, token=None):
        self.calls.append((url, data, token))
        if url == kn.TOKEN_URL and data["grant_type"] == "authorization_code":
            return {"access_token": "A1", "refresh_token": "R1", "scope": "profile_nickname talk_message"}
        if url == kn.TOKEN_URL:  # refresh: 새 refresh token도 준다
            return {"access_token": "A2", "refresh_token": "R2"}
        if url == kn.ME_URL:
            return {"id": 42, "kakao_account": {"profile": {"nickname": "살구"}}}
        if url == kn.MEMO_URL:
            if token != "A2":
                raise kn.KakaoError(401, '{"msg":"this access token does not exist","code":-401}')
            return {"result_code": 0}
        raise AssertionError(url)


class NotifyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig = (kn.STORE, kn._call)
        kn.STORE = Path(self.tmp.name) / "subscribers.json"
        self.fake = kn._call = FakeKakao()

    def tearDown(self):
        kn.STORE, kn._call = self.orig
        self.tmp.cleanup()

    def test_login_url_and_state(self):
        url = kn.login_url()
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        self.assertEqual(q["scope"], "profile_nickname,talk_message")
        self.assertEqual(q["redirect_uri"], kn.redirect_uri())
        self.assertTrue(kn.check_state(q["state"]))
        self.assertFalse(kn.check_state(q["state"]))  # 한 번만 쓴다
        self.assertFalse(kn.check_state("위조"))

    def test_login_save_and_send(self):
        tok = kn.exchange("code")
        kid, nick = kn.me(tok["access_token"])
        kn.save(kid, nick, tok)
        self.assertEqual(kn.subscribers()[0]["nickname"], "살구")
        self.assertNotIn("refresh_token", kn.subscribers()[0])  # 목록에 토큰을 내보내지 않음
        res = kn.send_all("[살구] 통화 결과가 나왔어요")
        self.assertEqual([r["ok"] for r in res], [True])
        memo = [c for c in self.fake.calls if c[0] == kn.MEMO_URL][0]
        tpl = json.loads(memo[1]["template_object"])
        self.assertEqual((tpl["object_type"], tpl["text"]), ("text", "[살구] 통화 결과가 나왔어요"))
        # 카카오가 새 refresh token을 주면 바꿔 저장
        self.assertEqual(json.loads(kn.STORE.read_text(encoding="utf-8"))["42"]["refresh_token"], "R2")

    def test_long_text_is_cut(self):
        self.assertEqual(len(kn.template("가" * 500)["text"]), kn.TEXT_MAX)

    def test_errors_are_explained(self):
        self.assertIn("talk_message", kn.explain(kn.KakaoError(403, '{"msg":"...","code": -402}')))
        self.assertIn("리다이렉트 URI", kn.explain(kn.KakaoError(400, '{"error_code":"KOE006"}')))
        self.assertIn("다시 로그인", kn.explain(kn.KakaoError(401, '{"code":-401}')))
        self.assertFalse(kn.send("999", "x")["ok"])  # 저장 안 된 사람 → 실패로 돌려줌(예외 없음)


if __name__ == "__main__":
    unittest.main()
