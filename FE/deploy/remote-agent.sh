#!/usr/bin/env bash
# 서버에서 도는 대화 에이전트 설치 단계. deploy-agent.sh 가 올린 뒤 한 번의 SSH 연결로 실행해요.
# 사용: bash ~/salgu-chat/incoming/remote-agent.sh <REL>
set -euo pipefail
REL="$1"
BASE="$HOME/salgu-chat"
IN="$BASE/incoming"
DEST="$BASE/releases/$REL"

mkdir -p "$DEST" "$BASE/data/sessions"
chmod 700 "$BASE/data"
tar -xzf "$IN/app.tgz" -C "$DEST"
python3 -m compileall -q "$DEST/src" >/dev/null

echo "▶ 가상 환경과 의존성"
[ -x "$BASE/venv/bin/python" ] || python3 -m venv "$BASE/venv"
"$BASE/venv/bin/python" -m pip install -q --disable-pip-version-check -r "$DEST/requirements.txt"

echo "▶ 설정 파일"
ENVF="$BASE/agent.env"
if [ ! -f "$ENVF" ]; then
  printf 'GEMINI_API_KEY=\nGEMINI_MODEL=\nSESSION_CACHE_DIR=%s/data/sessions\nSESSION_TTL_HOURS=24\n' "$BASE" > "$ENVF"
  chmod 600 "$ENVF"
fi
if [ -f "$IN/gemini.env" ] && ! grep -qE '^GEMINI_API_KEY[A-Z0-9_]*=.+' "$ENVF"; then
  echo "  Gemini 키를 설정 파일에 넣어요"
  grep -vE '^GEMINI_' "$ENVF" > "$ENVF.new"
  cat "$IN/gemini.env" >> "$ENVF.new"
  mv "$ENVF.new" "$ENVF"
  chmod 600 "$ENVF"
fi
rm -f "$IN/gemini.env"
grep -qE '^GEMINI_API_KEY[A-Z0-9_]*=.+' "$ENVF" || echo "  Gemini 키가 없어 규칙으로만 답해요($ENVF 에 넣으면 돼요)"

echo "▶ 서비스 등록·전환"
ln -sfn "$ENVF" "$DEST/.env"
ln -sfn "$DEST" "$BASE/current"
sed -e "s#__HOME__#$HOME#g" -e "s#__USER__#$(whoami)#g" "$IN/salgu-chat.service" \
  | sudo -n tee /etc/systemd/system/salgu-chat.service >/dev/null
sudo -n systemctl daemon-reload
sudo -n systemctl enable salgu-chat >/dev/null 2>&1
sudo -n systemctl restart salgu-chat

echo "▶ 확인"
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS http://127.0.0.1:8095/health >/tmp/salgu-chat-health.json 2>/dev/null; then break; fi
  sleep 1
done
python3 -c 'import json; d=json.load(open("/tmp/salgu-chat-health.json")); print({k: d[k] for k in ("ok", "model", "gemini_key", "gemini_available")})'

echo "▶ 화면 서버(salgu-fe)에 에이전트 주소 연결"
FE_ENV="$HOME/salgu-fe/salgu-fe.env"
if [ -f "$FE_ENV" ]; then
  if grep -q '^CHAT_AGENT_URL=' "$FE_ENV"; then
    sed -i 's#^CHAT_AGENT_URL=.*#CHAT_AGENT_URL=http://127.0.0.1:8095#' "$FE_ENV"
  else
    printf '\nCHAT_AGENT_URL=http://127.0.0.1:8095\n' >> "$FE_ENV"
  fi
  if systemctl is-active --quiet salgu-fe; then sudo -n systemctl restart salgu-fe; fi
fi

echo "▶ 오래된 배포 정리(최근 5개만 남김)"
cd "$BASE/releases" && ls -1 | sort | head -n -5 | xargs -r rm -rf
rm -f "$IN/app.tgz"
echo "에이전트 배포 끝: $REL"
