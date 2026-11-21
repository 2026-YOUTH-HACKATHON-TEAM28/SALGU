"""매물 주소 → 좌표(경도, 위도). 실거래 DB에는 좌표가 없어서 주소로 찾는다.

- 결과는 로컬 파일(GEO_CACHE_FILE, 기본 .cache/geo/coords.json)에 쌓아 두고 다시 묻지 않는다.
  scripts/geocode_buildings.py로 실거래 건물 전체를 미리 채울 수 있다.
- 공급자: GEOCODER=kakao(기본, KAKAO_REST_API_KEY — 카카오맵이 켜진 앱의 REST 키)
          GEOCODER=vworld(VWORLD_API_KEY — 브이월드 지오코더)
- 키가 없거나 거부되면(401·403) 이 프로세스에서는 더 묻지 않고 캐시에 있는 좌표만 쓴다.
"""
import json
import threading
import urllib.error
import urllib.parse
import urllib.request

from . import config

CACHE_FILE = config.ROOT / ".cache" / "geo" / "coords.json"
if config.ENV.get("GEO_CACHE_FILE"):
    CACHE_FILE = config.ROOT / config.ENV["GEO_CACHE_FILE"]
TIMEOUT_S = 5
SEOUL = (126.76, 127.19, 37.41, 37.72)  # 경도·위도 범위. 밖이면 잘못 찾은 것으로 본다


def _norm(address):
    return " ".join((address or "").split())


def _in_seoul(lon, lat):
    return SEOUL[0] <= lon <= SEOUL[1] and SEOUL[2] <= lat <= SEOUL[3]


def _get_json(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as res:
        return json.loads(res.read().decode("utf-8"))


def kakao(address, key):
    """카카오 로컬 주소 검색. 지번·도로명 모두 된다. → (lon, lat) 또는 None"""
    q = urllib.parse.urlencode({"query": address, "size": 1})
    data = _get_json(f"https://dapi.kakao.com/v2/local/search/address.json?{q}",
                     {"Authorization": f"KakaoAK {key}"})
    docs = data.get("documents") or []
    return (float(docs[0]["x"]), float(docs[0]["y"])) if docs else None


def kakao_place(name, key):
    """카카오 키워드 검색. 지하철역 분류(SW8)만 본다(같은 이름 가게·건물이 잡히지 않게). → (lon, lat) 또는 None"""
    q = urllib.parse.urlencode({"query": name, "size": 1, "category_group_code": "SW8"})
    data = _get_json(f"https://dapi.kakao.com/v2/local/search/keyword.json?{q}",
                     {"Authorization": f"KakaoAK {key}"})
    docs = data.get("documents") or []
    return (float(docs[0]["x"]), float(docs[0]["y"])) if docs else None


def vworld(address, key):
    """브이월드 주소 → 좌표. 실거래 주소는 지번이라 PARCEL로 묻는다. → (lon, lat) 또는 None"""
    q = urllib.parse.urlencode({"service": "address", "request": "getcoord", "version": "2.0", "crs": "epsg:4326",
                                "address": address, "refine": "true", "simple": "false", "format": "json",
                                "type": "parcel", "key": key})
    data = _get_json(f"https://api.vworld.kr/req/address?{q}").get("response") or {}
    if data.get("status") != "OK":
        if data.get("status") == "ERROR":
            raise PermissionError((data.get("error") or {}).get("text") or "vworld error")
        return None
    p = (data.get("result") or {}).get("point") or {}
    return (float(p["x"]), float(p["y"])) if p.get("x") else None


PROVIDERS = {"kakao": ("KAKAO_REST_API_KEY", kakao), "vworld": ("VWORLD_API_KEY", vworld)}
PLACE = "place:"  # 장소 이름 캐시 키 앞머리 (주소와 섞이지 않게)


class Geocoder:
    """주소 → 좌표. 캐시 우선, 없으면 공급자에게 묻는다(가능할 때만)."""

    def __init__(self, provider=None, key=None, cache_file=CACHE_FILE, lookup=None):
        self.provider = (provider or config.ENV.get("GEOCODER") or "kakao").lower()
        env_key, fn = PROVIDERS.get(self.provider, (None, None))
        self.key = key if key is not None else config.ENV.get(env_key or "", "")
        self._lookup = lookup or fn
        self.cache_file = cache_file
        self.disabled = None if (self.key and self._lookup) else f"{self.provider} 지오코딩 키 없음"
        self._lock = threading.Lock()
        self._cache = self._read()
        self._dirty = 0

    def _read(self):
        try:
            return json.loads(self.cache_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save(self):
        with self._lock:
            if not self._dirty:
                return
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._cache, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.cache_file)
            self._dirty = 0

    @property
    def can_lookup(self):
        return self.disabled is None

    def cached(self, address):
        """캐시만 본다. 없거나 못 찾은 주소면 None."""
        v = self._cache.get(_norm(address))
        return tuple(v) if v else None

    def known(self, address):
        return _norm(address) in self._cache

    def station_coords(self):
        """캐시에 있는 역 좌표 {역 이름(‘역’ 뺌): (lon, lat)}"""
        return {k[len(PLACE):-1]: tuple(v) for k, v in self._cache.items()
                if k.startswith(PLACE) and k.endswith("역") and v}

    def locate_place(self, name):
        """장소 이름(예: '망원역') → 좌표. 카카오 키워드 검색만 지원한다."""
        if self.provider != "kakao":
            return None
        return self.locate(name, _place=True)

    def locate(self, address, _place=False):
        """→ (lon, lat) 또는 None. 못 찾은 주소도 캐시에 None으로 남겨 다시 묻지 않는다."""
        addr = _norm(address)
        if not addr:
            return None
        lookup = kakao_place if _place else self._lookup
        if _place:
            addr = PLACE + addr
        if addr in self._cache:
            v = self._cache[addr]
            return tuple(v) if v else None
        if not self.can_lookup:
            return None
        try:
            pos = lookup(addr[len(PLACE):] if _place else addr, self.key)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                self.disabled = f"{self.provider} 키 거부({e.code})"
            return None
        except PermissionError as e:
            self.disabled = f"{self.provider} 키 거부({e})"
            return None
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError, OSError):
            return None  # 일시 오류는 캐시하지 않는다
        if pos and not _in_seoul(*pos):
            pos = None
        with self._lock:
            self._cache[addr] = list(pos) if pos else None
            self._dirty += 1
        return pos

    def __len__(self):
        return len(self._cache)
