#!/usr/bin/env bash
# 살구 팀 서비스 묶음 배포: 대화 에이전트(AI/chat_agent + AI/property_recommendation), 전화 에이전트(AI/phone_agent), BE(BE/).
# 팀 코드는 고치지 않고 그대로 올려요. 화면 서버는 deploy.sh 로 따로 올려요.
# 사용(Git Bash, FE 폴더에서): bash deploy/deploy-stack.sh
# SSH 연결은 두 번만 열어요(파일 한 번에 올리기, 서버 설치 한 번). 서버 보호 장치에 걸리지 않게.
# 비밀값은 로컬 Git 밖 파일에서 읽어 올리고, 서버에서는 권한 600 파일로만 둬요(값은 출력하지 않음).
#   AI/chat_agent/.env 의 GEMINI_*, SALGU_DB_* 줄 -> ~/salgu-chat/agent.env
#   AI/phone_agent/.env                         -> ~/salgu-phone/phone.env
#   BE/src/main/resources/application-secret.yml -> ~/salgu-be/config/application.yml
# 일부만 올리려면 PARTS=be 처럼(chat, phone, be 중에서).
# 전화 에이전트 모드는 PHONE_MODE(기본 mock). demo 로 올리면 시연 번호로 실제 전화가 가요.
set -euo pipefail
cd "$(dirname "$0")/.."

HOST="${DEPLOY_HOST:-$(cat .deploy-host 2>/dev/null || true)}"
[ -n "$HOST" ] || { echo "DEPLOY_HOST=user@서버 또는 .deploy-host 파일이 필요해요"; exit 1; }
SITE="${SITE_URL:-https://sample.localhostbar.com/}"
PHONE_MODE="${PHONE_MODE:-mock}"
AI="../AI"
BE="../BE"
for p in "$AI/chat_agent/run_server.py" "$AI/property_recommendation/src" "$AI/phone_agent/src/phone_agent" "$BE/pom.xml"; do
  [ -e "$p" ] || { echo "$p 가 없어요. 팀 저장소를 받아 주세요"; exit 1; }
done
OPENSSH="${WINDIR:-/c/Windows}/System32/OpenSSH"
if [ -x "$OPENSSH/ssh.exe" ]; then SSH="$OPENSSH/ssh.exe"; SCP="$OPENSSH/scp.exe"; else SSH=ssh; SCP=scp; fi
SSH="$SSH -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=20"
SCP="$SCP -q -o BatchMode=yes -o ConnectTimeout=15"
REL="$(date +%Y%m%d-%H%M%S)"
STAGE="stack-upload-$REL"

echo "▶ 묶기(가상 환경·캐시·.env·빌드 결과 제외)"
mkdir -p "$STAGE/secrets"
trap 'rm -rf "$STAGE"' EXIT
EX=(--exclude=.venv --exclude=.cache --exclude=.env --exclude=__pycache__ --exclude=.pytest_cache --exclude=.data)
tar "${EX[@]}" -czf "$STAGE/chat.tgz" -C "$AI" chat_agent property_recommendation
tar "${EX[@]}" -czf "$STAGE/phone.tgz" -C "$AI" phone_agent
tar --exclude=target --exclude=application-secret.yml -czf "$STAGE/be.tgz" -C "$BE" .
cp deploy/salgu-py.service deploy/salgu-be.service deploy/remote-stack.sh "$STAGE/"
grep -E '^(GEMINI_|SALGU_DB_)' "$AI/chat_agent/.env" > "$STAGE/secrets/chat.env" 2>/dev/null || true
[ -f "$AI/phone_agent/.env" ] && cp "$AI/phone_agent/.env" "$STAGE/secrets/phone.env"
[ -f "$BE/src/main/resources/application-secret.yml" ] && cp "$BE/src/main/resources/application-secret.yml" "$STAGE/secrets/be.yml"
ls "$STAGE/secrets" | sed 's/^/  비밀 파일: /'

echo "▶ 올리기(연결 1)"
$SCP -r "$STAGE" "$HOST:salgu-stack-incoming-$REL"

echo "▶ 서버 설치(연결 2)"
$SSH "$HOST" "rm -rf ~/salgu-stack-incoming && mv ~/salgu-stack-incoming-$REL ~/salgu-stack-incoming && chmod 700 ~/salgu-stack-incoming/secrets && bash ~/salgu-stack-incoming/remote-stack.sh $REL '$SITE' $PHONE_MODE '${PARTS:-chat phone be}'" </dev/null
