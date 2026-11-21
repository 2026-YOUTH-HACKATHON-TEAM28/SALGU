"""실거래 건물 주소와 지하철역 이름을 좌표로 바꿔 로컬 캐시(geocode.CACHE_FILE)에 채운다.

추천할 때도 후보 주소를 그때그때 찾지만, 미리 채워 두면 첫 검색이 빠르고 API 한도를 아낀다.
공용 DB에는 쓰지 않는다(읽기만). 이미 캐시에 있는 주소는 다시 묻지 않으므로 여러 번 돌려도 된다.

필요한 것: .env의 SALGU_DB_*와 지오코딩 키
  GEOCODER=kakao  → KAKAO_REST_API_KEY (카카오맵이 켜진 앱의 REST 키, 하루 10만 건)
  GEOCODER=vworld → VWORLD_API_KEY      (역 이름 검색은 지원하지 않음)

  .venv/Scripts/python scripts/geocode_buildings.py --dry-run     # 몇 건인지만
  .venv/Scripts/python scripts/geocode_buildings.py --limit 100   # 시험 삼아 100건
  .venv/Scripts/python scripts/geocode_buildings.py               # 전체
"""
import argparse
import asyncio
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from salgu_chat import geocode, recommender  # noqa: E402

SQL_ADDRESSES = """
SELECT DISTINCT region_address || ' ' || lot_address AS address FROM (
  SELECT region_address, lot_address FROM public.officetel_rentals
  UNION SELECT region_address, lot_address FROM public.multifamily_rentals
) t WHERE region_address IS NOT NULL AND lot_address IS NOT NULL
"""
SQL_STATIONS = "SELECT DISTINCT station_name FROM public.subway_stations"


async def fetch(*sqls):
    """SQL마다 첫 열 목록. 이벤트 루프 하나에서 읽고 연결을 닫는다."""
    from sqlalchemy import text
    engine = recommender._runner._db()
    try:
        async with engine.connect() as conn:
            return [[r[0] for r in (await conn.execute(text(sql))).all()] for sql in sqls]
    finally:
        await engine.dispose()


def run(names, fn, workers, geocoder, label):
    """names를 fn으로 찾는다. 키가 거부되면 멈춘다."""
    found = done = 0
    started = time.time()
    with ThreadPoolExecutor(workers) as pool:
        for i in range(0, len(names), 200):
            for pos in pool.map(fn, names[i:i + 200]):
                done += 1
                found += pos is not None
            geocoder.save()
            print(f"  {label} {done}/{len(names)} (좌표 {found}) {time.time() - started:.0f}초", flush=True)
            if geocoder.disabled:
                print(f"  중단: {geocoder.disabled}")
                break
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="건수만 세고 API는 부르지 않음")
    ap.add_argument("--limit", type=int, default=0, help="새로 찾을 주소 수 상한 (0 = 전체)")
    ap.add_argument("--workers", type=int, default=4, help="동시 요청 수")
    ap.add_argument("--skip-stations", action="store_true", help="역 이름 좌표는 찾지 않음")
    args = ap.parse_args()

    if not recommender.configured():
        sys.exit(".env에 SALGU_DB_HOST/USER/PASSWORD가 없습니다.")
    g = geocode.Geocoder()
    addresses, stations = asyncio.run(fetch(SQL_ADDRESSES, SQL_STATIONS))
    if args.skip_stations:
        stations = []
    todo = [a for a in addresses if not g.known(a)]
    if args.limit:
        todo = todo[:args.limit]
    todo_st = [f"{s}역" for s in stations if not g.known(geocode.PLACE + f"{s}역")]
    print(f"건물 주소 {len(addresses)}개 중 새로 찾을 것 {len(todo)}개, 역 {len(todo_st)}개 "
          f"(캐시 {g.cache_file}, 공급자 {g.provider})")
    if args.dry_run:
        return
    if not g.can_lookup:
        sys.exit(f"지오코딩을 할 수 없습니다: {g.disabled}. .env에 키를 넣어 주세요.")
    if todo and g.locate(todo[0]) is None and g.disabled:  # 키부터 확인
        sys.exit(f"지오코딩 키가 거부됐습니다: {g.disabled}")

    n = run(todo, g.locate, args.workers, g, "건물")
    m = run(todo_st, g.locate_place, args.workers, g, "역") if todo_st and not g.disabled else 0
    g.save()
    print(f"끝: 건물 좌표 {n}개, 역 좌표 {m}개 새로 찾음. 캐시 {len(g)}개. 챗봇 서버를 다시 띄우면 역 좌표가 반영됩니다.")


if __name__ == "__main__":
    main()
