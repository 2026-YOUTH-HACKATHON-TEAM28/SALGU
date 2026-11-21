# 매물 추천 알고리즘

과거 전월세 실거래에서 조건에 맞는 건물별 대표 매물을 찾고 점수순으로 반환한다.
챗봇과 FastAPI 라우터는 이 모듈 밖에서 `recommend_properties()`를 호출한다.
추천 매물은 기본 5개이며, 이 메소드는 공인중개사를 함께 조회하지 않는다.

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
| `max_bus_headway_min` | X | 최대 버스 배차간격 |
| `max_walk_to_station_min` | X | 첫 버스·지하철 승차지점까지 최대 도보시간 |
| `priorities` | X | `price`, `commute`, `building_age` 등 우선순위 |
| `limit` | X | 반환 개수, 기본 5개 |

챗봇의 조건 카드 전체를 `RecommendationInput.from_condition_card(card)`에 넘길 수도 있다.

## 조회 데이터

- `officetel_rentals`: 오피스텔 과거 전월세 실거래
- `multifamily_rentals`: 연립·다세대 과거 전월세 실거래
- `bus_routes`: 버스 배차간격·첫차·막차
- `bus_stops`, `bus_route_stops`: 매물 주변 정류장·통과 노선
- `subway_stations`: 지하철역·호선
- `subway_first_last`: 지하철 첫차·막차
- `subway_timetables`: 지하철 운행 횟수·배차간격
- `real_estate_agencies`: 공인중개업소
- 기본 조회 기간: 기준일 이전 12개월
- 매물 식별: 주택 유형 + 지역 + 지번 + 건물명 + 5㎡ 면적 구간
- 같은 건물·면적대 거래는 최신 한 건으로 합치고 중앙값·표본 수를 함께 계산

통근시간과 환승 경로는 `KakaoCommuteProvider`가 계산한다. 경로의 노선·정류장·역을
서울시 교통 DB와 결합해 배차간격, 첫차·막차, 운행 횟수와 매물 주변 정류장을 확인한다.
직장 조건이 있으면 가까운 지역을 먼저 거르고, 이후 개별 매물 주소를 계산한다.
직장 조건이 있는데 제공자가 없으면 잘못된 결과를 반환하지 않고 오류를 발생시킨다.

## 출력

`RecommendationOutput.candidates`에 추천 순서대로 다음을 반환한다.

- 건물명, 주소, 주택·계약 유형
- 대표 보증금·월세, 면적, 층, 건축연도
- 통근시간·경로거리·환승 횟수·요금
- 버스·지하철 노선, 배차간격, 첫차·막차, 승하차 지점, 도보 구간
- 매물 반경 800m 내 버스 정류장과 통과 노선
- 총점과 항목별 점수
- 실제 적용 가중치
- 추천 이유
- 같은 건물·면적대 가격 중앙값
- 원본 테이블·행 번호·계약일·건물 표본 수

과거 계약 기반 결과이므로 `is_live_listing`은 항상 `false`다. 현재 매물 존재 여부는
중개사 확인 단계에서 결정한다.

## 호출

```python
from property_recommendation import (
    KakaoCommuteConfig,
    KakaoCommuteProvider,
    recommend_properties,
)

async with KakaoCommuteProvider(KakaoCommuteConfig.from_env()) as commute_provider:
    result = await recommend_properties(
        criteria=RecommendationInput.from_condition_card(card),
        session=db_session,
        commute_provider=commute_provider,
    )
```

`KAKAO_REST_API_KEY`에는 카카오 디벨로퍼스 REST API 키를 넣고 카카오맵 API 사용 설정을
활성화해야 한다. FastAPI에서는 provider를 요청마다 만들지 말고 lifespan에서 한 번 생성해
HTTP 연결과 좌표·경로 캐시를 재사용한다.

지역 검색 반경은 10km에서 시작한다. 조건을 만족하는 추천이 없으면 20km, 40km로
확장하고 지역 경로 호출 상한도 10건, 20건, 30건으로 늘린다. 결과가 있으면 이후 단계는
호출하지 않는다. 개별 매물은 최대 30건을 주소 단위로 측정하며, 확인된 후보만 사용한다.
경로는 시간·환승·도보 제한을 먼저 만족시킨 뒤 환승 횟수, 소요시간 순으로 선택한다.

버스 배차간격 조건은 카카오 응답이 아니라 `bus_routes` DB 값으로 검증한다.

연동 확인:

```powershell
$env:KAKAO_REST_API_KEY="REST_API_KEY"
python scripts/check_kakao_commute.py 강남역 "서울특별시 마포구 공덕동"
```

## 건물 확정 후 공인중개사 검색

추천 결과에서 사용자가 건물을 선택한 뒤 별도 메소드를 호출한다.
카카오 `AG2` 카테고리에서 매물 주변 업소를 거리순으로 찾은 뒤,
`real_estate_agencies`의 이름·전화번호·주소와 대조한다. DB에서 영업 중으로 확인되는
업소만 등록번호·영업상태와 함께 반환한다.

- `recommend_properties()`: 매물 추천만 수행
- `find_nearest_realtors()`: 확정된 매물의 공인중개사 검색만 수행

```python
from property_recommendation import RealtorSearchInput, find_nearest_realtors

realtors = await find_nearest_realtors(
    RealtorSearchInput(
        property_address=selected_property.address,
        limit=5,
    ),
    session=db_session,
    location_provider=commute_provider,
)
```

`max_distance_m`을 넣으면 최대 20km 안에서만 검색하고, 생략하면 가장 가까운 중개업소를
거리순으로 조회한다. 이름·전화번호·주소·등록번호·영업상태·거리·카카오맵 링크를 반환한다.

사용 API: [카카오 대중교통 경로 조회](https://developers.kakao.com/docs/ko/kakaomap/rest-api),
[카카오 주소·카테고리 검색](https://developers.kakao.com/docs/ko/local/dev-guide)

## 평가

실제 DB 평가 스크립트는 `scripts/evaluate.py`다. 대표 조건별 제약 준수, 점수 정렬,
중복, 커버리지와 응답 시간을 확인한다. 최신 결과는 `evaluation/`에서 확인한다.

