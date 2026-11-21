# 교통 지표 (버스 배차 · 가까운 역)

> 상태: **초안 0.1**. 구현: `src/salgu_chat/transit.py`, `geocode.py`, `recommender.apply_transit`

추천 엔진이 고른 매물마다 주변 대중교통 지표를 붙이고, 사용자가 말한 교통 조건으로 거릅니다. 추천 엔진은 배차 간격을 계산하지 않고, 회사·학교가 없으면 교통 조건을 받지 않기 때문에, 이 일은 챗봇의 연결 모듈이 맡습니다. 외부 API는 주소 → 좌표 변환에만 씁니다.

## 계산 방법

| 지표 | 데이터 | 방법 |
|---|---|---|
| 버스 | `bus_stops`, `bus_route_stops`, `bus_routes` | 매물에서 400m 안 정류소에 서는 노선 중 평일 배차(`평일공동배차` 시트)가 가장 짧은 노선. 간선·지선·마을·광역·순환만 셈(공항·관광·한강·심야 제외) |
| 가까운 역 | `subway_stations`, `subway_first_last` | 1.5km 안에서 가장 가까운 역. 평일(`day_code` 1) 첫차·막차 |
| 도보 시간 | — | 직선거리 × 1.3 ÷ 분당 75m, 올림 |

- **역 좌표는 추정값입니다.** DB에 역 좌표가 없어 이름이 'OO역'으로 시작하는 버스 정류소들의 좌표로 대신합니다(서울 역 292곳). 정류소 이름으로 찾지 못한 역(예: 망원역)은 `geocode_buildings.py`가 카카오 키워드 검색으로 채웁니다.
- **매물 좌표:** 실거래 DB에는 좌표가 없습니다. `geocode.py`가 `시·구·동 + 지번`을 카카오(또는 브이월드) 지오코더로 좌표로 바꾸고 `.cache/geo/coords.json`에 쌓습니다. 실거래 건물은 54,374곳입니다.

## 후보에 붙는 값

```json
"transit": {
  "bus": { "route": "서대문03", "type": "마을", "headway_min": 5, "headway_range": [4, 7],
           "first": "05:25", "last": "00:15", "stop": "신촌전철역", "walk_min": 1,
           "stops_nearby": 29, "routes_nearby": 43, "frequent_routes": ["서대문03", "271", "273"] },
  "station": { "name": "신촌역", "lines": ["02호선", "경의선"], "walk_min": 2, "distance_m": 140,
               "first": "05:32", "last": "00:58", "estimated_position": true }
},
"transit_text": "신촌역(2호선·경의선) 걸어서 2분 · 버스 서대문03 배차 5분",
"station": "신촌역", "walk_to_station_min": 2
```

- 좌표를 모르는 매물은 `transit: null`입니다.
- 검색 결과 최상위의 `transit`은 상태입니다: `{"available", "limits", "located"(좌표를 찾은 후보 수), "reason"(지오코딩이 꺼진 이유)}`. `reason`은 운영자용이며 사용자 말에는 넣지 않습니다.

## 조건 적용

| 조건 카드 칸 | 적용 |
|---|---|
| `max_bus_headway_min` | 가장 짧은 배차가 이 값 이하인 매물만 남김 |
| `max_walk_to_station_min` | 가까운 역까지 도보 시간이 이 값 이하인 매물만 남김 |
| `priorities`에 `bus_headway` | 배차 짧은 순으로 정렬 |

- 교통 조건이 있으면 엔진에서 20곳을 받아 거른 뒤 5곳만 보여 줍니다.
- 조건에 맞지 않는 곳은 빼고 몇 곳을 뺐는지 알립니다. 좌표를 모르는 곳은 빼지 않고 "위치 정보가 아직 없어 확인하지 못했다"고 알립니다.
- 모두 맞지 않으면 교통이 나은 순으로 보여 주고 그 사실을 알립니다.

## 남은 일

- 카카오맵이 켜진 REST 키(또는 브이월드 키)를 받으면 `scripts/geocode_buildings.py`로 좌표를 채웁니다. 지금 `.env`의 카카오 키는 로그인 앱 키라 403입니다.
- 서버를 여러 대 띄우면 좌표 캐시를 공용 DB 테이블로 옮깁니다(팀 합의 필요).
- 통근 시간·환승은 추천 엔진의 `KakaoCommuteProvider`(같은 카카오 키 필요)를 연결하면 됩니다.
