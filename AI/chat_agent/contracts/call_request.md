# 전화 요청 초안 (챗봇 → BE → 전화 서버)

> 상태: **초안 0.1**. BE·FE·전화 서버(기하)와 합의하기 전입니다.

**챗봇은 전화를 걸지 않습니다.** 사용자가 추천 매물을 보고 "이 집 보고 싶어", "2번 문의해 줘", "전화해 줘"라고 하면, 챗봇은 그 매물이 있는 동의 중개사무소에 물어볼 **요청 초안**만 만듭니다. 실제 전화는 사용자가 화면에서 승인한 뒤 BE가 전화 서버에 보냅니다.

```
화면(FE) ──▶ BE (로그인·승인·DB 저장)
               ├─▶ 챗봇 서버 (안쪽): 말 이해, 추천, 전화 요청 초안
               └─▶ 전화 서버 (안쪽, AI/phone_agent): 승인된 요청만 받아 한 통씩 전화
```

돈이 들고 사람에게 실제로 연락하는 행동은 사람이 승인해야 하기 때문입니다. 그래서 AI(챗봇)는 제안만 하고, 승인과 실행 기록은 BE가 맡습니다.

## 흐름

1. 사용자: "2번 집 보고 싶어" → `POST /api/chat`
2. 챗봇 응답의 `action`에 초안이 옵니다. 세션 캐시의 `pending_action`에도 저장됩니다.
3. 화면은 초안을 보여 주고 아래 값을 사용자에게 받습니다.
   - 방문 가능 시간(`visit_windows`)
   - 중개사에게 알려도 되는 정보(`share`: 희망 조건, 방문 시간, 성, 연락처)
   - 대화 전문 보관 동의(`keep_transcript`)
   - 전화할 사무소 순서
4. 사용자가 [전화 요청]을 승인하면 BE가 `approval_id`를 만들어 초안을 채우고, 전화 서버 `POST /api/broker-call-batches`로 보냅니다.
5. BE가 결과를 조회해 DB에 저장하고, 화면에 진행 상황을 보여 줍니다. 결과 형식: `AI/phone_agent/contracts/io.md`

## `action` 형식

```json
{
  "type": "broker_call_request",
  "status": "needs_approval",
  "listing": { "name": "엔트라리움", "address": "서울특별시 서대문구 대현동 90-26", "housing_type": "officetel",
               "deposit_manwon": 60, "monthly_rent_manwon": 38, "area_m2": 17.6, "floor": 3 },
  "needs_user_input": ["visit_windows", "share", "approval_id"],
  "request": {
    "approval_id": null,
    "search": { "dong": "대현동", "ref_building": "엔트라리움", "housing_type": "officetel",
                "deposit_manwon": 1000, "monthly_rent_manwon": 50, "area_m2": 17.6 },
    "prep": { "move_in": "", "term": "", "pet": false, "surname": "" },
    "share": { "conditions": true, "visit_time": true, "surname": false, "contact": false },
    "keep_transcript": false,
    "brokers": [ { "reg": "92360000-가345", "name": "이화부동산중개인사무소", "phone": "02-313-…", "visit_windows": [] } ]
  },
  "phone_agent": { "endpoint": "POST /api/broker-call-batches", "contract": "AI/phone_agent/contracts/io.md" }
}
```

| 필드 | 설명 |
|---|---|
| `status` | `needs_approval`(사무소를 찾음) 또는 `no_agencies`(DB 접속이 안 되거나 그 구에 전화번호 있는 사무소가 없음) |
| `listing` | 사용자가 고른 추천 매물(추천 엔진 값 그대로) |
| `request` | 전화 서버 문의 요청 본문. **`approval_id`와 `brokers[].visit_windows`만 비어 있습니다.** BE가 채우면 그대로 보낼 수 있습니다(기하님 `BatchRequest` 형식 검증 통과) |
| `request.search` | 동 = 매물 주소의 동. 예산 = 사용자가 말한 예산(매물 가격이 아님). 참고 건물 = 매물 건물명(건물명이 없으면 빈 값) |
| `request.share` | 기본값입니다. 사용자가 화면에서 체크한 대로 바꿉니다. 체크하지 않은 정보는 통화에서 말하지 않습니다 |
| `request.prep.pet` | 사용자가 반려동물을 말했으면 `true` (전화 서버가 가능 여부를 물음) |
| `request.brokers` | 실거래 DB `real_estate_agencies`에서 고른 사무소(기본 3곳). 같은 동, 영업 중, 전화번호 있음, 조회 수 많은 순. 같은 동에 모자라면 같은 구에서 채웁니다. 지역번호가 빠진 번호는 02를 붙입니다 |

## BE가 지켜 주실 것

- **승인 없이 보내지 않습니다.** 한 번 승인에 `approval_id` 하나. 같은 값으로 다시 보내면 전화 서버가 다시 걸지 않습니다.
- 전화 서버는 인증이 없으므로 BE 안쪽에서만 부릅니다(바깥 주소로 열지 않음).
- 전화 서버는 프로세스 하나(`--workers 1`)로 띄웁니다. 줄과 하루 제한이 그 안에 있습니다.
