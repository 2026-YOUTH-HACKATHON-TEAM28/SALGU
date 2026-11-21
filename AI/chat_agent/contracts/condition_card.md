# 조건 카드 (Condition Card) 형식

> 상태: **초안**입니다. FE(채팅·카드)·BE(검색·점수 엔진)와 합의하기 전이며, 형식이 바뀌면 `version`을 올립니다.
>
> 0.2: 전세·반전세(`lease_types`), 살 곳·피할 곳(`preferred_areas`·`avoid_areas`), 면적(`min_area_m2`), 층(`min_floor`), 역까지 걸어서(`max_walk_to_station_min`)를 더했습니다. 챗봇은 계산·위치 찾기를 하지 않고 말을 이 카드로 바꾸기만 합니다.

`infer_conditions`는 사용자의 말을 조건 카드로 바꿉니다. FE는 카드를 그대로 보여 주고 추론한 조건에는 '추론' 표시를 붙입니다. 사용자가 [이대로 찾기]를 누르면 BE 검색·점수 엔진이 같은 JSON을 입력으로 받습니다.

## 원칙

- 사용자가 말한 것에서만 추론합니다. 말하지 않은 것(전세대출·매매 등)은 넣지 않습니다.
- 카드는 **무엇을 볼지**만 정합니다. 실거래 분위수, 통근 시간 같은 숫자 판정은 계산 엔진이 합니다.
- 데이터로 판단할 수 없는 바람은 `unverifiable`에 넣고 "데이터로 확인할 수 없어요"로 표시합니다.
- **처음부터 다 묻지 않습니다.** 대충 말해도 가장 자연스러운 뜻으로 카드를 만들고(해석한 조건은 `inferred`), 사용자는 다음 말로 고칩니다(예: "홍대는 좀?" → 홍대를 `avoid_areas`로).
- **최소 조건은 지역·보증금·월세 세 가지**입니다(지역 = `preferred_areas` 또는 `workplace`, 전세면 월세 없음). 빠진 것만 한 번에 자연스럽게 묻고 `clarifications`에 버튼을 넣습니다. 그 밖의 조건은 묻지 않습니다.
- 최소 조건이 다 모이면 `ready: true`입니다. 계산하는 쪽(BE)은 `ready`인 카드로 검색합니다.
- 금액 단위는 만원입니다(국토부 실거래 API와 같은 단위).

## 예시 1: 기본 흐름

입력: "회사가 강남역인데 1000/50 정도로 깨끗하고 싼 집 찾아줘. 출퇴근 편했으면 좋겠어"

```json
{
  "version": "0.2-draft",
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

## 예시 2: 확인 불가, 되묻지 않고 해석

입력: "여의도 쪽 조용한 오피스텔 찾아줘"

"여의도 쪽"은 회사라는 말이 없으므로 살고 싶은 곳으로 해석합니다. 되묻지 않고, 사용자가 "아니 회사가 여의도야"라고 하면 그때 고칩니다.

```json
{
  "version": "0.2-draft",
  "utterance": "여의도 쪽 조용한 오피스텔 찾아줘",
  "conditions": {
    "housing_types": {
      "value": ["officetel"],
      "source": "stated",
      "evidence": "오피스텔"
    },
    "preferred_areas": {
      "value": ["여의도"],
      "source": "stated",
      "evidence": "여의도 쪽"
    }
  },
  "priorities": [],
  "unverifiable": [
    { "phrase": "조용한", "message": "데이터로 확인할 수 없어요" }
  ],
  "clarifications": []
}
```

## 예시 2-1: 다음 말로 고치기

이전 카드가 `preferred_areas` = ["홍대"]일 때 입력: "홍대는 좀?"

→ `preferred_areas`에서 홍대를 빼고 `avoid_areas` = ["홍대"]를 넣은 **전체 카드**를 돌려줍니다. 나머지 조건은 그대로 둡니다.

## 예시 3: 살 곳·전세·면적·층·역까지 거리

입력: "홍대입구역 근처에 전세 1억 5천 이하 투룸, 반지하는 싫고 역에서 5분 안쪽이면 좋겠어. 신림은 빼줘"

```json
{
  "version": "0.2-draft",
  "utterance": "홍대입구역 근처에 전세 1억 5천 이하 투룸, 반지하는 싫고 역에서 5분 안쪽이면 좋겠어. 신림은 빼줘",
  "conditions": {
    "lease_types": {
      "value": ["jeonse"],
      "source": "stated",
      "evidence": "전세"
    },
    "deposit_manwon": {
      "value": 15000,
      "source": "stated",
      "evidence": "전세 1억 5천 이하"
    },
    "preferred_areas": {
      "value": ["홍대입구역"],
      "source": "stated",
      "evidence": "홍대입구역 근처에"
    },
    "avoid_areas": {
      "value": ["신림"],
      "source": "stated",
      "evidence": "신림은 빼줘"
    },
    "min_area_m2": {
      "value": 33,
      "source": "inferred",
      "evidence": "투룸",
      "reason": "투룸을 전용 33㎡(약 10평) 이상으로 해석"
    },
    "min_floor": {
      "value": 1,
      "source": "stated",
      "evidence": "반지하는 싫고"
    },
    "max_walk_to_station_min": {
      "value": 5,
      "source": "stated",
      "evidence": "역에서 5분 안쪽"
    }
  },
  "priorities": [],
  "unverifiable": [],
  "clarifications": []
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
| `conditions.workplace` | `"place"` | 출근지(회사·학교). `label`에 사용자가 말한 회사·학교·역 이름을 그대로 둡니다. 챗봇은 위치를 찾지 않습니다. 실제 위치는 계산하는 쪽(BE)이 찾습니다. (기존 `gangnam`·`yeouido`·`jongno` 값도 읽을 수 있습니다) |
| `conditions.workplace.kind` | `"work"` \| `"school"` | 회사인지 학교인지 (학교면 '통학'으로 말함) |
| `conditions.max_commute_min` | int | 출근 시간대 통근 상한(분) |
| `conditions.max_transfers` | int | 환승 상한 |
| `conditions.max_bus_headway_min` | int | 이용 버스 배차 상한(분) |
| `conditions.lease_types` | `"monthly"` \| `"jeonse"` \| `"semi_jeonse"` 배열 | 월세 / 전세 / 반전세. 전세는 `deposit_manwon`만 두고 월세 칸은 넣지 않습니다. |
| `conditions.preferred_areas` | string 배열 | 살고 싶은 곳(구·동·역 이름). 사용자가 말한 이름 그대로. 회사 위치와 구분합니다. |
| `conditions.avoid_areas` | string 배열 | 피하고 싶은 곳(구·동·역 이름) |
| `conditions.min_area_m2` | number | 전용면적 하한(㎡). 평은 × 3.3058, 소수 첫째 자리까지 |
| `conditions.min_floor` | int | 최저 층. 반지하 제외 = 1, 1층 제외 = 2 |
| `conditions.max_walk_to_station_min` | int | 가까운 지하철역까지 걸어서 상한(분) |
| `priorities` | string 배열 | 사용자가 말한 우선순위. `price`, `commute`, `bus_headway`, `building_age` 중에서 순서대로 |
| `unverifiable` | `{phrase, message}` 배열 | 데이터로 판단할 수 없는 바람 |
| `clarifications` | `{id, question, options}` 배열 | 빠진 최소 조건 버튼 되묻기. `id`: `area`, `budget`, `deposit`, `monthly_rent` |
| `workplace_hint` | `"학교"` \| `"회사"` \| `"학원"` | 학교·회사를 말했는데 이름이 없을 때("학교 근처 원룸"). 지역 대신 "학교는 어디예요?"라고 묻고, 다음 답을 `workplace`로 받습니다. |
| `missing` | string 배열 | 아직 모르는 최소 조건: `area`, `deposit`, `monthly_rent` |
| `ready` | bool | 최소 조건이 다 모였는지. `true`면 검색 가능 |

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
| "전세 2억", "반전세 5천에 30" | `lease_types` = 전세 / 반전세, 보증금(·월세) |
| "마포 근처 살고 싶어", "홍대입구역 근처 원룸" | `preferred_areas` (회사라는 말이 없으면 회사 위치가 아님) |
| "강남역 1000/50" (회사라는 말 없음) | `preferred_areas` (inferred, 살고 싶은 곳으로 해석) |
| "신림 말고", "강북은 빼고", "홍대는 좀?" | `avoid_areas` (이전 카드의 `preferred_areas`에 있으면 뺌) |
| "10평 이상", "20㎡ 넘는" | `min_area_m2` (stated) |
| "투룸" / "쓰리룸" | `min_area_m2` = 33 / 50 (inferred, 실거래에 방 수가 없어 면적으로 해석) |
| "반지하 싫어" / "1층은 싫어" / "3층 이상" | `min_floor` = 1 / 2 / 3 |
| "역에서 5분" / "역세권" | `max_walk_to_station_min` = 5 (stated) / 10 (inferred) |
| "부산 해운대", "분당 쪽" (서울 밖) | 살 곳으로 받지 않고 `unverifiable`에 "서울 밖은 아직 찾아 드리지 못해요(서울만)". 회사 위치로는 괜찮음 |
| "조용한 곳", 반려동물, 주차, 엘리베이터, 옵션 등 판단할 데이터가 없는 바람 | `unverifiable` |

## 합의할 점

- "정도"의 허용 범위(예: ±10%)를 카드에 둘지, 엔진 기본값으로 둘지
- 출근지를 업무지구 3곳으로 제한할지(기획서 MVP), 지도에서 찾은 실제 위치로 넓힐지(현재 시험 서버 방식)
- 후보가 0곳일 때 조건을 풀어 주는 제안("준공 15년까지 넓힐까요?")을 카드 형식에 포함할지, 검색 응답에 둘지
