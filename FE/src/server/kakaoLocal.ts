/* 카카오 로컬 API(REST)로 장소·동 이름을 좌표로 바꿔요. 키(KAKAO_REST_API_KEY)가 없거나 실패하면 null.
 * 한 번 찾은 결과는 기억해 두고(하루), 요청은 3초 안에 끝내요. 키 값은 어디에도 남기지 않아요. */

export interface Point {
  name: string;
  lat: number;
  lng: number;
}

const DAY = 24 * 3600 * 1000;

export class KakaoLocal {
  private readonly cache = new Map<string, { at: number; p: Point | null }>();

  constructor(private readonly key: string) {}

  get enabled(): boolean {
    return Boolean(this.key);
  }

  private async get(path: string, query: string): Promise<Record<string, unknown>[] | null> {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 3000);
    try {
      const res = await fetch(`https://dapi.kakao.com${path}?query=${encodeURIComponent(query)}&size=1`, {
        headers: { Authorization: `KakaoAK ${this.key}` },
        signal: ctrl.signal,
      });
      if (!res.ok) {
        console.error(`[kakao] 로컬 API 응답 ${res.status}`);
        return null;
      }
      const body = (await res.json()) as { documents?: Record<string, unknown>[] };
      return body.documents ?? [];
    } catch (err) {
      console.error(`[kakao] 로컬 API 호출 실패: ${(err as Error).name}`);
      return null;
    } finally {
      clearTimeout(timer);
    }
  }

  private async cached(key: string, find: () => Promise<Point | null>): Promise<Point | null> {
    if (!this.enabled) return null;
    const hit = this.cache.get(key);
    if (hit && Date.now() - hit.at < DAY) return hit.p;
    const p = await find();
    this.cache.set(key, { at: Date.now(), p });
    return p;
  }

  /** 장소 이름(역, 학교, 회사) -> 좌표. 서울 기준으로 찾아요 */
  place(name: string): Promise<Point | null> {
    return this.cached(`place:${name}`, async () => {
      const docs = await this.get('/v2/local/search/keyword.json', name);
      const d = docs?.[0];
      if (!d) return null;
      return { name: String(d.place_name ?? name), lat: Number(d.y), lng: Number(d.x) };
    });
  }

  /** '마포구 합정동' -> 동 중심 좌표 */
  region(gu: string, dong: string): Promise<Point | null> {
    return this.cached(`region:${gu} ${dong}`, async () => {
      const docs = await this.get('/v2/local/search/address.json', `서울 ${gu} ${dong}`);
      const d = docs?.[0];
      if (!d) return null;
      return { name: dong, lat: Number(d.y), lng: Number(d.x) };
    });
  }
}
