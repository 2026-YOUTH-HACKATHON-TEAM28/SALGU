# 조건 카드 (Condition Card) 형식

> 상태: **초안**입니다. FE(채팅·카드)·BE(검색·점수 엔진)와 합의하기 전이며, 형식이 바뀌면 `version`을 올립니다.

`infer_conditions`는 사용자의 말을 조건 카드로 바꿉니다. FE는 카드를 그대로 보여 주고 추론한 조건에는 '추론' 표시를 붙입니다. 사용자가 [이대로 찾기]를 누르면 BE 검색·점수 엔진이 같은 JSON을 입력으로 받습니다.

## 원칙

- 사용자가 말한 것에서만 추론합니다. 말하지 않은 것(전세대출·매매 등)은 넣지 않습니다.
- 카드는 **무엇을 볼지**만 정합니다. 실거래 분위수, 통근 시간 같은 숫자 판정은 계산 엔진이 합니다.
- 데이터로 판단할 수 없는 바람은 `unverifiable`에 넣고 "데이터로 확인할 수 없어요"로 표시합니다.
- 해석이 둘 이상이면 `clarifications`에 버튼 되묻기를 넣습니다.
- 금액 단위는 만원입니다(국토부 실거래 API와 같은 단위).

## 예시 1: 기본 흐름

입력: "회사가 강남역인데 1000/50 정도로 깨끗하고 싼 집 찾아줘. 출퇴근 편했으면 좋겠어"

```json
{
  "version": "0.1-draft",
  "utterance": "회사가 강남역인데 1000/50 정도로 깨끗하고 싼 집 찾아줘. 출퇴근 편했으면 좋겠어",
  "conditions": {
    "housing_types": {
      "value": ["officetel", "villa"],
      "source": "inferred",
      "evidence": "깨끗하고",
      "reason": "'깨끗한'을 오피스텔·신축 빌라로 해석"
    },
    "max_building_age_years": {
      "value": 10,
      "source": "inferred",
      "evidence": "깨끗하고",
      "reason": "준공 10년 이내"
    },
    "deposit_manwon": {
      "value": 1000,
      "approx": true,
      "source": "stated",
      "evidence": "1000/50 정도"
    },
    "monthly_rent_manwon": {
      "value": 50,
      "approx": true,
      "source": "stated",
      "evidence": "1000/50 정도"
    },
    "price_band": {
      "value": "median_or_below",
      "source": "inferred",
      "evidence": "싼",
      "reason": "같은 조건 실거래의 가운데~아래 구간"
    },
    "workplace": {
      "value": "place",
      "label": "강남역",
      "source": "stated",
      "evidence": "회사가 강남역"
    },
    "max_commute_min": {
      "value": 40,
      "source": "inferred",
      "evidence": "출퇴근 편했으면",
      "reason": "출근 시간대 통근 40분 이내"
    },
    "max_transfers": {
      "value": 1,
      "source": "inferred",
      "evidence": "출퇴근 편했으면",
      "reason": "환승 1회 이하"
    },
    "max_bus_headway_min": {
      "value": 10,
      "source": "inferred",
      "evidence": "출퇴근 편했으면",
      "reason": "이용 버스는 배차 10분 이하 노선"
    }
  },
  "priorities": [],
  "unverifiable": [],
  "clarifications": []
}
```

## 예시 2: 확인 불가와 되묻기

입력: "여의도 쪽 조용한 오피스텔 찾아줘"

```json
{
  "version": "0.1-draft",
  "utterance": "여의도 쪽 조용한 오피스텔 찾아줘",
  "conditions": {
    "housing_types": {
      "value": ["officetel"],
      "source": "stated",
      "evidence": "오피스텔"
    }
  },
  "priorities": [],
  "unverifiable": [
    { "phrase": "조용한", "message": "데이터로 확인할 수 없어요" }
  ],
  "clarifications": [
    {
      "id": "yeouido_role",
      "question": "여의도는 회사 위치인가요, 살고 싶은 동네인가요?",
      "options": ["회사가 여의도예요", "여의도 근처에 살고 싶어요"]
    }
  ]
}
```

## 필드

| 필드 | 형식 | 설명 |
|---|---|---|
| `version` | string | 형식 버전 |
| `utterance` | string | 사용자가 한 말. 개인정보는 가린 뒤 전달합니다. |
| `conditions` | object | 조건 항목. 사용자가 말하지 않았고 추론 근거도 없는 항목은 넣지 않습니다. |
| `conditions.housing_types` | `"officetel"` \| `"villa"` 배열 | 오피스텔 / 연립다세대(빌라) |
| `conditions.max_building_age_years` | int | 준공 후 최대 연수 |
| `conditions.deposit_manwon` | int | 보증금(만원). `approx: true`면 "정도" |
| `conditions.monthly_rent_manwon` | int | 월세(만원). `approx: true`면 "정도" |
| `conditions.price_band` | `"median_or_below"` | 같은 조건 실거래 대비 가격 구간 |
| `conditions.workplace` | `"place"` | 출근지. `label`에 사용자가 말한 회사·학교·역 이름을 그대로 둡니다. 실제 위치는 서버가 카카오 지도에서 찾아 `place`(`name`, `address`, `x`, `y`)로 붙입니다. 서울 밖이면 `unverifiable`로 보냅니다. (기존 `gangnam`·`yeouido`·`jongno` 값도 읽을 수 있습니다) |
| `conditions.max_commute_min` | int | 출근 시간대 통근 상한(분) |
| `conditions.max_transfers` | int | 환승 상한 |
| `conditions.max_bus_headway_min` | int | 이용 버스 배차 상한(분) |
| `priorities` | string 배열 | 사용자가 말한 우선순위. `price`, `commute`, `bus_headway`, `building_age` 중에서 순서대로 |
| `unverifiable` | `{phrase, message}` 배열 | 데이터로 판단할 수 없는 바람 |
| `clarifications` | `{id, question, options}` 배열 | 버튼 되묻기 |

조건 항목은 모두 다음 형태를 따릅니다.

| 키 | 설명 |
|---|---|
| `value` | 조건 값 |
| `source` | `"stated"`(사용자가 직접 말함) 또는 `"inferred"`(살구가 추론함, 카드에 '추론' 표시) |
| `evidence` | 근거가 된 사용자 말의 구절 |
| `reason` | 추론 이유. `inferred`일 때 씁니다. |

## 추론 규칙 (MVP)

| 사용자의 말 | 조건 |
|---|---|
| "깨끗한 집" | `housing_types` = 오피스텔·빌라, `max_building_age_years` = 10 |
| "싼 집", "1000/50 정도" | 보증금·월세 값(`approx`) + `price_band` = `median_or_below` |
| "출퇴근 편하게", "회사가 강남역" | `workplace`, `max_commute_min` = 40, `max_transfers` = 1, `max_bus_headway_min` = 10 |
| "조용한 곳" 등 판단할 데이터가 없는 바람 | `unverifiable` |

## 합의할 점

- "정도"의 허용 범위(예: ±10%)를 카드에 둘지, 엔진 기본값으로 둘지
- 출근지를 업무지구 3곳으로 제한할지(기획서 MVP), 지도에서 찾은 실제 위치로 넓힐지(현재 시험 서버 방식)
- 후보가 0곳일 때 조건을 풀어 주는 제안("준공 15년까지 넓힐까요?")을 카드 형식에 포함할지, 검색 응답에 둘지
