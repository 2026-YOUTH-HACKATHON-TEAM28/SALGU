# 매물 추천 알고리즘

과거 전월세 실거래에서 조건에 맞는 건물별 대표 매물을 찾고 점수순으로 반환한다.
챗봇과 FastAPI 라우터는 이 모듈 밖에서 `recommend_properties()`를 호출한다.

## 입력

| 필드 | 필수 | 설명 |
|---|---:|---|
| `deposit_manwon` | O | 최대 보증금, 단위 만원 |
| `monthly_rent_manwon` | 월세일 때 O | 최대 월세, 단위 만원 |
| `housing_types` | X | `officetel`, `villa` |
| `lease_types` | X | `monthly`, `jeonse`, `semi_jeonse` |
| `preferred_areas` | X | 포함할 구·동 이름 |
| `avoid_areas` | X | 제외할 구·동 이름 |
| `min_area_m2` | X | 최소 전용면적 |
| `min_floor` | X | 최소 층 |
| `max_building_age_years` | X | 최대 건물 연식 |
| `workplace` | X | 회사·학교·역 이름 |
| `max_commute_min` | X | 최대 통근시간 |
| `max_transfers` | X | 최대 환승 횟수 |
| `priorities` | X | `price`, `commute`, `building_age` 등 우선순위 |
| `limit` | X | 반환 개수, 기본 5개 |

챗봇의 조건 카드 전체를 `RecommendationInput.from_condition_card(card)`에 넘길 수도 있다.

## 조회 데이터

- `officetel_rentals`: 오피스텔 과거 전월세 실거래
- `multifamily_rentals`: 연립·다세대 과거 전월세 실거래
- 기본 조회 기간: 기준일 이전 12개월
- 매물 식별: 주택 유형 + 지역 + 지번 + 건물명 + 5㎡ 면적 구간
- 같은 건물·면적대 거래는 최신 한 건으로 합치고 중앙값·표본 수를 함께 계산

현재 DB에는 건물·지하철역 좌표가 없으므로 통근시간은 `CommuteProvider` 구현체가 제공한다.
직장 조건이 있으면 통근 제공자가 지역을 먼저 거르고, 이후 개별 매물 통근시간을 계산한다.
직장 조건이 있는데 제공자가 없으면 잘못된 결과를 반환하지 않고 오류를 발생시킨다.

## 출력

`RecommendationOutput.candidates`에 추천 순서대로 다음을 반환한다.

- 건물명, 주소, 주택·계약 유형
- 대표 보증금·월세, 면적, 층, 건축연도
- 통근시간·환승 횟수(제공된 경우)
- 총점과 항목별 점수
- 실제 적용 가중치
- 추천 이유
- 같은 건물·면적대 가격 중앙값
- 원본 테이블·행 번호·계약일·건물 표본 수

과거 계약 기반 결과이므로 `is_live_listing`은 항상 `false`다. 현재 매물 존재 여부는
중개사 확인 단계에서 결정한다.

## 호출

```python
result = await recommend_properties(
    criteria=RecommendationInput.from_condition_card(card),
    session=db_session,
    commute_provider=commute_provider,
)
```

`CommuteProvider`는 `measure_regions()`와 `measure_properties()`를 구현한다. 지역 통근값으로
후보 지역을 먼저 좁히므로, 최신 거래 200건에 먼저 제한하던 편향이 없다.

