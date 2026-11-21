# 추천 메소드 I/O

## 메소드 분리

```python
# 1. 조건에 맞는 매물을 기본 5개 추천한다.
recommendations = await recommend_properties(criteria, session, commute_provider)

# 2. 사용자가 확정한 매물 주소로 공인중개사를 별도 조회한다.
realtors = await find_nearest_realtors(realtor_criteria, provider)
```

두 메소드는 서로 자동 호출하지 않는다. 입력·출력 필드 설명은 Pydantic
`Field(description=...)`에 정의되어 FastAPI OpenAPI 문서에도 포함된다.

## 입력 예시

```json
{
  "deposit_manwon": 1000,
  "monthly_rent_manwon": 50,
  "deposit_approx": false,
  "monthly_rent_approx": true,
  "housing_types": ["officetel", "villa"],
  "lease_types": ["monthly"],
  "preferred_areas": ["마포구", "서대문구"],
  "avoid_areas": ["신림동"],
  "min_area_m2": 20,
  "min_floor": 1,
  "max_building_age_years": 10,
  "workplace": "강남역",
  "max_commute_min": 40,
  "max_transfers": 1,
  "max_walk_to_station_min": 10,
  "priorities": ["commute", "price"],
  "limit": 5
}
```

- 금액 단위는 만원이다.
- `approx=true`인 금액만 검색 상한을 10% 늘린다.
- 월세·반전세는 `monthly_rent_manwon`이 필요하다.
- 통근 조건을 쓰려면 `workplace`가 필요하다.

## 출력 예시

```json
{
  "count": 1,
  "candidates": [
    {
      "name": "살구오피스텔",
      "address": "서울특별시 마포구 1-1",
      "housing_type": "officetel",
      "rent_type": "월세",
      "deposit_manwon": 1000,
      "monthly_rent_manwon": 45,
      "area_m2": 23.1,
      "floor": 4,
      "construction_year": 2021,
      "contract_date": "2026-11-01",
      "commute_minutes": 35,
      "transfers": 1,
      "commute_distance_km": 14.32,
      "transit_fare_won": 1500,
      "station": "공덕역",
      "walk_to_station_min": 4,
      "route_url": "https://map.kakao.com/...",
      "transit_legs": [
        {
          "mode": "walking",
          "minutes": 4,
          "distance_m": 220,
          "guidance": "공덕역까지 도보 이동",
          "start_name": null,
          "end_name": null,
          "route_names": []
        },
        {
          "mode": "subway",
          "minutes": 25,
          "distance_m": 12000,
          "guidance": null,
          "start_name": "공덕역",
          "end_name": "강남역",
          "route_names": ["5호선", "2호선"]
        }
      ],
      "score": 82.4,
      "score_breakdown": {
        "price": 0.4,
        "area": 0.31,
        "building_age": 0.5,
        "recency": 0.94,
        "evidence": 0.73,
        "commute": 0.56
      },
      "applied_weights": {
        "price": 0.35,
        "area": 0.1,
        "building_age": 0.1,
        "recency": 0.15,
        "evidence": 0.1,
        "commute": 0.2
      },
      "reasons": [
        "보증금 1000만·월세 45만 중앙값",
        "전용 23.1㎡",
        "통근 35분·환승 1회",
        "최근 12개월 실거래 8건"
      ],
      "market_median_deposit_manwon": 1000,
      "market_median_monthly_rent_manwon": 47,
      "source_table": "officetel_rentals",
      "source_row": 7,
      "transaction_count": 8,
      "is_live_listing": false
    }
  ],
  "query": {
    "start_date": "2025-11-26",
    "end_date": "2026-11-21",
    "source_tables": ["officetel_rentals", "multifamily_rentals"],
    "evaluated_count": 500,
    "evaluated_region_count": 12,
    "commute_evaluated_count": 30,
    "commute_search_depth": 1,
    "commute_search_radius_km": 20
  },
  "unapplied_conditions": [],
  "applied_tolerances": ["월세 상한 +10%"]
}
```

`is_live_listing=false`는 이 후보가 과거 계약 데이터라는 뜻이다. 현재 계약 가능한지는
중개사 확인 결과로 갱신한다.

`commute_evaluated_count`는 카카오 API로 주소 단위 통근 경로가 확인된 후보 수다.
`commute_search_depth=0`은 최초 10km, `1`은 20km, `2`는 40km까지 확장했다는 뜻이다.

## 건물 확정 후 공인중개사 검색

입력:

```json
{
  "property_address": "서울특별시 마포구 공덕동 1-1",
  "limit": 5,
  "max_distance_m": 5000
}
```

- `property_address`: 사용자가 확정한 추천 결과의 `address`
- `limit`: 반환 개수, 기본 5개, 최대 15개
- `max_distance_m`: 선택 사항, 최대 20000m

출력:

```json
{
  "property_address": "서울특별시 마포구 공덕동 1-1",
  "count": 1,
  "offices": [
    {
      "place_id": "12345",
      "name": "살구공인중개사",
      "phone": "02-123-4567",
      "address": "서울 마포구 공덕동 1-2",
      "road_address": "서울 마포구 살구로 1",
      "distance_m": 120,
      "longitude": 126.951,
      "latitude": 37.541,
      "place_url": "https://place.map.kakao.com/12345"
    }
  ]
}
```

호출 메소드:

```python
result = await find_nearest_realtors(criteria, provider=commute_provider)
```

## 점수

| 항목 | 기본 비중 | 데이터 |
|---|---:|---|
| 가격 | 35% | 건물별 보증금·월세 중앙값 |
| 면적 | 10% | 전용면적 |
| 연식 | 10% | 건축연도 |
| 최근성 | 15% | 최신 계약일 |
| 근거량 | 10% | 같은 건물 실거래 수 |
| 통근 | 20% | 외부 `CommuteProvider` 결과 |

사용자가 말한 `priorities` 항목의 비중을 높인 뒤, 사용 가능한 항목끼리 합계가 100%가
되도록 다시 계산한다. 최종 비중은 각 후보의 `applied_weights`로 반환한다.

가격·면적·연식·통근의 상한 또는 하한을 정확히 만족하면 0.5점이다. 조건 안에서 여유가
클수록 최대 1점까지 올라간다. 가격 점수는 화면에 표시하는 최신 실거래 가격으로 계산하고,
중앙값은 같은 건물·5㎡ 면적대의 비교 근거로만 사용한다.
