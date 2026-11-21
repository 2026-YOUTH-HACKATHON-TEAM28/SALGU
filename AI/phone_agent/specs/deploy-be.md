# 전화 에이전트 서버 띄우기 (BE 서버 담당용)

전화 에이전트는 BE와 **별도 프로세스**(Python FastAPI)로 띄웁니다. BE·화면·챗봇은 이 서버의 REST(`/api/...`)나 MCP(`/mcp`)를 부릅니다. 형식은 [api.md](api.md)(한 장 요약), [../contracts/io.md](../contracts/io.md)(전체), DB에 저장할 것은 [db-data.md](db-data.md)입니다.

## 1. 설치와 실행

Python 3.11 이상.

```bash
cd AI/phone_agent
uv venv .venv && uv pip install -p .venv -e ".[mcp]"      # uv가 없으면: python3 -m venv .venv && .venv/bin/pip install -e ".[mcp]"
cp .env.example .env                                      # 값 채우기(아래 2절)
.venv/bin/uvicorn phone_agent.app:app --host 0.0.0.0 --port 8090 --workers 1
```

- **`--workers 1`(프로세스 하나)로만 띄웁니다.** 한 번에 한 통씩 거는 줄과 기록이 프로세스 메모리에 있어서, 여러 개 띄우면 전화가 겹치거나 하루 제한이 깨집니다.
- 확인: `curl localhost:8090/api/health` → `{"ok":true,"mode":"mock" 또는 "demo","mcp":true,…}`
- 기록은 `AI/phone_agent/.data/calls.json`(demo 모드). 서버를 다시 띄워도 남습니다. mock 모드는 메모리에만 있습니다.

## 2. 환경 변수(.env)

변수 이름과 설명은 [.env.example](../.env.example)에 있습니다. **실제 키·번호는 리포나 채팅에 올리지 말고 kkiha에게 비밀 공유 도구로 받으세요.**

| 상황 | 꼭 필요한 값 |
|---|---|
| 화면·BE 연동 개발(전화 안 나감) | `PHONE_AGENT_MODE=mock` 하나면 됩니다. 키 없음 |
| 시연(실제 전화) | `PHONE_AGENT_MODE=demo`, `KAT_BASE_URL`·`KAT_API_KEY`·`KAT_ACCOUNT_ID`·`KAT_AGENT_ID`·`KAT_FROM_NUMBER`, `PHONE_AGENT_DEMO_TO`(전화 받을 팀원 번호), `OPENAI_API_KEY`·`PHONE_AGENT_LLM_MODEL` |
| 다른 컴퓨터의 챗봇이 `/mcp`를 부를 때 | `PHONE_AGENT_MCP_HOST=0.0.0.0` (기본은 localhost로 온 요청만) |
| 화면 주소만 API를 부르게 할 때 | `PHONE_AGENT_CORS_ORIGINS=https://화면주소` (기본 `*`) |
| 시연을 밤·일요일에 할 때 | `PHONE_AGENT_IGNORE_HOURS=1` (기본은 월~토 9~19시에만 발신) |
| 안 받을 때 재발신을 빨리 보여 줄 때 | `PHONE_AGENT_RETRY_MINUTES=2` (기본 30) |
| 녹음 | **기본은 녹음 안 함**(기획서). 대화록은 실시간 전사로 받습니다. 속도 실험 때만 `PHONE_AGENT_RECORD=1` |

## 3. 꼭 지킬 것

- **인증이 없습니다.** demo 모드 서버를 공개 주소에 그대로 열면 누구나 실제 전화를 걸 수 있습니다. 공개 주소는 mock으로만 열고, demo는 BE 서버 안에서만 부르게(방화벽·내부 주소) 해 주세요.
- demo 모드는 요청에 담긴 중개사 번호로 걸지 않고 `PHONE_AGENT_DEMO_TO`의 팀원 번호로만 겁니다.
- 녹음하지 않으므로 공급사 에이전트(`KAT_AGENT_ID`)에 **실시간 전사(liveEvents `transcript.final`)가 켜져 있어야** 결과가 나옵니다. 꺼져 있으면 대화록이 없어 결과가 `unclear`입니다(살구-live 에이전트는 11-21에 켬).
- 같은 사무소 하루 1번·하루 10통 제한이 시연에서도 걸립니다. 같은 예시로 다시 해 보려면 `approval_id`·`reg`를 바꾸거나 `.data/calls.json`을 지우세요.
- 요청 예시의 방문 날짜(`visit_windows`)가 지났으면 `window_passed`로 거절됩니다. 오늘 이후 날짜로 보내세요.

## 4. BE가 부르는 순서

```
① POST /api/broker-call-batches   (사용자가 [전화 걸기] 승인)  → batch_id
② GET  /api/broker-call-batches/{batch_id}   1~2초마다, status가 done이 될 때까지
③ POST /api/visit-confirmations   (사용자가 방·시각 승인)        → batch_id
④ GET  /api/visit-confirmations/{batch_id}   1~2초마다
```

- mock 모드에서는 헤더 `X-Mock-Scenario: listing,no_listing`처럼 사무소 순서대로 결과를 고를 수 있습니다(시나리오 목록은 [api.md](api.md)).
- 결과를 DB에 넣을 때는 `batch_id`·`call_id`를 그대로 키로 upsert하면 중복이 생기지 않습니다([db-data.md](db-data.md) 2절).
- 등기부·알림(C6)은 만들지 않았습니다. `registry_docs`·`notifications`는 빈 배열입니다.
