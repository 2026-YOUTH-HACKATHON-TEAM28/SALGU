# C2. 발신 규칙과 거는 줄 (필수)

## 목적

중개사에게 폐가 되지 않게, 그리고 시연 중 전화가 겹치지 않게 언제·몇 번 걸지 코드로 지킵니다.

## 규칙

| 규칙 | 값 | 어기면 |
|---|---|---|
| 한 번에 한 통 | 회선을 쓰는 통화(`queued`·`ringing`·`in_progress`)가 있으면 다음 통화는 `waiting` | — |
| 순서 | 다시 걸 차례가 된 통화 먼저, 그다음 접수 순서 | — |
| 같은 사무소 문의 | 하루 1번(등록번호 기준). **접수할 때** 그날 나갈(나간) 통화를 셈: 거절·한 번도 못 건 통화만 빼고, 아직 기다리는 통화도 셈 | 그 통화만 `rejected` + `already_called_today` |
| 하루 문의 수 | 10통(`PHONE_AGENT_DAILY_LIMIT`) | `rejected` + `daily_limit` |
| 세는 날 | 접수한 날이 아니라 **전화가 나가는 날**. 한 번도 못 건 통화(거절·공급사 오류)는 세지 않음 | — |
| 영업시간 | 월~토 9~19시, 공휴일 제외(`PHONE_AGENT_HOLIDAYS`로 추가) | 밖이면 `scheduled` + 다음 영업 시작 시각. 기다리는 중 영업이 끝나도 다시 예약 |
| 시연용 | `PHONE_AGENT_IGNORE_HOURS=1`이면 영업시간 무시 | — |
| 방문 시간대가 이미 지남 | 사용자 시간대(`deadline`)가 모두 지났으면 걸지 않음 | **접수할 때** 이미 지났으면 `rejected`, 줄에서 기다리다 **차례가 왔을 때** 지났으면 `failed`. 둘 다 `error: window_passed` |
| 안 받음·자동응답 | `retry_minutes`(기본 30, 시연은 1~2) 뒤 **1번만** 다시. 그래도 안 되면 문자 초안(`sms_draft`)만 만들고 보내지 않음 | `outcome: no_answer` |
| 통화 사이 쉬기 | `PHONE_AGENT_CALL_GAP_SEC`초(한 번호로 시연할 때) | — |
| 공급사 조회 간격 | 같은 통화는 3초에 한 번만 공급사에 물음(화면이 1초마다 조회해도) | — |
| 공급사 오류 | 그 통화만 `failed`, 다음 통화로 넘어감 | — |
| demo 모드 | 요청의 `phone`이 아니라 `PHONE_AGENT_DEMO_TO`의 시연 번호로만. 여러 개면 묶음 안 사무소 순서대로 돌아가며, 재발신은 처음 번호, 확정은 그 문의를 받은 번호. 비었으면 요청 전체 `409 not_allowed`. **C2는 번호 고르기까지만**(mock으로 시험), 실제 발신은 C3 | — |

다음 통화는 앞 통화가 **끊기면** 바로 겁니다. 결과 추출(C4)을 기다리지 않습니다.

## 그대로 가져갈 자료

- [assets/messages.json](assets/messages.json)의 `policy_errors`, `holidays`, `business_hours`

## 완료 조건

- 테스트: `test_policy.py` 전체, `test_service.py`의 `test_one_call_at_a_time_in_order`, `test_next_call_does_not_wait_for_analysis`, `test_rejections_are_per_broker`, `test_no_answer_or_voicemail_retries_once_then_drafts_sms`, `test_outside_hours_is_scheduled_then_dialed`, `test_provider_failure_moves_on_and_does_not_use_up_the_day`, `test_polling_is_throttled`

## 커밋

`AI: 전화 에이전트 발신 규칙 — 한 통씩, 하루 제한, 영업시간, 재발신`

## 함정

- [lessons.md](lessons.md) L9(mock에서도 하루 1번), L10(재발신 30분은 시연에 너무 김)
