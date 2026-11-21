#!/usr/bin/env bash
# 살구 화면 배포: 로컬에서 빌드해 서버에 올리고 systemd 서비스(salgu-fe)로 8080에서 띄워요.
# 사용(Git Bash, FE 폴더에서): bash deploy/deploy.sh
# 서버 주소: 환경 변수 DEPLOY_HOST 또는 FE/.deploy-host 파일(Git 제외, 예: ubuntu@서버주소)
# SSH 키는 Windows OpenSSH 에이전트에 있어서 Windows 의 ssh.exe / scp.exe 를 써요.
set -euo pipefail
cd "$(dirname "$0")/.."

HOST="${DEPLOY_HOST:-$(cat .deploy-host 2>/dev/null || true)}"
[ -n "$HOST" ] || { echo "DEPLOY_HOST=user@서버 또는 .deploy-host 파일이 필요해요"; exit 1; }
OPENSSH="${WINDIR:-/c/Windows}/System32/OpenSSH"
if [ -x "$OPENSSH/ssh.exe" ]; then SSH="$OPENSSH/ssh.exe"; SCP="$OPENSSH/scp.exe"; else SSH=ssh; SCP=scp; fi
SSH="$SSH -n -o BatchMode=yes -o ConnectTimeout=10"   # -n: 입력을 기다리지 않게
SCP="$SCP -q -o BatchMode=yes -o ConnectTimeout=10"
BIN="$PWD/node_modules/.bin"
REL="$(date +%Y%m%d-%H%M%S)"

echo "▶ 검사: 타입, 린트, 단위 시험"
"$BIN/tsc" --noEmit -p tsconfig.json
"$BIN/tsc" --noEmit -p tsconfig.server.json
"$BIN/eslint" .
"$BIN/vitest" run

echo "▶ 빌드"
"$BIN/vite" build
"$BIN/tsc" -p tsconfig.server.json
PKG="salgu-fe-$REL.tgz"   # Windows scp 가 읽을 수 있게 지금 폴더에 만들어요
tar -czf "$PKG" dist package.json package-lock.json

echo "▶ 서버 확인: $HOST"
$SSH "$HOST" "node -v" >/dev/null || { echo "서버에 Node 22 이상이 필요해요"; exit 1; }
if $SSH "$HOST" "systemctl is-active --quiet zipsa"; then
  if [ "${STOP_OLD:-}" = "1" ]; then
    echo "▶ 기존 zipsa(옛 살구) 서비스를 멈추고 자동 시작을 꺼요"
    $SSH "$HOST" "sudo -n systemctl disable --now zipsa"
  else
    echo "기존 zipsa 서비스가 8080을 쓰고 있어요. 내린 뒤 다시 하거나 STOP_OLD=1 bash deploy/deploy.sh 로 실행해 주세요."
    exit 1
  fi
fi

echo "▶ 올리기: ~/salgu-fe/releases/$REL"
$SSH "$HOST" "mkdir -p ~/salgu-fe/releases/$REL ~/salgu-fe/data && chmod 700 ~/salgu-fe/data"
$SCP "$PKG" "$HOST:~/salgu-fe/releases/$REL/app.tgz"
$SSH "$HOST" "cd ~/salgu-fe/releases/$REL && tar -xzf app.tgz && rm app.tgz && npm ci --omit=dev --no-audit --no-fund --loglevel=error"

echo "▶ 설정 파일(처음 한 번만 만들고, 있으면 그대로 둬요)"
$SCP deploy/salgu-fe.env.example "$HOST:~/salgu-fe/salgu-fe.env.example"
$SSH "$HOST" 'cd ~/salgu-fe && [ -f salgu-fe.env ] || { sed "s#__HOME__#$HOME#g" salgu-fe.env.example > salgu-fe.env && chmod 600 salgu-fe.env; }'

echo "▶ 서비스 등록·전환"
$SCP deploy/salgu-fe.service "$HOST:~/salgu-fe/salgu-fe.service"
$SSH "$HOST" 'sed -e "s#__HOME__#$HOME#g" -e "s#__USER__#$(whoami)#g" ~/salgu-fe/salgu-fe.service | sudo -n tee /etc/systemd/system/salgu-fe.service >/dev/null && sudo -n systemctl daemon-reload'
$SSH "$HOST" "ln -sfn ~/salgu-fe/releases/$REL ~/salgu-fe/current && sudo -n systemctl enable --now salgu-fe && sudo -n systemctl restart salgu-fe"

echo "▶ 확인"
sleep 2
$SSH "$HOST" "curl -fsS http://127.0.0.1:8080/api/health"
echo
echo "▶ 오래된 배포 정리(최근 5개만 남김)"
$SSH "$HOST" 'cd ~/salgu-fe/releases && ls -1 | sort | head -n -5 | xargs -r rm -rf'
rm -f "$PKG"
echo "배포 끝: $REL"
