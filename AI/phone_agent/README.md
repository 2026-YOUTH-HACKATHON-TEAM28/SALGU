# 살구 전화 에이전트 (AI 전화·방문 확정)

살구의 마지막 단계(기획서 ④·⑤)입니다. 사용자가 고른 동네의 중개사무소에 AI가 전화해 방과 조건, 중개사가 되는 시간을 확인하고, 사용자가 일정을 승인하면 다시 전화해 방문을 확정합니다. 결과와 알림(카카오톡 '나에게 보내기')을 돌려줍니다.

**지금 상태 (2026-11-20)**: API·MCP 서버가 v0.3.1(문의 → 확정 두 번 통화)로 동작하고 자동 테스트 115개가 통과합니다. 11-19~20에 실제 통화 12건을 걸어 설정을 비교했고, 기본 에이전트를 live(GPT-Live)로 정했습니다. live로 **문의 → 확정 통화를 실제로 이어 걸어** 결과가 문서 형식대로 나오는 것까지 확인했습니다(응답 1.8~2.1초). 문자·카카오 알림 실제 발송, 등기부 MMS 실제 수신은 아직 확인하지 않았고, 챗봇·화면과도 아직 연결하지 않았습니다.

## 동작 흐름

1. 사용자가 전화할 중개사무소, 전달할 정보, 방문 가능 시간대를 승인합니다.
2. 챗봇이 `POST /api/broker-call-batches`(MCP `call_brokers`)로 **문의 통화**를 요청합니다.
3. 서버가 발신 전 검사를 하고 한 번에 한 통씩 겁니다. AI가 첫마디에 AI임을 밝히고, 방의 건물·층·가격·관리비·입주 시기, **방을 보여 줄 수 있는 시간**, 등기부를 미리 받을 수 있는지 묻습니다. 약속은 잡지 않고 "손님께 여쭤보고 보러 갈 시간 정해서 다시 연락드릴게요"로 끝냅니다. 등기부는 전화를 건 살구 번호로 문자로 받습니다.
4. 서버가 대화록에서 값을 뽑고, 각 값이 **중개사가 한 말**의 어느 줄에서 나왔는지 대조합니다. 출처가 다른 매물 중 같은 방일 수 있는 것을 `duplicate_groups`로 묶습니다. 다 끝나면 요약 알림을 보냅니다.
5. 화면에서 사용자가 방과 시각을 고르고(동선 배치는 화면 몫) 승인하면, 챗봇이 `POST /api/visit-confirmations`(MCP `confirm_visits`)로 **확정 통화**를 요청합니다.
6. AI가 그 사무소에 다시 전화해 "그 방 아직 있죠?"로 방이 남았는지(호수를 모르면 호수도) 확인하고 그 시각을 확정합니다. 시각이 문의 때 중개사가 된다고 한 시간 밖이면 전화를 걸지 않습니다(`409 outside_broker_slots`). 통화 중에는 '요청 중', 중개사 확인까지 끝난 것만 `confirmed`이고 그때만 확정 알림을 보냅니다. 다른 시각을 제안받으면 '사용자 승인 필요'로 돌려줍니다.

요청·결과의 형식은 [인풋·아웃풋](contracts/io.md), 서버의 동작 규칙은 [서버 정의](contracts/call_broker.md)에 있습니다. 두 문서와 서버 코드 모두 v0.3입니다.

## 연동하는 사람이 할 일

### 챗봇 (전화 에이전트를 부르는 쪽)

- REST나 MCP(`/mcp`, 도구 `call_brokers`·`get_call_results`·`confirm_visits`) 중 편한 쪽으로 부릅니다. 어느 쪽이든 같은 규칙이 적용됩니다.
- 문의: `brokers` 배열 순서가 전화 순서입니다. 방문 가능 시간대는 사무소끼리 겹쳐도 됩니다(약속은 확정 통화에서 잡습니다).
- 확정: 사용자가 일정을 승인한 뒤에만 부릅니다. 문의 통화의 `call_id`와 방 번호, 시각을 넘깁니다. 같은 사무소의 방 여러 개는 서버가 확정 전화 한 통으로 묶습니다.

### 화면 (결과를 받는 쪽)

- 묶음 번호로 1~2초마다 조회합니다. 문의 결과의 `broker_slots`로 동선·시간을 배치하고, `duplicate_groups`로 중복 의심을 표시합니다.
- 확정 결과는 방마다 `rooms[].visit_status`(`requesting` 요청 중 / `confirmed` / `needs_approval` / `not_scheduled`)로 보여 주세요. 일정은 `confirmed`인 방만 만듭니다.
- 등기부 첨부는 `registry_docs[].media` 주소로 받습니다. 중개사가 문자로 보낸 것과 사용자가 직접 올린 PDF(`POST /api/broker-calls/{call_id}/registry-docs`)가 같은 자리에 들어오고, `source`(`sms`/`upload`)로 구분합니다.
- 전화를 걸지 않는 mock 모드로 먼저 붙여 볼 수 있습니다.

### 아직 정하지 않은 것

- 이 서버를 어디에 띄울지(지금은 `AI/phone_agent/` 안의 서버, 화면과 다른 포트)

## 실행

```bash
cd AI/phone_agent
uv venv .venv && uv pip install -p .venv -e ".[dev,mcp]"
cp .env.example .env          # mock 모드는 비워 둬도 됩니다
.venv/bin/uvicorn phone_agent.app:app --port 8090     # REST + http://localhost:8090/mcp
.venv/bin/python -m phone_agent.mcp_server            # MCP만 stdio로
.venv/bin/python -m pytest    # 테스트
```

| 모드 | 동작 |
|---|---|
| `PHONE_AGENT_MODE=mock` (기본) | 전화·문자를 보내지 않고 정해진 결과를 돌려줍니다. 키가 필요 없습니다. |
| `PHONE_AGENT_MODE=demo` | **`PHONE_AGENT_DEMO_TO`에 적은 시연 번호로만** 겁니다. 요청에 담긴 중개사 번호는 쓰지 않습니다. 번호가 하나면 모든 전화가 그 번호로, 쉼표로 둘 이상 적으면 사무소 순서대로 나눠 겁니다(재발신·확정은 처음 받은 번호로). 알림 문자는 첫 번호(또는 `PHONE_AGENT_NOTIFY_TO`)로 갑니다. 공급사 키와 `OPENAI_API_KEY`가 필요합니다. |

시험 통화와 속도 측정: `python -m phone_agent.trial run --agent <에이전트ID> --label <설정이름>`으로 시연 번호에 걸어 결과와 응답 지연을 바로 보고, `python -m phone_agent.trial measure <callId>`로 끝난 통화의 속도를 잽니다. 절차와 기록표는 [속도 실험](experiments/2026-11-20-speed.md)에 있습니다.

시연할 때: 서버는 한 번에 한 통만 거니 전화가 겹치지 않습니다. 번호가 하나뿐이면 한 사람이 1번·2번 사무소 역할을 차례로 받고, 팀원 번호를 더 적으면 사무소마다 다른 사람이 받습니다. 받지 않을 때의 재발신을 시연에서 보여 주려면 `PHONE_AGENT_RETRY_MINUTES=2`처럼 줄이세요(기본 30분). `PHONE_AGENT_CALL_GAP_SEC=15`처럼 주면 끊고 15초 쉬고 다음 전화를 겁니다. 같은 사무소 하루 1번·하루 10통 제한은 시연에서도 적용되므로, 같은 예시로 다시 해 보려면 `.data/calls.json`을 지우거나 다른 등록번호를 쓰세요.

mock 모드 예시입니다. `X-Mock-Scenario`에 쉼표로 통화별 결과를 적을 수 있습니다(문의: `listing`, `two_rooms`, `registry`, `no_listing`, `no_answer`, `voicemail`, `declined` / 확정: `confirmed`, `shifted`, `alternative`, `no_time`, `unavailable`, `partial`, `no_answer`, `declined`). 예시 파일의 방문 날짜(2026-11-21)가 지났으면 날짜를 바꿔서 보내세요.

```bash
curl -X POST localhost:8090/api/broker-call-batches -H 'Content-Type: application/json' \
  -H 'X-Mock-Scenario: listing,registry' -d @tests/fixtures/request.example.json
curl localhost:8090/api/broker-call-batches/<batch_id>   # status가 done이 될 때까지 반복
curl -X POST localhost:8090/api/visit-confirmations -H 'Content-Type: application/json' \
  -H 'X-Mock-Scenario: confirmed' \
  -d '{"approval_id":"vs-1","visits":[{"call_id":"<문의 call_id>","at":"2026-11-21T14:00:00+09:00"}]}'
curl localhost:8090/api/visit-confirmations/<batch_id>
```

## 지키는 규칙

통화에서 지키는 것(에이전트 프롬프트):

- 첫마디에 AI 비서임을 밝히고, 상대가 원하지 않으면 끊습니다.
- 사용자가 체크한 정보만 말합니다. 체크하지 않은 정보는 통화 지시문에 넣지 않습니다.
- 문의 통화에서는 약속을 확정하지 않습니다. 확정 통화에서는 승인한 시각·범위 안에서만 확정하고, 범위 밖 시간은 제안으로만 받아 옵니다.
- 계약, 가계약금, 가격 합의는 하지 않습니다.
- 사용자 예산을 넘는 방도 거절하지 않고 들은 조건을 받아 옵니다. 맞는지는 사용자가 판단합니다.

서버가 코드로 지키는 것:

- 같은 승인으로 두 번 걸지 않습니다(버튼 두 번 누름 방지).
- 한 번에 한 통만 겁니다.
- 문의는 같은 중개사무소 하루 1번, 전체 하루 10통. 확정은 문의 통화 하나당 하루 2통. 전화가 나가는 날 기준으로 셉니다.
- 영업시간(월~토 9~19시, 공휴일 제외)에만 겁니다.
- 받지 않거나 자동응답이면 30분 뒤 한 번만 다시 걸고, 그래도 안 되면 문자 초안을 만듭니다(보내지는 않습니다).
- 시연 모드에서는 요청에 담긴 중개사 번호로 걸지 않고 허용한 한 번호로만 겁니다.
- 결과의 숫자·시각·날짜는 중개사가 한 말(근거 줄)에 실제로 있을 때만 씁니다. 확인되지 않으면 비웁니다.
- 결론(방 있음, 확정 등)은 LLM이 아니라 코드가 정합니다.
- 대화 전문은 동의했을 때만 30일 보관하고, 녹음은 받지 않습니다. 등기부 문자 본문의 주민등록번호는 바로 가리고, 문자 첨부는 저장하지 않습니다. 사용자가 올린 PDF는 메모리에만 두고 사실 정리 뒤 `DELETE /api/registry-docs/{id}`로 지웁니다(안 지우면 24시간 뒤 자동 삭제).

하지 않는 일: 동네·사무소 고르기와 전화 순서 정하기(챗봇), 동선·이동 시간 점검과 일정 화면·스케줄러 반영(화면), 등기부 사실 정리와 소재지로 중복 최종 판정(등기 담당).

## 시험 통화 결과

### 2026-11-19~20: 설정 비교와 두 번 통화 (12건)

기존 / high / realtime / live 네 설정을 같은 대사로 걸어 비교했습니다. 자세한 숫자는 [속도 실험](experiments/2026-11-20-speed.md)에 있습니다.

| 확인한 것 | 결과 |
|---|---|
| 응답 지연 | 기존 2.4~3.1초 → live 1.8~2.1초. live를 기본 에이전트로 정함 |
| 문의 → 확정 두 번 통화 | live 3차에서 문의 후 확정까지 이어서 성공(확정 통화 59초) |
| 확정 되읽기 | 실제 날짜를 채운 완성 문장을 지시문에 넣은 뒤 성공 |
| 중개사가 말을 고친 값 | 고친 값만 받고, 고치기 전 값·AI가 되풀이한 값은 버림 |
| 사용자 평가(장황함, 번호 하나씩 부르기, 긴 텀) | 되풀이 금지 한 줄, 번호 안 부르기, live 교체로 반영 |

남은 문제: live가 가끔 날짜를 틀리게 말함(1건, "12월 21일"), 낯선 건물 이름 발음.

### 2026-11-18: v0.1 첫 시험 (4건)

허용 번호로 4건을 걸어 사람이 중개사 역할을 했습니다. v0.1 서버와 그때의 프롬프트로 건 통화입니다.

| 확인한 것 | 결과 |
|---|---|
| 발신, 상태 추적(신호 → 통화 → 분석 → 완료), 전사 | 동작 |
| AI와 상대 구분 | 17줄 대화에서 모두 맞음 |
| 첫마디 AI 고지 | 통과 |
| 예산(월세 60)을 넘는 방(65) 받아 적기 | 통과(프롬프트 수정 후) |
| 관리비·포함 항목 확인 | 통과 |
| 범위 밖 시간(오후 5시) 거절 | 통과 |
| 범위 안 시간(오후 4시) 확정과 장소 확인 | 통과 |
| 가격을 깎아 주겠다는 제안에 합의하지 않기 | 통과 |
| 대화록 → 결과 추출 | 보증금 1,000, 월세 65, 관리비 8, 토요일 오후 4시가 근거 줄과 함께 나오고 '예약 확정'으로 판정 |

아직 실제 통화로 확인하지 못한 것(11-20 기준):

- 이름·연락처를 물었을 때 말하지 않기
- 받지 않았을 때의 재발신과 문자 초안
- 방을 여러 건 듣고 한 확정 통화에서 함께 확정하기
- 문자·카카오 알림 실제 발송, 등기부 문자 실제 수신
- 시연 번호 여러 개로 나눠 걸기

알려진 한계: live에서도 응답이 상대 말이 끝난 뒤 약 2초 걸립니다(사람끼리는 0.2~0.5초).

## 구조

코드를 spec과 자료만으로 다시 만들 때는 [specs/00-overview.md](specs/00-overview.md)부터 봅니다(자료는 `specs/assets/`, 이름은 `specs/interfaces.md`).

| 파일 | 내용 |
|---|---|
| `contracts/io.md` | 인풋·아웃풋 형식 (v0.3) |
| `contracts/call_broker.md` | 서버 정의: API, 발신 순서, 결과를 정하는 규칙, 알림, 등기부 수신, 구현 상태 (v0.3) |
| `specs/api.md` | API 요약: 처음 붙이는 사람용 한 장 |
| `specs/db-data.md` | DB 담당용: 요청에 꺼내 줄 데이터, DB에 저장할 테이블 4개와 조회만 할 값, ERD v3과 다른 점, Postgres 초안 |
| `specs/00-overview.md` ~ `07-mcp-dedupe.md` | 기능별 spec(C1~C7): 규칙, 그대로 가져갈 자료, 완료 조건, 커밋 |
| `specs/lessons.md`, `specs/prompts.md` | 실제로 겪은 함정 목록, 해커톤 당일 프롬프트 |
| `specs/interfaces.md`, `specs/assets/` | 모듈·함수 이름과 시그니처 / 그대로 가져갈 자료(pyproject, 예시 요청, 오류 문구, mock 대화록, LLM 지시, 낱말 목록) |
| `prompts/agent_prompt.md` | 공급사 에이전트의 고정 프롬프트(문의/확정)와 통화별 지시 예시 |
| `src/phone_agent/app.py` | REST API와 `/mcp` 연결 |
| `src/phone_agent/mcp_server.py` | MCP 입구 `mcp-phone`: `call_brokers`, `get_call_results`, `confirm_visits` |
| `src/phone_agent/schemas.py` | 요청 형식(문의 묶음, 확정 묶음, 통화 한 건) |
| `src/phone_agent/service.py` | 접수, 한 통씩 거는 줄, 통화 진행, 알림, 등기부 수신(문자·사용자 업로드), 보관 기간, 결과 |
| `src/phone_agent/policy.py` | 발신 전 검사(영업시간·공휴일, 하루 제한, 확정 통화 수) |
| `src/phone_agent/instruction.py` | 요청 → 통화별 지시문(문의/확정), 문자 초안 |
| `src/phone_agent/provider.py` | 한국AI통신 호출(전화·문자)과 전화를 걸지 않는 `MockProvider` |
| `src/phone_agent/extract.py` | 대화록 → 결과. LLM이 값을 찾고, 코드가 중개사 근거 줄·날짜와 대조해 결론을 정함 |
| `src/phone_agent/dedupe.py` | 출처가 다른 매물의 중복 후보 묶기 |
| `src/phone_agent/notify.py` | 카카오톡 '나에게 보내기', 문자 대체 |
| `src/phone_agent/timing.py` | 통화 속도 측정(응답 지연, AI 발화 길이, 끊은 횟수) |
| `src/phone_agent/trial.py` | 시험 통화 도구(`run`, `measure`) |
| `experiments/2026-11-20-speed.md` | 속도·정정 실험 절차, 기준값, 기록표 |

공급사는 한국AI통신입니다(국내 070 발신·문자, REST API). 공급사 API와의 대응은 서버 정의의 '공급사 대응'에 있습니다. API 키, 발신 번호, 시연 번호, 카카오 토큰은 로컬 `.env`에만 둡니다.

## 남은 일

- [x] 서버를 v0.2 형식으로 고치기 (묶음 접수, 매물 여러 건, 등기부 답변)
- [x] v0.3: 문의/확정 두 번 통화, MCP 입구, 중복 후보, 등기부 수신, 알림, 보관 기간
- [x] 정정 감지, 통화 속도 측정, 시험 통화 도구, '빠르고 자연스럽게' 프롬프트
- [x] 고정 프롬프트 v0.3을 공급사 에이전트에 올리기, 실험용 에이전트 3개(high·realtime·live) 만들기
- [x] 속도 실험: 기존 / high / realtime / live 비교 → live로 결정(11-20)
- [x] v0.3 시험 통화(한 번호로 문의 → 확정)
- [x] 등기부 PDF 사용자 업로드를 통화에 연결, 시연 번호 여러 개로 나눠 걸기
- [ ] 문자·카카오 알림 실제 발송, 등기부 MMS 실제 수신
- [ ] 공급사 발신 번호의 녹음 끄기
- [ ] 챗봇, 화면 쪽과 연결
- [ ] 서버를 띄울 곳 정하고 배포
