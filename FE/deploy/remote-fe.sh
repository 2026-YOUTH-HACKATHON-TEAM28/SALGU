#!/usr/bin/env bash
# 서버에서 도는 화면 서버 설치 단계. deploy.sh 가 올린 뒤 한 번의 SSH 연결로 실행해요.
# 사용: STOP_OLD=0|1 bash ~/salgu-fe/incoming/remote-fe.sh <REL>
set -euo pipefail
REL="$1"
BASE="$HOME/salgu-fe"
IN="$BASE/incoming"
DEST="$BASE/releases/$REL"

node -v >/dev/null 2>&1 || { echo "서버에 Node 22 이상이 필요해요"; exit 1; }
if systemctl is-active --quiet zipsa; then
  if [ "${STOP_OLD:-0}" = "1" ]; then
    echo "▶ 기존 zipsa(옛 살구) 서비스를 멈추고 자동 시작을 꺼요"
    sudo -n systemctl disable --now zipsa
  else
    echo "기존 zipsa 서비스가 8080을 쓰고 있어요. STOP_OLD=1 로 다시 실행해 주세요."
    exit 1
  fi
fi

echo "▶ 풀기와 의존성"
mkdir -p "$DEST" "$BASE/data"
chmod 700 "$BASE/data"
tar -xzf "$IN/app.tgz" -C "$DEST"
(cd "$DEST" && npm ci --omit=dev --no-audit --no-fund --loglevel=error)

echo "▶ 설정 파일(처음 한 번만 만들고, 있으면 그대로)"
if [ ! -f "$BASE/salgu-fe.env" ]; then
  sed "s#__HOME__#$HOME#g" "$IN/salgu-fe.env.example" > "$BASE/salgu-fe.env"
  chmod 600 "$BASE/salgu-fe.env"
fi

echo "▶ 서비스 등록·전환"
sed -e "s#__HOME__#$HOME#g" -e "s#__USER__#$(whoami)#g" "$IN/salgu-fe.service" \
  | sudo -n tee /etc/systemd/system/salgu-fe.service >/dev/null
sudo -n systemctl daemon-reload
ln -sfn "$DEST" "$BASE/current"
sudo -n systemctl enable salgu-fe >/dev/null 2>&1
sudo -n systemctl restart salgu-fe

echo "▶ 확인"
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS http://127.0.0.1:8080/api/health; then echo; break; fi
  sleep 1
done
curl -fsS http://127.0.0.1:8080/api/ai && echo

echo "▶ 오래된 배포 정리(최근 5개만 남김)"
cd "$BASE/releases" && ls -1 | sort | head -n -5 | xargs -r rm -rf
rm -f "$IN/app.tgz"
echo "배포 끝: $REL"
