# C1. 뼈대: 요청 형식, mock, REST, 기록 (필수)

## 목적

키 없이 돌아가는 서버를 먼저 세워서, 화면·BE가 바로 붙어 볼 수 있게 합니다. 실제 전화는 C3에서 붙입니다.

## 입출력

- 요청·응답 형식: [io.md](../contracts/io.md) 1절(문의)·2절(확정)·공통 status. 이 단계에서는 문의만 동작하면 됩니다.
- 엔드포인트: `POST /api/broker-call-batches`, `GET /api/broker-call-batches/{id}`, `GET /api/broker-calls/{id}`, `GET /api/health`
- 모듈·클래스 이름: [interfaces.md](interfaces.md)의 `config`, `schemas`, `provider`(`MockProvider`), `service`(`Store`, `CallService`), `app`

| 응답 | 모양 |
|---|---|
| `POST` 새 접수 `201` / 같은 `approval_id` `200` | 둘 다 **접수 응답**(`batch_id`, `kind`, `approval_id`, `calls[]{call_id, reg, status, scheduled_at?, error?, message?}`). 묶음 전체가 아님 |
| `GET` 묶음 | 묶음 결과. 묶음 `status`는 통화가 하나라도 진행 중이면 **`running`**, 모두 끝나면 `done` |
| 없는 ID | `404 {"error": "not_found"}` |
| `GET /api/health` | `{ok: true, mode, notify("kakao"|"sms"|"log"), mcp(bool), registry_inbox(bool)}` |

## 규칙

1. 요청 검사(pydantic): `approval_id` 1~80자, `search.housing_type`은 `officetel`|`villa`, 금액 0 이상, `brokers` 1~10곳·등록번호 중복 금지, `visit_windows` 최대 6개·`end > start`, `prep.surname` 최대 2자. 틀리면 `422 {"error":"invalid_request","detail":[{field,message}]}`이고 통화를 하나도 만들지 않음
2. 문의 묶음은 사무소마다 통화 한 건으로 나눔. **배열 순서 = 전화 순서**
3. 같은 `approval_id`로 다시 오면 새로 만들지 않고 기존 묶음을 `200`으로 돌려줌(버튼 두 번 누름 방지). 새로 만들면 `201`
4. 상태는 웹훅 없이 진행: 조회(GET)와 5초마다 도는 백그라운드 작업이 공급사 상태를 읽어 옴
5. mock 공급사(`MockProvider`): 전화를 걸지 않고 [assets/mock_scenarios.json](assets/mock_scenarios.json)의 대화록과 추출 값을 돌려줌. 공급사 조회 한 번에 한 단계(`queued → ringing → in_progress → in_progress → ended`). 요청 헤더 `X-Mock-Scenario: listing,registry`처럼 사무소 순서대로 시나리오 지정(mock 모드에서만). 빈 자리나 모르는 값은 등록번호로 정해지는 기본 시나리오. 문의 시나리오: `listing`, `two_rooms`, `registry`, `no_listing`, `no_answer`, `voicemail`, `declined`
6. 결과 만들기: 통화가 끝나면 `analyzing` → 대화록과 추출 값으로 결과. C1에서는 mock의 `canned_extraction` 값을 결과에 그대로 옮겨도 되고, 근거 줄 대조(`decide`)는 C4에서 끼움
7. 거는 줄은 C1에서 **한 번에 한 통, 접수 순서대로**만. 하루 제한·영업시간·재발신은 C2에서 `policy.py`와 줄에 더함
8. 기록: 메모리 + JSON 파일(`.data/calls.json`). mock은 파일에 남기지 않음
9. CORS: `PHONE_AGENT_CORS_ORIGINS`(기본 `*`), 메서드 GET·POST·DELETE
10. 응답의 묶음 `version`은 `0.3.1`

## 그대로 가져갈 자료

- [assets/pyproject.toml](assets/pyproject.toml) → `AI/phone_agent/pyproject.toml`
- [assets/request.example.json](assets/request.example.json) → `tests/fixtures/`(방문 날짜는 당일 이후로)
- [assets/mock_scenarios.json](assets/mock_scenarios.json)(mock 대화록·추출 값), [assets/messages.json](assets/messages.json)(오류 문구)

## 완료 조건

- `uvicorn phone_agent.app:app --port 8090` → `GET /api/health`가 `{"ok":true,"mode":"mock",…}`
- 예시 요청을 POST → GET을 반복하면 묶음 `status`가 `done`, 통화마다 `outcome`과 `listings`
- 테스트: `test_service.py`의 `test_inquiry_flow`, `test_same_approval_does_not_dial_twice`, `test_http_api`, `test_policy.py::test_request_shape`

## 커밋

`AI: 전화 에이전트 뼈대 — 요청 형식, mock 공급사, 문의 REST`

## 함정

- [lessons.md](lessons.md) L1(형식은 io.md 하나만 기준), L9(mock에서도 하루 1번 규칙)
