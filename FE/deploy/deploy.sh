#!/usr/bin/env bash
# 살구 화면 배포: 로컬에서 검사·빌드해 서버에 올리고 systemd 서비스(salgu-fe)로 8080에서 띄워요.
# 사용(Git Bash, FE 폴더에서): bash deploy/deploy.sh
# 서버 주소: 환경 변수 DEPLOY_HOST 또는 FE/.deploy-host 파일(Git 제외, 예: ubuntu@서버주소)
# SSH 연결은 두 번만 열어요(파일 한 번에 올리기, 서버 설치 한 번). 서버 보호 장치에 걸리지 않게.
# SSH 키는 Windows OpenSSH 에이전트에 있어서 Windows 의 ssh.exe / scp.exe 를 써요.
set -euo pipefail
cd "$(dirname "$0")/.."

HOST="${DEPLOY_HOST:-$(cat .deploy-host 2>/dev/null || true)}"
[ -n "$HOST" ] || { echo "DEPLOY_HOST=user@서버 또는 .deploy-host 파일이 필요해요"; exit 1; }
OPENSSH="${WINDIR:-/c/Windows}/System32/OpenSSH"
if [ -x "$OPENSSH/ssh.exe" ]; then SSH="$OPENSSH/ssh.exe"; SCP="$OPENSSH/scp.exe"; else SSH=ssh; SCP=scp; fi
SSH="$SSH -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=20"
SCP="$SCP -q -o BatchMode=yes -o ConnectTimeout=15"
BIN="$PWD/node_modules/.bin"
REL="$(date +%Y%m%d-%H%M%S)"
STAGE="fe-upload-$REL"

echo "▶ 검사: 타입, 린트, 단위 시험"
"$BIN/tsc" --noEmit -p tsconfig.json
"$BIN/tsc" --noEmit -p tsconfig.server.json
"$BIN/eslint" .
"$BIN/vitest" run

echo "▶ 빌드"
"$BIN/vite" build
"$BIN/tsc" -p tsconfig.server.json
mkdir -p "$STAGE"
trap 'rm -rf "$STAGE"' EXIT
tar -czf "$STAGE/app.tgz" dist package.json package-lock.json
cp deploy/salgu-fe.service deploy/salgu-fe.env.example deploy/remote-fe.sh "$STAGE/"

echo "▶ 올리기(연결 1): $HOST"
$SCP -r "$STAGE" "$HOST:salgu-fe-incoming-$REL"

echo "▶ 서버 설치(연결 2)"
$SSH "$HOST" "rm -rf ~/salgu-fe/incoming && mkdir -p ~/salgu-fe && mv ~/salgu-fe-incoming-$REL ~/salgu-fe/incoming && STOP_OLD=${STOP_OLD:-0} bash ~/salgu-fe/incoming/remote-fe.sh $REL" </dev/null
