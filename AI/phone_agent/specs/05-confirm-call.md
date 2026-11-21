# C5. 확정 통화와 방문 상태 (기본)

## 목적

사용자가 방과 시각을 고르고 승인하면, 그 사무소에 다시 전화해 방문을 확정합니다. 중개사 확인과 사용자 승인이 모두 끝난 것만 `confirmed`입니다(기획서 ⑤).

## 입출력

- `POST /api/visit-confirmations`, `GET /api/visit-confirmations/{id}`: [io.md](../contracts/io.md) 2절
- 요청: `approval_id`, `visits[]{call_id(문의 통화), listing_index, at, alternatives[], place}`

## 접수 규칙

1. 모든 `call_id`가 **끝난 문의 통화**이고 `outcome`이 `listing`, 그 방(`listing_index`)이 있어야 함. 아니면 요청 전체 `409 call_not_found`/`listing_not_found`
2. **확정 시각 안전장치**: `at`이 그 문의 통화의 `broker_slots`(끝 시각 포함, 시각 하나면 그 시각만) 밖이면 전화를 걸지 않고 `409 outside_broker_slots`(`detail`에 슬롯). 이후 확정 통화에서 중개사가 직접 제안한 시각은 허용. 판단 근거가 모자라면(슬롯 없음, 시간 미확인, `availability_note`만 있음) 막지 않음
3. 같은 사무소의 방 여러 개(최대 3개)는 **확정 통화 한 통**으로 묶음
4. 확정 통화는 하루 1번·10통 제한에 넣지 않고, 문의 통화 하나당 하루 2통(`PHONE_AGENT_CONFIRM_LIMIT`)

## 통화 (지시문)

- 첫마디: `"안녕하세요, {상호}이죠? {아까/어제/11월 20일에} 방 문의드렸던 AI 비서 살구입니다. 손님이 그 방을 보러 가고 싶어 하셔서 다시 전화드렸어요. 잠시 괜찮으실까요?"`
- 방 확인: **"그 방 아직 있죠?" 한 마디**(호수를 모르면 "호수가 몇 호예요?"까지). 건물·층·가격을 다시 확인하지 않음
- 요청 시각 → 안 되면 `alternatives` 범위 안에서만 맞춤 → 범위 밖 제안은 받아 적고 "본인께 확인하고 다시 연락드리겠습니다"(확정 안 함)
- 확정되면 **실제 날짜를 채운 완성 문장**을 그대로 말하고 끊음: "네, 11월 21일 토요일 오후 2시에 한빛공인중개사 사무소에서 뵙겠습니다. 계약과 가격 이야기는 방문 때 본인이 직접 하실 거예요. 감사합니다."

## 결과

| 방별 `outcome` | `rooms[].visit_status` |
|---|---|
| (통화 전·중) | `requesting` — 화면 '요청 중' |
| `confirmed`(요청 시각 또는 대안 범위 안, 날짜·시각을 중개사 말에서 확인. 시각 없이 "당연하죠"면 바로 앞 AI 질문의 시각) | `confirmed` |
| `alternative`(범위 밖 제안, `proposal`) | `needs_approval` |
| `no_time`, `unavailable`, `unclear`, `no_answer`, `declined` | `not_scheduled` |

전체 `outcome`: 모두 확정 `confirmed`, 일부 `partial`(`partially_confirmed`), 확정 없음은 제안 > 시간 안 맞음 > 나감 > 그 밖 순. 방이 하나면 `rooms[0]`의 값이 바깥에도 그대로(예전 형식 호환).

## 완료 조건

- 테스트: `test_service.py`의 `test_confirm_*`, `test_two_rooms_*`, `test_policy_slots.py`, `test_extract.py`의 `test_confirmed_*`, `test_confirm_*`, `test_accepted_time_needs_a_plain_yes`
- 실제 통화: `.venv/bin/python -m phone_agent.trial run --agent live --label c5 --confirm --ignore-hours` → 문의 뒤 확정 전화, 완성 문장 되읽기, 결과 `confirmed`

## 커밋

`AI: 전화 에이전트 확정 통화 — 방문 상태와 확정 시각 안전장치`

## 함정

- [lessons.md](lessons.md) L8("당연하죠"), L11(되읽기는 완성 문장), L13(중개사가 안 된다고 한 시각으로 전화), L14(날짜 잘못 말함)
