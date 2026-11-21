"""Gemini 모델 넘어가기 시험. 네트워크 없이 urlopen을 가짜로 바꾼다."""

import io
import json
import sys
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from salgu_chat import config, llm  # noqa: E402

A = "gemini-3.1-flash-lite"
B = "gemini-3.5-flash-lite"


def ok(text="안녕"):
    """가짜 성공 응답."""
    resp = mock.MagicMock()
    resp.__enter__.return_value.read.return_value = json.dumps(
        {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    ).encode("utf-8")
    return resp


def quota(kind="PerDay", retry=None):
    """가짜 429 한도 초과."""
    details = [{"violations": [{"quotaId": f"GenerateRequests{kind}PerProjectPerModel-FreeTier"}]}]
    if retry:
        details.append({"retryDelay": retry})
    body = json.dumps({"error": {"code": 429, "details": details}}).encode("utf-8")
    return urllib.error.HTTPError("u", 429, "quota", {}, io.BytesIO(body))


def called_models(urlopen):
    return [c.args[0].full_url.split("/models/")[1].split(":")[0] for c in urlopen.call_args_list]


class FallbackTest(unittest.TestCase):
    def setUp(self):
        self.saved = (config.GEMINI_KEY, config.GEMINI_MODEL, config.GEMINI_FALLBACK_MODELS, config.GEMINI_MAX_RPM)
        config.GEMINI_KEY, config.GEMINI_MODEL, config.GEMINI_FALLBACK_MODELS, config.GEMINI_MAX_RPM = "k", A, [B], 10
        llm._sent.clear()
        llm._cool_until.clear()

    def tearDown(self):
        config.GEMINI_KEY, config.GEMINI_MODEL, config.GEMINI_FALLBACK_MODELS, config.GEMINI_MAX_RPM = self.saved
        llm._sent.clear()
        llm._cool_until.clear()

    def test_daily_quota_moves_to_next_model(self):
        with mock.patch("urllib.request.urlopen", side_effect=[quota("PerDay"), ok(), ok()]) as u:
            llm.generate_text("s", "u")
            llm.generate_text("s", "u")
        self.assertEqual(called_models(u), [A, B, B])
        self.assertEqual(llm.last_model(), B)
        self.assertGreater(llm._cool_until[A] - time.time(), 60)
        self.assertEqual(llm.status()[B], "사용 가능")

    def test_minute_quota_uses_retry_delay(self):
        with mock.patch("urllib.request.urlopen", side_effect=[quota("PerMinute", "7s"), ok()]):
            llm.generate_text("s", "u")
        self.assertAlmostEqual(llm._cool_until[A] - time.time(), 7, delta=1)

    def test_all_quota_raises(self):
        with mock.patch("urllib.request.urlopen", side_effect=[quota(), quota()]):
            with self.assertRaises(llm.LLMError):
                llm.generate_text("s", "u")
        self.assertFalse(llm.available())

    def test_timeout_does_not_fall_back(self):
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")) as u:
            with self.assertRaises(llm.LLMError):
                llm.generate_text("s", "u")
        self.assertEqual(called_models(u), [A])

    def test_overload_moves_to_next_model(self):
        busy = urllib.error.HTTPError("u", 503, "busy", {}, io.BytesIO(b'{"error": {"code": 503}}'))
        with mock.patch("urllib.request.urlopen", side_effect=[busy, ok()]) as u:
            llm.generate_text("s", "u")
        self.assertEqual(called_models(u), [A, B])
        self.assertAlmostEqual(llm._cool_until[A] - time.time(), llm.OVERLOAD_COOLDOWN_S, delta=1)

    def test_per_model_rpm_limit(self):
        config.GEMINI_MAX_RPM = 1
        with mock.patch("urllib.request.urlopen", side_effect=[ok(), ok()]) as u:
            llm.generate_text("s", "u")
            llm.generate_text("s", "u")
        self.assertEqual(called_models(u), [A, B])


if __name__ == "__main__":
    unittest.main()
