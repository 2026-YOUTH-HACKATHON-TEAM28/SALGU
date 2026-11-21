# C3. 문의 통화: 지시문, 고정 프롬프트, 공급사 연결 (필수)

## 목적

실제 전화가 나가게 합니다. AI는 첫마디에 AI임을 밝히고, 방·가격·관리비·입주 시기·**보여 줄 수 있는 시간**·등기부를 묻고, 약속은 잡지 않고 끊습니다.

## 구성: 프롬프트 두 층

| 층 | 어디 | 내용 |
|---|---|---|
| 고정 프롬프트 | 공급사 대시보드의 에이전트(한 번 붙여 넣음) | 역할, 말투, 통화 순서, 반드시 지킬 것. **`{{변수}}` 금지** |
| 통화별 지시문 | 발신 요청의 `CallContext.Instruction`(최대 4,000자) | `[첫마디]`, `[이번 통화: 문의 — 방문 약속은 확정하지 않음]`, 조건, `[말해도 되는 정보]`, `[말하면 안 되는 정보]` |

## 지시문 규칙 (`instruction.py`)

1. 첫마디: `"안녕하세요, {상호}이죠? 집을 구하는 분의 요청으로 전화드린 AI 비서 살구입니다. 잠시 통화 괜찮으실까요?"`
2. 찾는 방: 유형, 보증금·월세를 말로("보증금 천만 원에 월세 육십만 원"). **예산을 넘는 방도 거절하지 말고 조건을 확인**
3. 면적은 상대가 물을 때만
4. 방이 있으면: 건물·층(호수), 보증금·월세·관리비·입주 가능일
5. ~~등기부: 미리 받을 수 있는지 묻고, 된다고 하면 "지금 전화드린 이 번호로 문자 주시면 돼요". **번호를 불러 주지 않음**~~ → 11-21: C6(등기부 문자 수신) 제외로 **묻지 않음**
6. 방문 시간대가 있으면 그 안에서 보여 줄 수 있는 시간을 물음(약속은 잡지 않음). 없으면 묻지 않음
7. 마무리: "손님께 여쭤보고 보러 갈 시간 정해서 다시 연락드릴게요. 감사합니다."
8. `share`에서 체크하지 않은 정보는 **줄 자체를 넣지 않음**. 성은 "김○○ 님"처럼 성만, 연락처는 통화에서 말하지 않음
9. 두 번 걸어도 안 받았을 때의 문자 초안도 같은 규칙(`build_sms_draft`)

## 공급사 (한국AI통신 REST, `KatProvider`)

| 동작 | 호출 |
|---|---|
| 발신 | `POST /v1/accounts/{account}/calls` `{To, From, AgentId, CallContext:{Instruction}}` → `callId` |
| 상태 | `GET /calls/{id}` + `GET /calls/{id}/events`(`call.ringing`, `call.answered`, `call.completed`) |
| 전사 | `POST /calls/{id}/transcript` 요청(409면 이미 요청됨) → `GET /calls/{id}/transcript`(`status`, `segments`) |

인증은 `Authorization: Bearer {KAT_API_KEY}`. 필요한 환경 변수: `KAT_API_KEY`, `KAT_ACCOUNT_ID`, `KAT_AGENT_ID`, `KAT_FROM_NUMBER`, `PHONE_AGENT_DEMO_TO`.

## 시험 통화 도구 (`trial.py`)

서버 없이 한 번에 걸어 보는 명령줄 도구입니다. 실제 통화 확인과 속도 비교에 씁니다.

| 명령 | 동작 |
|---|---|
| `run --label <이름> [--agent base\|high\|realtime\|live\|에이전트ID] [--ignore-hours]` | demo 설정으로 `tests/fixtures/request.example.json`(= `assets/` 복사본)의 **첫 사무소 하나**에 문의 전화(번호는 시연 번호). 등록번호는 매번 `trial-<이름>-<시각>`으로 바꿔 하루 1번에 걸리지 않게, `keep_transcript`는 켬. 끝날 때까지 기다린 뒤 결과(방·가능 시간·정정 기록)와 기록표 한 줄(`timing`)을 출력 |
| `run … --confirm` | 문의에서 방이 나오면 중개사가 말한 가능 시간의 시작 시각(손님 시간대와 겹치는 것 먼저)으로 그 방 확정 전화까지 |
| `run … --confirm-at <ISO 시각>` | 그 시각으로 확정(가능 시간 밖이면 `outside_broker_slots`로 막힘) |
| `measure <callId…> [--label] [--lines]` | 끝난 통화의 전사를 받아 응답 지연 등 `timing`을 출력, `--lines`는 줄마다 "← n초 뒤 응답" |

- `--agent` 이름은 `.env`의 `KAT_AGENT_ID_<이름>`(base는 `KAT_AGENT_ID`)
- 기록은 `.data/trials.json`에 따로 남겨 서버의 하루 제한과 섞지 않음, 알림은 보내지 않음

## 그대로 가져갈 자료

- `prompts/agent_prompt.md`의 고정 프롬프트(11-18판 + 세 줄). 대시보드의 live 에이전트에 이미 올라가 있음
- 공급사 에이전트 설정: **live**(`gpt-live-1`, 목소리 `noeul`). 에이전트 ID는 `.env`의 `KAT_AGENT_ID`

## 완료 조건

- 테스트: `test_instruction.py` 전체
- 실제 통화: `.venv/bin/python -m phone_agent.trial run --agent live --label c3 --ignore-hours` → 시연 번호로 전화가 오고, 첫마디에 "AI 비서 살구", 방 조건·시간·등기부를 묻고 약속 없이 끊음

## 커밋

`AI: 전화 에이전트 문의 통화 — 통화별 지시문과 한국AI통신 발신`

## 함정

- [lessons.md](lessons.md) L2(프롬프트 크게 고치면 망가짐), L3(번호 부르기), L4(`{{변수}}`), L5(되풀이), L12(고정 프롬프트가 한 번 통화판)
