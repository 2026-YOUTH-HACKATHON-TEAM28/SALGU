# 전화 에이전트 API 요약 (v0.3.1)

처음 붙이는 사람(BE·화면)이 이 한 장으로 호출할 수 있게 줄인 문서입니다. 모든 필드와 규칙은 [인풋·아웃풋](../contracts/io.md), DB에 무엇을 저장할지는 [DB 데이터](db-data.md)에 있습니다.

- REST(JSON). 금액은 만원, 시각은 한국 시간 ISO 문자열(`2026-11-21T14:00:00+09:00`)
- 인증 없음. 공개 주소에서는 mock 모드로만 띄웁니다(실제 전화 안 나감).

## 흐름

```
① POST 문의 묶음 ──▶ batch_id
② GET 문의 묶음 (1~2초마다, status가 done일 때까지)  → 사무소별 방·가격·가능 시간
   (화면: 사용자가 방과 시각을 고르고 승인)
③ POST 확정 묶음 ──▶ batch_id
④ GET 확정 묶음 (1~2초마다)                          → 방별 방문 상태
```

전화는 한 통에 1~2분 걸리고 한 번에 한 통씩 겁니다. 그래서 요청과 결과 조회를 나눕니다(mock은 문의 2곳에 30초 안팎).

## 엔드포인트

| 언제 | 메서드·경로 | 응답 |
|---|---|---|
| 사용자가 [전화 걸기]를 승인했을 때 | `POST /api/broker-call-batches` | `201` 접수(같은 `approval_id`면 `200` 기존 묶음) |
| 문의 진행·결과 보기 | `GET /api/broker-call-batches/{batch_id}` | 묶음 전체 |
| 사용자가 방문 일정을 승인했을 때 | `POST /api/visit-confirmations` | `201`/`200`, 걸 수 없으면 `409` |
| 확정 진행·결과 보기 | `GET /api/visit-confirmations/{batch_id}` | 묶음 전체 |
| 통화 한 건만 보기 | `GET /api/broker-calls/{call_id}` | 통화 한 건 |
| 사용자가 등기부 PDF를 올릴 때 | `POST /api/broker-calls/{call_id}/registry-docs?listing_index=0` | `201` (본문에 PDF 그대로) — **11-21 구현에 없음(C6 제외)** |
| 등기부 첨부 받기 | `GET /api/registry-docs/{message_id}/media/{i}` | 파일 — **11-21 구현에 없음(C6 제외)** |
| 등기 정리 뒤 올린 원본 지우기 | `DELETE /api/registry-docs/{message_id}` | `204` — **11-21 구현에 없음(C6 제외)** |
| 서버 상태 | `GET /api/health` | `{ok, mode, …}` |

## ① 문의 요청 (최소)

```json
{
  "approval_id": "ap-001",
  "search": { "dong": "봉천동", "housing_type": "villa", "deposit_manwon": 1000, "monthly_rent_manwon": 60 },
  "share": { "conditions": true, "visit_time": true },
  "brokers": [
    { "reg": "11620-2019-00123", "name": "한빛공인중개사", "phone": "02-555-0123",
      "visit_windows": [{ "start": "2026-11-23T14:00:00+09:00", "end": "2026-11-23T17:00:00+09:00" }] }
  ]
}
```

- `brokers` 순서가 전화 순서입니다(최대 10곳).
- 있으면 좋은 것: `search.ref_building`(참고 건물), `search.area_m2`, `prep`(`move_in`, `term`, `pet`, `surname`), `keep_transcript`. 설명은 [DB 데이터 1절](db-data.md#1-요청을-만들-때-db에서-꺼낼-데이터-입력).
- `visit_windows`가 없으면 중개사가 되는 시간을 묻지 않아서, 확정 단계에서 시각을 검사할 근거가 없습니다.

## ② 문의 결과에서 화면이 쓰는 것

`calls[]`가 사무소 하나씩입니다.

| 필드 | 화면 |
|---|---|
| `status` | 진행 표시: `waiting`(차례 기다림) → `ringing` → `in_progress` → `analyzing` → `done`. `retry_wait`는 "안 받아서 다시 걸 예정" |
| `outcome` | `listing` 방 있음 / `no_listing` 없음 / `no_answer` 안 받음 / `declined` AI 통화 거절 / `unclear` |
| `called_at` | 확인 시각 |
| `listings[]` | 방 카드: `building`, `floor`, `unit`, `deposit_manwon`, `monthly_rent_manwon`, `maintenance_fee_manwon`, `move_in`. **모르는 값은 null** |
| `unverified[]` | null인 값의 이름 → '확인 필요'로 표시 |
| `broker_slots[]` | 중개사가 방을 보여 줄 수 있다고 한 시각 → 방문 시각 고르기 |
| `registry_docs[]` | 등기부(문자로 받음 / 사용자가 올림). 첨부는 `media` 주소 |

묶음에는 `duplicate_groups`(같은 방일 수 있는 매물)와 `notifications`(보낸 알림)가 함께 옵니다. (11-21 구현: 알림은 만들지 않아 `notifications`·`registry_docs`는 빈 배열)

## ③ 확정 요청

```json
{ "approval_id": "vs-001",
  "visits": [ { "call_id": "bc_7f3a9c", "listing_index": 0, "at": "2026-11-23T14:00:00+09:00" } ] }
```

- `call_id`는 그 방을 들은 **문의 통화**, `listing_index`는 그 통화의 몇 번째 방인지입니다.
- `at`이 중개사가 문의 때 된다고 한 시간(`broker_slots`) 밖이면 전화를 걸지 않고 `409 outside_broker_slots`입니다.
- 같은 사무소의 방 여러 개는 서버가 확정 전화 한 통으로 묶습니다.

## ④ 확정 결과에서 화면이 쓰는 것

방마다 `calls[].rooms[].visit_status`를 봅니다.

| `visit_status` | 화면 | 일정·알림 |
|---|---|---|
| `requesting` | '요청 중' | 만들지 않음 |
| `confirmed` | 확정 (`visit.at`, `visit.place`) | **이때만** 일정에 넣고 확정 알림 |
| `needs_approval` | 중개사가 다른 시각 제안(`proposal.at`) → 사용자가 승인하면 새 `approval_id`로 ③을 다시 | 만들지 않음 |
| `not_scheduled` | 시간 안 맞음·방 나감·안 받음 | 만들지 않음 |

## 오류

| 코드 | 언제 | 화면 문구 예 |
|---|---|---|
| `422 invalid_request` | 필수 값이 없거나 형식이 틀림(`detail`에 필드) | — |
| `409 call_not_found` / `listing_not_found` | 확정할 문의 통화·방이 없음 | "확정할 방을 찾을 수 없어요" |
| `409 outside_broker_slots` | 중개사가 안 된다고 한 시각 | "중개사가 말한 가능 시간 안에서 골라 주세요" |
| 통화의 `status: "rejected"` + `error` | 그 사무소만 못 걸음: `already_called_today`(같은 사무소 하루 1번), `daily_limit`(하루 10통), `window_passed`(방문 시간 지남) | "오늘 이미 문의한 곳이에요" |

## mock으로 먼저 붙여 보기

```bash
cd AI/phone_agent && python3 -m venv .venv && .venv/bin/pip install -e .
PHONE_AGENT_IGNORE_HOURS=1 .venv/bin/uvicorn phone_agent.app:app --port 8090
```

- 키 없이 뜹니다. `GET /api/health`의 `mode`가 `mock`인지 확인하세요.
- 요청 헤더 `X-Mock-Scenario`로 통화별 결과를 고를 수 있습니다(쉼표로 사무소 순서대로). 문의: `listing`, `two_rooms`, `registry`, `no_listing`, `no_answer`, `voicemail`, `declined` / 확정: `confirmed`, `shifted`, `alternative`, `no_time`, `unavailable`, `partial`, `no_answer`, `declined`.
- `PHONE_AGENT_IGNORE_HOURS=1`이 없으면 영업시간(월~토 9~19시) 밖 요청은 다음 날 9시로 예약됩니다.
- mock에서도 같은 사무소 하루 1번 규칙이 적용됩니다. 다시 시험할 때는 `approval_id`와 `reg`를 바꾸거나 서버를 다시 띄우세요.
