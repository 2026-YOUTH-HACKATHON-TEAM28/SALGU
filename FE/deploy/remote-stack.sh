#!/usr/bin/env bash
# 서버에서 도는 팀 서비스 설치 단계. deploy-stack.sh 가 올린 뒤 한 번의 SSH 연결로 실행해요.
# 사용: bash ~/salgu-stack-incoming/remote-stack.sh <REL> <사이트 주소> <mock|demo>
set -euo pipefail
REL="$1"
SITE="$2"
PHONE_MODE="$3"
PARTS="${4:-chat phone be}"
has() { case " $PARTS " in *" $1 "*) return 0 ;; esac; return 1; }
IN="$HOME/salgu-stack-incoming"
UID_="$(id -u)"
GID_="$(id -g)"
IMG=python:3.12-slim
DOCKER="sudo -n docker"

# 키=값 파일에 값을 넣거나 바꿔요(값은 출력하지 않음)
put_env() {
  local file="$1" key="$2" val="$3"
  touch "$file" && chmod 600 "$file"
  grep -v "^$key=" "$file" > "$file.new" || true
  printf '%s=%s\n' "$key" "$val" >> "$file.new"
  mv "$file.new" "$file" && chmod 600 "$file"
}

# 파이썬 서비스 등록: 이름, 기준 폴더, 작업 폴더, 추가 -e, 실행 명령
py_service() {
  local name="$1" base="$2" workdir="$3" envs="$4" cmd="$5"
  sed -e "s#__NAME__#$name#g" -e "s#__UID__#$UID_#g" -e "s#__GID__#$GID_#g" \
    -e "s#__ENV__#$envs#g" -e "s#__BASE__#$base#g" -e "s#__WORKDIR__#$workdir#g" -e "s#__CMD__#$cmd#g" \
    "$IN/salgu-py.service" | sudo -n tee "/etc/systemd/system/$name.service" >/dev/null
  sudo -n systemctl daemon-reload
  sudo -n systemctl enable "$name" >/dev/null 2>&1
  sudo -n systemctl restart "$name"
}

venv312() {
  local base="$1"
  shift
  $DOCKER run --rm --user "$UID_:$GID_" -e HOME=/tmp -v "$base:$base" "$IMG" sh -c \
    "[ -x $base/venv312/bin/python ] || python -m venv $base/venv312; $base/venv312/bin/python -m pip install -q --disable-pip-version-check $*"
}

wait_http() {
  local url="$1" n="${2:-30}"
  for _ in $(seq 1 "$n"); do
    if curl -fsS "$url" >/dev/null 2>&1; then return 0; fi
    sleep 2
  done
  return 1
}

$DOCKER image inspect "$IMG" >/dev/null 2>&1 || $DOCKER pull -q "$IMG"

if has chat; then
echo "▶ 대화 에이전트(AI/chat_agent + 추천 엔진)"
B="$HOME/salgu-chat"
D="$B/releases/$REL"
mkdir -p "$D" "$B/data/sessions"
chmod 700 "$B/data"
tar -xzf "$IN/chat.tgz" -C "$D"
ENVF="$B/agent.env"
touch "$ENVF" && chmod 600 "$ENVF"
sed -i 's/\r$//' "$IN/secrets/chat.env" 2>/dev/null || true
if [ -s "$IN/secrets/chat.env" ]; then
  while IFS='=' read -r k v; do [ -n "$k" ] && put_env "$ENVF" "$k" "$v"; done < "$IN/secrets/chat.env"
fi
grep -q '^SESSION_CACHE_DIR=' "$ENVF" || put_env "$ENVF" SESSION_CACHE_DIR "$B/data/sessions"
venv312 "$B" -r "$D/chat_agent/requirements.txt" "'httpx>=0.27'"  # 추천 엔진(카카오 통근)이 쓰는데 requirements 에 아직 없음
ln -sfn "$ENVF" "$D/chat_agent/.env"
ln -sfn "$D" "$B/current"
# 추천 엔진의 카카오 통근 계산은 환경 변수(KAKAO_REST_API_KEY)로 읽어서 설정 파일을 환경으로도 넘겨요.
py_service salgu-chat "$B" "$B/current/chat_agent" "--env-file $ENVF" "$B/venv312/bin/python run_server.py 8095"
wait_http http://127.0.0.1:8095/health && curl -fsS http://127.0.0.1:8095/health \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("  ", {k: d.get(k) for k in ("ok","model","gemini_key","gemini_available","backend")})' \
  || echo "  대화 에이전트가 응답하지 않아요(journalctl -u salgu-chat)"
grep -qE '^SALGU_DB_HOST=.+' "$ENVF" && echo "   추천 엔진 DB 설정 있음" || echo "   추천 엔진 DB 설정(SALGU_DB_*) 없음"

fi

if has phone; then
echo "▶ 전화 에이전트(AI/phone_agent, 모드 $PHONE_MODE)"
B="$HOME/salgu-phone"
D="$B/releases/$REL"
mkdir -p "$D" "$B/data"
chmod 700 "$B/data"
tar -xzf "$IN/phone.tgz" -C "$D"
if [ -s "$IN/secrets/phone.env" ]; then
  cp "$IN/secrets/phone.env" "$B/phone.env"
  sed -i 's/\r$//' "$B/phone.env"
fi
touch "$B/phone.env" && chmod 600 "$B/phone.env"
venv312 "$B" "'fastapi>=0.110' 'uvicorn>=0.29' 'httpx>=0.27' 'pydantic>=2.6'"
ln -sfn "$B/phone.env" "$D/phone_agent/.env"
ln -sfn "$B/data" "$D/phone_agent/.data"
ln -sfn "$D" "$B/current"
py_service salgu-phone-agent "$B" "$B/current/phone_agent" "-e PHONE_AGENT_MODE=$PHONE_MODE" \
  "$B/venv312/bin/python -m uvicorn phone_agent.app:app --app-dir src --host 127.0.0.1 --port 8090"
wait_http http://127.0.0.1:8090/api/health && echo "   $(curl -fsS http://127.0.0.1:8090/api/health)" \
  || echo "  전화 에이전트가 응답하지 않아요(journalctl -u salgu-phone-agent)"

fi

if has be; then
echo "▶ BE(Spring Boot, 로컬에서 만든 jar 실행)"
B="$HOME/salgu-be"
mkdir -p "$B/config" "$B/releases/$REL"
chmod 700 "$B/config"
[ -f "$IN/app.jar" ] || { echo "  올린 jar 가 없어요"; exit 1; }
cp "$IN/app.jar" "$B/releases/$REL/app.jar"
if [ -s "$IN/secrets/be.yml" ]; then
  cp "$IN/secrets/be.yml" "$B/config/application.yml"
fi
[ -f "$B/config/application.yml" ] && chmod 600 "$B/config/application.yml" || echo "  BE 비밀 설정이 없어요($B/config/application.yml)"
JAVA="$(readlink -f "$(command -v java)")"
ln -sfn "$B/releases/$REL" "$B/current"
sed -e "s#__HOME__#$HOME#g" -e "s#__USER__#$(whoami)#g" -e "s#__JAVA__#$JAVA#g" -e "s#__SITE__#$SITE#g" \
  "$IN/salgu-be.service" | sudo -n tee /etc/systemd/system/salgu-be.service >/dev/null
sudo -n systemctl daemon-reload
sudo -n systemctl enable salgu-be >/dev/null 2>&1
sudo -n systemctl restart salgu-be
wait_http http://127.0.0.1:8081/actuator/health 45 && echo "   $(curl -fsS http://127.0.0.1:8081/actuator/health)" \
  || { echo "  BE 가 응답하지 않아요. 마지막 기록:"; sudo -n journalctl -u salgu-be -n 30 --no-pager | grep -v -i "password\|secret" || true; }

fi

echo "▶ 화면 서버(salgu-fe)에 주소 연결"
FE_ENV="$HOME/salgu-fe/salgu-fe.env"
if [ -f "$FE_ENV" ]; then
  put_env "$FE_ENV" CHAT_AGENT_URL http://127.0.0.1:8095
  put_env "$FE_ENV" PHONE_AGENT_URL http://127.0.0.1:8090
  put_env "$FE_ENV" BE_URL http://127.0.0.1:8081
  # 화면 서버도 동네·회사 이름을 좌표로 바꿀 때 카카오 REST 키를 써요
  KK="$(grep -E '^KAKAO_REST_API_KEY=.+' "$HOME/salgu-chat/agent.env" | head -1 | cut -d= -f2-)"
  [ -n "$KK" ] && put_env "$FE_ENV" KAKAO_REST_API_KEY "$KK"
  # 시험 전화(내 번호로 먼저 받아 보기)는 전화 에이전트 demo 의 시연 번호로만 실제로 걸려요
  DT="$(grep -E '^PHONE_AGENT_DEMO_TO=.+' "$HOME/salgu-phone/phone.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d ' ')"
  [ -n "$DT" ] && put_env "$FE_ENV" PHONE_TEST_NUMBERS "$DT"
  if systemctl is-active --quiet salgu-fe; then sudo -n systemctl restart salgu-fe; fi
fi

echo "▶ 정리(최근 3개만 남김, 올린 비밀 파일 삭제)"
for d in "$HOME/salgu-chat/releases" "$HOME/salgu-phone/releases" "$HOME/salgu-be/releases"; do
  [ -d "$d" ] || continue
  (cd "$d" && ls -1 | sort | head -n -3 | xargs -r rm -rf)
done
rm -rf "$HOME/salgu-be/build"
rm -rf "$IN"
echo "팀 서비스 배포 끝: $REL"
