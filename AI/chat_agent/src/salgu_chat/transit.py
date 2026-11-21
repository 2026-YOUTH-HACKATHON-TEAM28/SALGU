"""매물 좌표 → 주변 대중교통 지표 (버스 배차 간격, 가까운 지하철역, 막차).

공용 DB의 공공데이터만 쓴다. 외부 API는 부르지 않는다.
- 버스: bus_stops(정류소 좌표) + bus_route_stops(정류소별 노선) + bus_routes(노선별 배차, '평일공동배차' 시트)
- 지하철: subway_stations(역 이름·호선) + subway_first_last(첫차·막차, day_code '1' = 평일)
- 지하철역 좌표는 DB에 없어서, 이름이 'OO역'으로 시작하는 버스 정류소들의 좌표로 대신한다(추정).

DB에서 한 번 읽어 메모리에 색인(TransitIndex)을 만들고, 이후 계산은 순수 파이썬으로 한다.
"""
import math
import re
import statistics

BUS_RADIUS_M = 400        # 걸어서 5분 안팎 정류소
STATION_RADIUS_M = 1500   # 이보다 먼 역은 '가까운 역 없음'
WALK_M_PER_MIN = 75       # 평균 보행 속도(분당 m)
DETOUR = 1.3              # 직선거리 → 실제 걷는 길 보정
STATION_SPREAD_M = 800    # 같은 역 이름 정류소가 이보다 멀리 흩어지면 바깥 것은 버린다
BUS_TYPES = ("간선", "지선", "마을", "광역", "순환")  # 공항·관광·한강·심야(형식 없음)는 생활 이동과 무관
WEEKDAY_SHEET = "평일공동배차"

SQL_ROUTES = """
SELECT DISTINCT ON (route_name) route_name, route_type, headway, min_headway, max_headway, first_time, last_time
FROM public.bus_routes
WHERE source_sheet = :sheet AND headway > 0 AND route_type = ANY(:types)
ORDER BY route_name, source_row
"""
SQL_STOPS = """
SELECT s.node_id, s.stop_name, s.longitude::float AS lon, s.latitude::float AS lat,
       array_agg(DISTINCT rs.route_name) AS routes
FROM public.bus_stops s JOIN public.bus_route_stops rs ON rs.node_id = s.node_id
WHERE s.longitude IS NOT NULL AND s.latitude IS NOT NULL
GROUP BY s.node_id, s.stop_name, s.longitude, s.latitude
"""
# 이름에 '역'이 든 정류소. 어느 역인지는 파이썬에서 맞춘다(station_names_in) — DB 정규식 조인은 너무 느리다
SQL_STATION_STOPS = """
SELECT stop_name, longitude::float AS lon, latitude::float AS lat FROM public.bus_stops
WHERE stop_name LIKE '%역%' AND longitude IS NOT NULL AND latitude IS NOT NULL
"""
# 'OO역'이 정류소 이름의 처음 또는 구분자 뒤에 있을 때만 (예: '홍대입구역1번출구', '경의선숲길공원(홍대입구역3번출구)',
# '지하철2호선신촌역'). '남구로역'에서 '구로'를 뽑지 않는다
_STATION_IN_STOP = re.compile(r"(?:^|(?<=[.·(\s])|(?<=호선))([^\s.·()]+?)역")
SQL_LINES = "SELECT station_name, array_agg(DISTINCT line_name ORDER BY line_name) AS lines FROM public.subway_stations GROUP BY 1"
SQL_FIRST_LAST = """
SELECT station_name, min(first_time_service_seconds) AS first_s, max(last_time_service_seconds) AS last_s
FROM public.subway_first_last WHERE day_code = '1' GROUP BY 1
"""


def distance_m(lon1, lat1, lon2, lat2):
    """두 좌표 사이 직선거리(m, 하버사인)."""
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def walk_min(meters):
    """직선거리 → 걷는 시간(분, 올림). 길이 굽는 것을 DETOUR로 보정한다."""
    return max(1, math.ceil(meters * DETOUR / WALK_M_PER_MIN))


def clock(seconds):
    """운행 기준 초(자정을 넘으면 24시 이상) → 'HH:MM'. 89580 → '00:53'"""
    if seconds is None:
        return None
    m = int(seconds) // 60
    return f"{m // 60 % 24:02d}:{m % 60:02d}"


def _num(v):
    return None if v is None else int(round(float(v)))


def station_names_in(stop_name, known):
    """정류소 이름 → 그 안에 든 역 이름들(known에 있는 것만). '신촌역.신촌오거리' → ['신촌']"""
    return [m for m in _STATION_IN_STOP.findall(stop_name or "") if m in known]


def cluster_station(points):
    """같은 역 이름 정류소 좌표들 → 역 좌표(중앙값 근처만 평균). 멀리 떨어진 동명 정류소는 버린다."""
    if not points:
        return None
    mlon = statistics.median(p[0] for p in points)
    mlat = statistics.median(p[1] for p in points)
    near = [p for p in points if distance_m(mlon, mlat, p[0], p[1]) <= STATION_SPREAD_M]
    if not near:
        return None
    return (sum(p[0] for p in near) / len(near), sum(p[1] for p in near) / len(near))


class TransitIndex:
    """정류소·노선·역 색인. from_rows로 만들고 near()로 좌표별 지표를 얻는다."""

    def __init__(self, stops, routes, stations):
        self.stops = stops        # [{"name", "lon", "lat", "routes": [route_name]}]
        self.routes = routes      # {route_name: {"type", "headway", "min", "max", "first", "last"}}
        self.stations = stations  # [{"name", "lon", "lat", "lines": [..], "first", "last"}]

    @classmethod
    def from_rows(cls, route_rows, stop_rows, station_stop_rows, line_rows, first_last_rows, station_coords=None):
        """station_coords: {역 이름: (lon, lat)} — 정류소 이름으로 위치를 못 찾은 역에 쓴다(지오코딩 캐시)."""
        routes = {r["route_name"]: {"type": r["route_type"], "headway": _num(r["headway"]),
                                    "min": _num(r["min_headway"]), "max": _num(r["max_headway"]),
                                    "first": r["first_time"], "last": r["last_time"]}
                  for r in route_rows}
        stops = []
        for r in stop_rows:
            names = [n for n in (r["routes"] or []) if n in routes]
            if names:
                stops.append({"name": r["stop_name"], "lon": float(r["lon"]), "lat": float(r["lat"]),
                              "routes": sorted(set(names))})
        lines = {r["station_name"]: list(r["lines"] or []) for r in line_rows}
        points = {}
        for r in station_stop_rows:
            for name in station_names_in(r["stop_name"], lines):
                points.setdefault(name, []).append((float(r["lon"]), float(r["lat"])))
        times = {r["station_name"]: (r["first_s"], r["last_s"]) for r in first_last_rows}
        stations = []
        for name in sorted(set(points) | (set(station_coords or {}) & set(lines))):
            pos = cluster_station(points.get(name)) or (station_coords or {}).get(name)
            if pos:
                first, last = times.get(name, (None, None))
                stations.append({"name": name, "lon": pos[0], "lat": pos[1], "lines": lines.get(name, []),
                                 "first": clock(first), "last": clock(last)})
        return cls(stops, routes, stations)

    def near(self, lon, lat):
        """좌표 → {"bus": {...}|None, "station": {...}|None}

        bus: 반경 BUS_RADIUS_M 안 정류소에 서는 노선 중 배차가 가장 짧은 노선과, 정류소·노선 수
        station: STATION_RADIUS_M 안의 가장 가까운 지하철역(추정 좌표)"""
        dlat = BUS_RADIUS_M / 111000
        dlon = BUS_RADIUS_M / (111000 * math.cos(math.radians(lat)))
        best = {}  # route_name → (거리, 정류소 이름)
        n_stops = 0
        for s in self.stops:
            if abs(s["lat"] - lat) > dlat or abs(s["lon"] - lon) > dlon:
                continue
            d = distance_m(lon, lat, s["lon"], s["lat"])
            if d > BUS_RADIUS_M:
                continue
            n_stops += 1
            for name in s["routes"]:
                if name not in best or d < best[name][0]:
                    best[name] = (d, s["name"])
        bus = None
        if best:
            ranked = sorted(best, key=lambda n: (self.routes[n]["headway"], best[n][0], n))
            top = ranked[0]
            info, (d, stop) = self.routes[top], best[top]
            bus = {"route": top, "type": info["type"], "headway_min": info["headway"],
                   "headway_range": [info["min"], info["max"]], "first": info["first"], "last": info["last"],
                   "stop": stop, "walk_min": walk_min(d), "stops_nearby": n_stops, "routes_nearby": len(best),
                   "frequent_routes": [n for n in ranked if self.routes[n]["headway"] <= 10][:5]}
        station = None
        for st in self.stations:
            d = distance_m(lon, lat, st["lon"], st["lat"])
            if d <= STATION_RADIUS_M and (station is None or d < station[0]):
                station = (d, st)
        if station:
            d, st = station
            station = {"name": f"{st['name']}역", "lines": st["lines"], "walk_min": walk_min(d),
                       "distance_m": round(d), "first": st["first"], "last": st["last"], "estimated_position": True}
        return {"bus": bus, "station": station}


async def load_index(session, station_coords=None):
    """DB(AsyncSession 또는 AsyncConnection) → TransitIndex. 처음 한 번만 부른다(수 초 걸림)."""
    from sqlalchemy import text

    async def rows(sql, **params):
        return (await session.execute(text(sql), params)).mappings().all()

    return TransitIndex.from_rows(
        await rows(SQL_ROUTES, sheet=WEEKDAY_SHEET, types=list(BUS_TYPES)),
        await rows(SQL_STOPS),
        await rows(SQL_STATION_STOPS),
        await rows(SQL_LINES),
        await rows(SQL_FIRST_LAST),
        station_coords,
    )


def passes(metric, max_bus_headway_min=None, max_walk_to_station_min=None):
    """교통 조건을 만족하는지. 지표를 모르면(None) None을 돌려준다(거르지 않음)."""
    if metric is None:
        return None
    ok = True
    if max_bus_headway_min is not None:
        bus = metric.get("bus")
        ok = ok and bool(bus) and bus["headway_min"] <= max_bus_headway_min
    if max_walk_to_station_min is not None:
        st = metric.get("station")
        ok = ok and bool(st) and st["walk_min"] <= max_walk_to_station_min
    return ok


def describe(metric):
    """지표 → 짧은 설명. 예: '신촌역(2호선) 걸어서 6분 · 버스 서대문03 배차 5분'"""
    if not metric:
        return None
    parts = []
    st = metric.get("station")
    if st:
        lines = "·".join(l.lstrip("0") for l in st["lines"])
        parts.append(f"{st['name']}{f'({lines})' if lines else ''} 걸어서 {st['walk_min']}분")
    bus = metric.get("bus")
    if bus:
        parts.append(f"버스 {bus['route']} 배차 {bus['headway_min']}분")
    return " · ".join(parts) or None
