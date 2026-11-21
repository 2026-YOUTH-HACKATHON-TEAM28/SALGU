"""살구 채팅 API 서버 실행.

    AI/chat_agent/.venv/Scripts/python AI/chat_agent/run_server.py      (Windows)
    → http://127.0.0.1:8090 (시험용 채팅 화면), http://127.0.0.1:8090/docs (API 문서)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import uvicorn  # noqa: E402

from salgu_chat import config  # noqa: E402

if __name__ == "__main__":
    if not config.GEMINI_KEY:
        print("경고: Gemini 키가 없습니다. 규칙만으로 답합니다.")
    port = int(sys.argv[1]) if len(sys.argv) > 1 else config.API_PORT
    uvicorn.run("salgu_chat.server:app", host=config.API_HOST, port=port)
