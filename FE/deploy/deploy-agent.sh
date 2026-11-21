#!/usr/bin/env bash
# 살구 대화 에이전트(팀 저장소 AI/chat_agent) 배포: 코드는 고치지 않고 그대로 올려 systemd salgu-chat(127.0.0.1:8095)로 띄워요.
# 사용(Git Bash, FE 폴더에서): bash deploy/deploy-agent.sh
# SSH 연결은 두 번만 열어요(파일 한 번에 올리기, 서버 설치 한 번). 서버 보호 장치에 걸리지 않게.
# 설정(Gemini 키 등)은 서버 ~/salgu-chat/agent.env(권한 600)에만 두고, 배포마다 current/.env 로 링크해요.
# 서버 설정에 Gemini 키가 없으면 로컬 AI/chat_agent/.env 의 GEMINI_* 줄을 옮겨요(값은 출력하지 않음).
set -euo pipefail
cd "$(dirname "$0")/.."

HOST="${DEPLOY_HOST:-$(cat .deploy-host 2>/dev/null || true)}"
[ -n "$HOST" ] || { echo "DEPLOY_HOST=user@서버 또는 .deploy-host 파일이 필요해요"; exit 1; }
SRC="../AI/chat_agent"
[ -f "$SRC/run_server.py" ] || { echo "$SRC 가 없어요. 팀 저장소 main 을 받아 주세요"; exit 1; }
OPENSSH="${WINDIR:-/c/Windows}/System32/OpenSSH"
if [ -x "$OPENSSH/ssh.exe" ]; then SSH="$OPENSSH/ssh.exe"; SCP="$OPENSSH/scp.exe"; else SSH=ssh; SCP=scp; fi
SSH="$SSH -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=20"
SCP="$SCP -q -o BatchMode=yes -o ConnectTimeout=15"
REL="$(date +%Y%m%d-%H%M%S)"
STAGE="agent-upload-$REL"

echo "▶ 묶기: AI/chat_agent (가상 환경·캐시·.env 제외)"
mkdir -p "$STAGE"
trap 'rm -rf "$STAGE"' EXIT
tar --exclude=.venv --exclude=.cache --exclude=.env --exclude=__pycache__ -czf "$STAGE/app.tgz" -C "$SRC" .
cp deploy/salgu-chat.service deploy/remote-agent.sh "$STAGE/"
if grep -qE '^GEMINI_API_KEY[A-Z0-9_]*=.+' "$SRC/.env" 2>/dev/null; then
  grep -E '^GEMINI_' "$SRC/.env" > "$STAGE/gemini.env"
fi

echo "▶ 올리기(연결 1): ~/salgu-chat/incoming"
# scp 는 폴더째 올려요. 서버의 incoming 은 매번 새로 받아요.
$SCP -r "$STAGE" "$HOST:salgu-chat-incoming-$REL"

echo "▶ 서버 설치(연결 2)"
$SSH "$HOST" "rm -rf ~/salgu-chat/incoming && mkdir -p ~/salgu-chat && mv ~/salgu-chat-incoming-$REL ~/salgu-chat/incoming && bash ~/salgu-chat/incoming/remote-agent.sh $REL" </dev/null
