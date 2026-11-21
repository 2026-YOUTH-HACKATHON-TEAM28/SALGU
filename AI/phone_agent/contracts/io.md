# AI 전화 에이전트 인풋·아웃풋 (v0.3.1)

전화는 **두 번** 겁니다(기획서 ④·⑤와 화면 v93의 `call_broker` → `confirm_visits` 흐름).

1. **문의 통화**: 챗봇이 사무소 목록과 조건을 넘기면 한 통씩 걸어 방·가격·관리비·입주일·**중개사가 되는 시간**·등기부를 묻습니다. 약속은 잡지 않고 "손님께 여쭤보고 보러 갈 시간 정해서 다시 연락드릴게요"로 끝냅니다.
2. **확정 통화**: 사용자가 방과 방문 시각을 고르고 승인하면, 그 사무소에 다시 전화해 그 시각을 확정합니다. "그 방 아직 있죠?"로 방이 남았는지, 호수를 모르면 호수도 확인합니다.

> 서버의 동작 규칙은 [서버 정의](call_broker.md)에 있습니다. v0.2(한 번 통화로 약속까지)와는 호환되지 않습니다.

> **11-21 구현 범위**: 알림·등기부(C6)는 만들지 않았습니다. 결과의 `notifications`·`registry_docs`는 항상 빈 배열이고, 등기부 업로드·첨부·삭제 엔드포인트(`/registry-docs`)는 없습니다(404). 아래 해당 절은 계획으로 남겨 둡니다.

```
챗봇 ──문의 묶음──▶ 전화 에이전트 ──(한 통씩)──▶ 중개사무소
  ▲                     │  ◀── 등기부 문자(살구 번호) ──┘
  │                     └──결과(매물·가능 시간·중복 후보)──▶ 화면: 비교·동선·일정 고르기
  │                                                            │ 사용자 승인
  └──────────────────────────── 확정 묶음 ◀─────────────────────┘
                        └──결과(확정/제안/불가) + 카카오톡 알림
```

- 금액은 만원, 시각은 한국 시간(`2026-11-21T14:00:00+09:00`)입니다.
- 통화는 한 통에 1~2분 걸립니다. 그래서 **요청 → 묶음 번호 → 조회**로 나눕니다. 1~2초마다 조회하면 됩니다.
- 같은 기능을 MCP 도구로도 부를 수 있습니다(아래 [MCP](#mcp-mcp-phone)).

## 1. 문의 통화

`POST /api/broker-call-batches`

```json
{
  "approval_id": "ap-20261120-01",
  "search": {
    "dong": "봉천동", "ref_building": "해든빌라", "housing_type": "villa",
    "deposit_manwon": 1000, "monthly_rent_manwon": 60, "area_m2": 25
  },
  "prep": { "move_in": "12월 초", "term": "1년", "pet": false, "surname": "김" },
  "share": { "conditions": true, "visit_time": true, "surname": false, "contact": false },
  "keep_transcript": false,
  "brokers": [
    { "reg": "11620-2019-00123", "name": "한빛공인중개사", "phone": "02-555-0123",
      "visit_windows": [{ "start": "2026-11-21T14:00:00+09:00", "end": "2026-11-21T17:00:00+09:00" }] },
    { "reg": "11620-2021-00456", "name": "새봄공인중개사", "phone": "02-555-0456",
      "visit_windows": [{ "start": "2026-11-21T14:00:00+09:00", "end": "2026-11-21T17:00:00+09:00" }] }
  ]
}
```

| 필드 | 필수 | 설명 | 어디서 오는지 |
|---|---|---|---|
| `approval_id` | ○ | 사용자가 승인한 한 번. 같은 값으로 다시 보내면 새로 걸지 않습니다. | 챗봇 |
| `search.dong` | ○ | 문의할 동네 | 조건 카드 |
| `search.ref_building` | | 참고 건물. "이 건물이나 근처"라고 묻습니다. | 추천 결과 |
| `search.housing_type` | ○ | `officetel` 또는 `villa` | 조건 카드 |
| `search.deposit_manwon`, `monthly_rent_manwon` | ○ | 사용자 예산. 넘는 방도 거절하지 않고 받아 옵니다. | 조건 카드 |
| `search.area_m2` | | 전용면적. 상대가 물을 때만 말합니다. | 조건 카드 |
| `prep.move_in`, `term`, `pet`, `surname` | | 희망 입주일, 계약 기간, 반려동물, 방문자 성 | 사용자 입력 |
| `share.*` | ○ | 중개사에게 말해도 되는 것: 희망 조건, 방문 시간, 성, 연락처. `visit_time`이 `false`면 가능 시간을 묻지 않습니다. | 사용자 체크 |
| `keep_transcript` | | 대화 전문 30일 보관 동의. `false`(기본)면 근거로 쓴 줄(`quotes`)만 남깁니다. 녹음은 어느 경우에도 받지 않습니다. | 사용자 체크 |
| `brokers[]` | ○ | 전화할 사무소(최대 10곳). **배열 순서가 전화 순서**입니다. | 중개업소 DB |
| `brokers[].reg`, `name`, `phone` | ○ | 등록번호, 상호, 전화번호. 시연에서는 `phone`으로 걸지 않고 **허용한 한 번호로만** 겁니다. | 중개업소 DB |
| `brokers[].visit_windows[]` | | 사용자가 방문할 수 있는 시간대(최대 6개). 이 안에서 중개사가 되는 시간을 묻습니다. 사무소끼리 겹쳐도 됩니다(약속은 확정 통화에서). | 사용자 선택 |

### 접수 응답

```json
{
  "batch_id": "bb_3c1e77", "kind": "inquiry", "approval_id": "ap-20261120-01",
  "calls": [
    { "call_id": "bc_7f3a9c", "reg": "11620-2019-00123", "status": "queued" },
    { "call_id": "bc_81d2e0", "reg": "11620-2021-00456", "status": "waiting" }
  ]
}
```

걸 수 없는 사무소는 `status: "rejected"`와 `error`, `message`가 붙습니다(`already_called_today`, `daily_limit`, `window_passed`). 영업시간 밖이면 `status: "scheduled"`와 `scheduled_at`이 붙습니다.

같은 `approval_id`로 다시 보내면 새로 걸지 않고 `200`과 **같은 모양의 접수 응답**(현재 상태)을 돌려줍니다. 없는 묶음·통화를 조회하면 `404 {"error": "not_found"}`입니다.

### 결과

`GET /api/broker-call-batches/{batch_id}` : 묶음 전체. `GET /api/broker-calls/{call_id}` : 한 통.

```json
{
  "version": "0.3.1", "batch_id": "bb_3c1e77", "kind": "inquiry", "approval_id": "ap-20261120-01", "status": "done",
  "calls": [ { "…통화 결과…" } ],
  "duplicate_groups": [
    { "group_id": "dup1", "status": "suspected",
      "members": [ { "call_id": "bc_7f3a9c", "listing_index": 0, "broker": "한빛공인중개사" },
                   { "call_id": "bc_81d2e0", "listing_index": 0, "broker": "새봄공인중개사" } ],
      "reasons": ["같은 건물: 해든빌라", "같은 층: 3층", "보증금·월세 같음"] }
  ],
  "notifications": [ { "kind": "inquiry_done", "text": "[살구] 봉천동 중개사무소 2곳 문의가 끝났어요. …", "channel": "kakao", "status": "sent" } ]
}
```

묶음의 `status`는 통화가 하나라도 진행 중이면 `running`, 모두 끝나면 `done`입니다. `duplicate_groups`는 문의 묶음에만 있고, 확정 묶음은 `duplicate_groups` 없이 같은 모양입니다.

#### 문의 통화 결과 한 건

```json
{
  "call_id": "bc_7f3a9c", "kind": "inquiry", "batch_id": "bb_3c1e77",
  "broker": { "reg": "11620-2019-00123", "name": "한빛공인중개사" },
  "status": "done", "outcome": "listing", "called_at": "2026-11-20T10:12:04+09:00",
  "listings": [
    { "location": "해든빌라 3층", "building": "해든빌라", "floor": "3층", "unit": null,
      "area_m2": 26.4, "deposit_manwon": 1000, "monthly_rent_manwon": 65,
      "maintenance_fee_manwon": 8, "maintenance_includes": "수도·인터넷", "move_in": "다음 달 초" }
  ],
  "broker_slots": [ { "start": "2026-11-21T14:00:00+09:00", "end": "2026-11-21T15:00:00+09:00", "in_user_window": true } ],
  "availability_note": null,
  "pet_allowed": null,
  "registry_reply": "will_send",
  "registry_docs": [
    { "message_id": "MG…", "received_at": "2026-11-20T10:20:00+09:00", "type": "mms", "text": "등기부 보내드립니다.",
      "source": "sms", "listing_index": null, "media": ["/api/registry-docs/MG…/media/0"] }
  ],
  "unverified": ["listings[0].area_m2"],
  "corrections": [ { "field": "listings[0].maintenance_fee_manwon", "value": 7, "reason": "corrected_value", "line": 5 },
                   { "field": "listings[0].maintenance_fee_manwon", "dropped": 5, "reason": "corrected", "line": 4 } ],
  "evidence": { "listings[0].monthly_rent_manwon": 3, "broker_slots[0]": 9 },
  "quotes": { "3": { "speaker": "broker", "text": "하나 있어요. 해든빌라 3층이고 천에 육십오예요.", "start": 21.4, "end": 25.9 } },
  "transcript": [],
  "sms_draft": null,
  "timing": { "response_median": 0.9, "response_p90": 1.4, "response_max": 1.6, "response_gaps": [0.8, 0.9, 1.6],
              "ai_turn_avg": 2.8, "ai_turn_max": 4.1, "ai_cut_ins": 0, "broker_barge_ins": 1, "call_seconds": 74.2 },
  "attempts": 1, "scheduled_at": null, "retry_at": null, "ended_at": "…", "error": null
}
```

| 필드 | 설명 |
|---|---|
| `outcome` | `listing`(방 있음) · `no_listing` · `no_answer` · `declined` · `unclear`. `status`가 `done`일 때만 있습니다. |
| `called_at` | 전화한 시각. 화면의 '확인 시각' |
| `listings[]` | 중개사가 말한 방. 듣지 못했거나 근거 줄에서 확인되지 않은 값은 `null`이며 요청 값으로 채우지 않습니다. `building`·`floor`·`unit`은 중복 확인에 씁니다. |
| `broker_slots[]` | 중개사가 방을 보여 줄 수 있다고 한 시각(시·분과 날짜를 대화에서 확인한 것만). `end`는 말했을 때만. `in_user_window`는 사용자가 고른 시간대 안인지 |
| `availability_note` | 구체적 시각 없이 말한 가능 시간("평일 오후는 언제든") |
| `pet_allowed` | 반려동물 가능 여부(`true`/`false`). 중개사가 말했고 근거 줄이 있을 때만, 아니면 `null`(살구는 `prep.pet`이 `true`일 때 물어봅니다) |
| `registry_reply` | 등기부 요청에 대한 답: `will_send`, `at_visit`, `refused`, `null` |
| `registry_docs[]` | 등기부. 살구 번호로 들어온 문자·MMS(`source: "sms"`)와 사용자가 올린 PDF(`source: "upload"`, `type: "upload"`)가 함께 들어옵니다. 첨부는 `media` 주소로 받습니다. `listing_index`는 업로드할 때 방을 지정했으면 그 방(문자는 `null`). 문자 본문의 주민등록번호는 가립니다. |
| `unverified` | 확인되지 않아 비운 값의 이름. 화면에는 '확인 필요'로 |
| `corrections[]` | 중개사가 말을 고친 흔적 `{field, value 또는 dropped, reason, line}`. `corrected_value`(고친 뒤 값을 받음, `value`), `corrected`(고치기 전 값이라 버림, `dropped`), `echoed`(AI가 말한 조건을 되풀이한 값이라 버림), `hedged`(중개사도 확실하지 않아 버림). 화면에 "통화 중 바뀐 값"으로 보여 줄 수 있습니다. 전사 보정도 여기에 남습니다: `name_matched`(전사된 건물 이름을 참고 건물 이름에 맞춤, `heard`에 들린 값), `read_back`(AI가 되읽고 중개사가 "네"라고 한 입주 시기로 받음, `heard`에 들린 값). |
| `timing` | 통화 속도(초): 응답 지연 중앙값·p90·최대, AI 한 번 발화 평균·최대, AI가 끊은 횟수, 중개사가 끊은 횟수, 통화 길이. 시각이 없는 대화록(mock)이면 `null`. 확정 통화 결과에도 있습니다. |
| `evidence`, `quotes` | 값이 나온 줄 번호와 그 줄의 내용(전문 보관에 동의하지 않아도 남습니다). `quotes`의 `start`·`end`는 통화 시작부터 센 초로, 대화록에 시각이 있을 때만 붙습니다(mock에는 없음). |
| `transcript` | 대화 전문. `keep_transcript`가 `true`일 때만, 30일 동안 |
| `sms_draft` | 두 번 걸어도 받지 않았을 때의 문자 초안(보내지 않습니다) |

### 등기부 PDF 올리기 (기획서 ⑥)

중개사가 문자로 보내지 않았거나 사용자가 따로 받은 등기부를 화면에서 올리면, 그 문의 통화의 `registry_docs`에 붙습니다. 등기 담당은 문자로 온 것과 똑같이 `media` 주소로 받아 사실 정리를 합니다.

`POST /api/broker-calls/{call_id}/registry-docs?listing_index=0` — 본문에 PDF 파일 그대로(`Content-Type: application/pdf`), 10MB까지.

```json
{ "message_id": "up_9a1c…", "received_at": "2026-11-20T11:02:00+09:00", "type": "upload", "text": "",
  "source": "upload", "listing_index": 0, "media": ["/api/registry-docs/up_9a1c…/media/0"] }
```

- 오류: 통화 없음 `404 call_not_found`, PDF 아님 `422 not_pdf`, 그 방 없음 `422 listing_not_found`, 너무 큼 `413 too_large`.
- 서버는 PDF를 읽지 않습니다. 주민등록번호 가리기와 사실 정리는 등기 담당이 합니다.
- 원본은 메모리에만 둡니다. 사실 정리를 마치면 `DELETE /api/registry-docs/{message_id}`로 지우세요(기획서: 원본 PDF는 사실 정리 후 삭제). 지우지 않으면 24시간 뒤(`PHONE_AGENT_UPLOAD_KEEP_HOURS`) 지워지고, 서버를 다시 시작해도 사라집니다. 지운 뒤에는 `media`가 빈 배열입니다.

## 2. 확정 통화

사용자가 화면에서 방과 시각을 고르고(동선·이동 시간 점검은 화면 몫) **승인한 뒤** 보냅니다.

`POST /api/visit-confirmations`

```json
{
  "approval_id": "vs-20261120-01",
  "visits": [
    { "call_id": "bc_7f3a9c", "listing_index": 0, "at": "2026-11-21T14:00:00+09:00",
      "alternatives": [{ "start": "2026-11-21T14:30:00+09:00", "end": "2026-11-21T15:00:00+09:00" }],
      "place": "" },
    { "call_id": "bc_81d2e0", "listing_index": 0, "at": "2026-11-21T15:30:00+09:00" }
  ]
}
```

| 필드 | 필수 | 설명 |
|---|---|---|
| `approval_id` | ○ | 사용자가 일정을 승인한 한 번. 같은 값이면 새로 걸지 않습니다. |
| `visits[].call_id` | ○ | 그 방을 들은 **문의 통화**. 결론이 `listing`인 통화만 됩니다. 같은 사무소의 방 여러 개를 보러 가면 같은 `call_id`를 방마다 넣습니다(최대 3개). |
| `visits[].listing_index` | | 그 통화의 `listings` 순서(기본 0). 같은 (`call_id`, `listing_index`)는 한 번만 |
| `visits[].at` | ○ | 요청할 방문 시각 |
| `visits[].alternatives[]` | | `at`이 안 될 때 맞춰도 되는 범위(최대 3개). 사용자가 미리 승인한 범위라 이 안이면 바로 확정합니다. |
| `visits[].place` | | 만날 곳. 비우면 사무소 |

서버는 `visits`를 **사무소(문의 통화)별로 묶어 사무소마다 확정 전화를 한 통** 겁니다. 같은 사무소의 방 두 개면 한 통화에서 "해든빌라는 2시, 새솔빌은 2시 반"처럼 함께 확정합니다.

접수 응답은 문의와 같은 모양이며 `kind: "confirm"`, `calls[].parent_call_id`가 붙습니다(통화 하나 = 사무소 하나). 문의 통화를 찾을 수 없으면 `409 call_not_found`, 그 방이 없으면 `409 listing_not_found`.

`at`이 그 문의 통화에서 중개사가 된다고 한 시간(`broker_slots`, 범위는 끝 시각 포함, 시각 하나면 그 시각만) 밖이면 전화를 걸지 않고 `409 outside_broker_slots`입니다. 그 뒤 확정 통화에서 중개사가 직접 제안한 시각(`proposal.at`)은 됩니다. 판단할 근거가 모자라면 막지 않습니다: `broker_slots`가 비었거나, 대조 못 한 시간(`unverified`)이 있거나, `availability_note`가 있을 때.

```json
{"error": "outside_broker_slots", "message": "중개사가 문의 통화에서 말한 가능 시간 밖이에요. 그 시간 안에서 다시 골라 주세요.",
 "detail": {"call_id": "bc_7f3a9c", "listing_index": 0, "at": "2026-11-21T14:00:00+09:00",
            "broker_slots": [{"start": "2026-11-21T09:00:00+09:00", "end": "2026-11-21T12:00:00+09:00"}]}}
```

`GET /api/visit-confirmations/{batch_id}` : 묶음 전체. 한 통은 `GET /api/broker-calls/{call_id}`.

#### 확정 통화 결과 한 건

```json
{
  "call_id": "bc_a1b2c3", "kind": "confirm", "batch_id": "vb_5d20aa", "parent_call_id": "bc_7f3a9c",
  "broker": { "reg": "11620-2019-00123", "name": "한빛공인중개사" },
  "status": "done", "outcome": "partial", "called_at": "2026-11-20T15:02:10+09:00",
  "target": { "rooms": [
    { "listing_index": 0, "at": "2026-11-21T14:00:00+09:00", "place": null, "alternatives": [] },
    { "listing_index": 1, "at": "2026-11-21T14:30:00+09:00", "place": null, "alternatives": [] } ] },
  "visit_status": "partially_confirmed",
  "rooms": [
    { "listing_index": 0, "at": "2026-11-21T14:00:00+09:00", "outcome": "confirmed", "visit_status": "confirmed",
      "visit": { "at": "2026-11-21T14:00:00+09:00", "place": "한빛공인중개사 사무소", "listing_index": 0 },
      "proposal": null, "still_available": true, "same_listing": true, "unit": "302호" },
    { "listing_index": 1, "at": "2026-11-21T14:30:00+09:00", "outcome": "alternative", "visit_status": "needs_approval",
      "visit": null, "proposal": { "at": "2026-11-21T16:30:00+09:00", "note": "4시 반은 가능하다고 함" },
      "still_available": true, "same_listing": true, "unit": "303호" }
  ],
  "visit": null, "proposal": null, "still_available": null, "same_listing": null, "unit": null,
  "unverified": [], "evidence": { "rooms[0].visit.at": 3, "rooms[1].proposal.at": 6 },
  "quotes": { "3": { "speaker": "broker", "text": "…" } }, "timing": { "…": "…" },
  "transcript": [], "sms_draft": null,
  "attempts": 1, "scheduled_at": null, "retry_at": null, "ended_at": "…", "error": null
}
```

- **방마다 `rooms[]`를 봅니다.** 화면의 일정 카드는 `rooms[].visit_status`가 `confirmed`인 방만 확정으로 그립니다.
- 방이 하나면 `rooms[0]`의 `visit`·`proposal`·`still_available`·`same_listing`·`unit`이 바깥에도 그대로 있습니다(예전 형식과 같음). 방이 여럿이면 바깥 값은 `null`입니다.
- `evidence`·`unverified`의 키는 방이 여럿이면 `rooms[i].` 접두어가 붙습니다.

방별 `outcome` → `rooms[].visit_status`

| 방별 `outcome` | 뜻 | `visit_status` |
|---|---|---|
| (통화 전·중) | | `requesting` — 화면에 **'요청 중'** |
| `confirmed` | 요청 시각이나 그 방의 `alternatives` 안에서 합의. 날짜·시각을 중개사가 한 말에서 확인함(중개사가 시각 없이 "당연하죠"처럼 받기만 했으면, 바로 앞 살구 질문의 시각) | `confirmed` |
| `alternative` | 범위 밖 시각을 제안받음(`proposal`) | `needs_approval` — 사용자가 승인하면 새 `approval_id`로 그 방만 다시 확정 요청 |
| `no_time` | 방은 있지만 시간이 맞지 않음 | `not_scheduled` |
| `unavailable` | 그 방이 나감 | `not_scheduled` |
| `unclear`, `no_answer`, `declined` | 확인 못 함 / 받지 않음(문자 초안 있음) / AI 통화 거절 | `not_scheduled` |

통화 전체 `outcome` → `visit_status`

| 전체 `outcome` | 언제 | `visit_status` |
|---|---|---|
| `confirmed` | 모든 방 확정 | `confirmed` |
| `partial` | 일부 방만 확정 | `partially_confirmed` |
| `alternative` / `no_time` / `unavailable` / `unclear` | 확정된 방 없음(제안 > 시간 안 맞음 > 모두 나감 > 그 밖) | `needs_approval` / `not_scheduled` |
| `no_answer`, `declined` | 받지 않음 / 거절 | `not_scheduled` |

- `same_listing`, `unit`: 방마다 같은 방인지 다시 확인한 결과. 문의 결과의 `duplicate_groups`가 이 호수로 다시 계산됩니다(같은 호수면 `likely_same`, 다르면 묶음에서 빠짐). 최종 판정은 등기부 소재지로 합니다.
- 확정 알림은 확정된 방만 "방문 확정"으로 적습니다. 제안받은 방은 "아직 확정 아님"으로 적습니다.

## 공통: `status`

| 값 | 뜻 |
|---|---|
| `waiting` | 앞 통화가 끝나기를 기다리는 중(한 번에 한 통) |
| `scheduled` | 영업시간(월~토 9~19시, 공휴일 제외) 밖이라 다음 영업 시작에 걸 예정 |
| `queued` → `ringing` → `in_progress` | 발신, 신호, 통화 중 |
| `retry_wait` | 받지 않았거나 자동응답이라 30분 뒤 다시 걸 예정 |
| `analyzing` | 통화가 끝나 결과를 뽑는 중 |
| `done` | 끝남. `outcome`을 봅니다. |
| `failed`, `rejected` | 걸지 못함. `error`에 사유. `rejected`는 접수할 때 거절(하루 제한, 이미 지난 시간대), `failed`는 걸려다 실패(공급사 오류, 줄에서 기다리는 사이 시간대가 지남 = `window_passed`) |

## 알림

`notifications[]`는 묶음 결과에 함께 옵니다: `{id, at, kind, batch_id, call_id, text, channel, status, error}`.

| `kind` | 언제 |
|---|---|
| `inquiry_done` | 문의 묶음의 모든 통화가 끝났을 때 한 번 |
| `visit` | 확정 통화가 끝났을 때(확정 / 제안 / 불가) |
| `registry` | 등기부 문자가 들어왔을 때 |

`channel`: `kakao`(카카오톡 '나에게 보내기') · `sms`(살구 번호에서 문자) · `log`(보내지 않고 기록만). `status`: `sent` · `logged`(`log` 채널) · `failed`(`error`에 사유. 카카오가 실패하면 문자로 다시 보내고 `channel: "sms"`). 화면의 스케줄러 반영은 화면 몫입니다.

## MCP (`mcp-phone`)

같은 서버의 `/mcp`(Streamable HTTP)에서 아래 도구를 엽니다. 입력은 위 REST 본문과 같고, 결과도 같습니다.

| 도구 | REST |
|---|---|
| `call_brokers(approval_id, search, share, brokers, prep?, keep_transcript?)` | `POST /api/broker-call-batches` |
| `get_call_results(batch_id)` | `GET /api/broker-call-batches/{id}`, `GET /api/visit-confirmations/{id}` |
| `confirm_visits(approval_id, visits)` | `POST /api/visit-confirmations` |

## 전화 에이전트가 지키는 것

- 첫마디에 AI 비서임을 밝히고, 원하지 않으면 끊습니다. 계약·가계약금·가격 합의는 하지 않습니다.
- 사용자가 체크한 정보만 말합니다.
- 문의 통화는 같은 사무소 하루 1번, 하루 10통. 확정 통화는 문의 통화 하나당 하루 2통까지(하루 1번·10통에 넣지 않음). 영업시간에만 겁니다.
- 받지 않거나 자동응답이면 30분 뒤 1번만 다시 겁니다.
- 숫자·시각·날짜는 **중개사가 한 말**에 실제로 있을 때만 결과에 넣습니다.

## 앞뒤 담당이 맞춰 줄 것

- **챗봇**: 문의 인풋을 넘기고, 사용자가 일정을 승인하면 확정 인풋을 넘깁니다.
- **화면**: `broker_slots`로 동선·시간을 배치하고, `duplicate_groups`로 중복 의심을 표시합니다. 확정 통화 중에는 '요청 중', `visit_status`가 `confirmed`인 것만 일정 확정으로 보여 주세요. 등기부 첨부는 `registry_docs[].media`로 받습니다.
- **등기 담당**: `registry_docs`의 첨부(문자로 온 것·사용자가 올린 PDF)로 사실 정리를 하고, 소재지로 중복 여부를 최종 판정합니다. 올린 PDF는 정리 뒤 `DELETE`로 지웁니다.
- **화면**: 등기부 PDF 올리기 버튼은 `POST /api/broker-calls/{call_id}/registry-docs`로 보냅니다.
