import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';
import type { FastifyInstance } from 'fastify';
import { buildApp } from '../../src/server/app.js';
import { Store } from '../../src/server/store.js';
import { config } from '../../src/server/config.js';
import { agentSearch, splitAddress } from '../../src/server/dongAgent.js';
import { priceVerdict } from '../../src/server/mock/engine.js';
import type { ChatState } from '../../src/shared/types.js';

/* 추천 엔진(실거래 DB) 결과를 실은 대화 에이전트 응답 */
const cand = (o: Record<string, unknown>) => ({
  housing_type: 'villa',
  rent_type: '월세',
  area_m2: 24,
  floor: 3,
  construction_year: 2015,
  contract_date: '2026-09-12',
  transaction_count: 4,
  reasons: ['최근 12개월 실거래 4건'],
  commute_minutes: null,
  transfers: null,
  station: null,
  is_live_listing: false,
  ...o,
});
const BACKEND = {
  ok: true,
  mock: false,
  source: '추천 엔진(실거래 DB)',
  notes: ['여의도역까지 통근 시간·환승은 아직 계산하지 못해요(교통 데이터 연결 전).'],
  count: 4,
  candidates: [
    cand({
      name: '해든빌라',
      address: '서울특별시 영등포구 신길동 100-1',
      deposit_manwon: 1000,
      monthly_rent_manwon: 55,
      score: 88.2,
      market_median_deposit_manwon: 1000,
      market_median_monthly_rent_manwon: 55,
    }),
    cand({
      name: '신길하우스',
      address: '서울특별시 영등포구 신길동 200-3',
      deposit_manwon: 1000,
      monthly_rent_manwon: 60,
      score: 80,
      market_median_deposit_manwon: 1000,
      market_median_monthly_rent_manwon: 57,
    }),
    cand({
      name: '마포오피스텔',
      address: '서울특별시 마포구 공덕동 5-2',
      housing_type: 'officetel',
      deposit_manwon: 1000,
      monthly_rent_manwon: 65,
      score: 84,
      market_median_deposit_manwon: 1000,
      market_median_monthly_rent_manwon: 63,
    }),
    cand({
      name: '주소없음',
      address: '알 수 없음',
      deposit_manwon: 500,
      monthly_rent_manwon: 40,
      score: 99,
    }),
  ],
};

const realFetch = globalThis.fetch;
const asked: string[] = [];
function fakeAgent(url: string | URL | Request, init?: RequestInit): Promise<Response> {
  if (!String(url).startsWith('http://agent.test/')) return realFetch(url, init);
  const body = JSON.parse(String(init?.body)) as { session_id: string; message: string };
  asked.push(body.message);
  return Promise.resolve(
    new Response(
      JSON.stringify({
        session_id: body.session_id,
        type: 'condition_card',
        reply: '조건으로 찾아봤어요.',
        messages: [{ kind: 'reply', text: '조건으로 찾아봤어요.' }],
        card: {
          conditions: {
            workplace: { value: 'place', label: '여의도역', source: 'stated' },
            deposit_manwon: { value: 1000, source: 'stated' },
            monthly_rent_manwon: { value: 60, source: 'stated' },
          },
        },
        intent: 'search',
        via: 'rules',
        ready: true,
        missing: [],
        changed: [],
        backend: BACKEND,
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    ),
  );
}

describe('추천 후보 -> 동네 카드', () => {
  it("주소를 '구 동'으로 나눠요", () => {
    expect(splitAddress('서울특별시 관악구 신림동 408-15')).toEqual({ gu: '관악구', dong: '신림동' });
    expect(splitAddress('서울특별시 종로구 종로1가 1')).toEqual({ gu: '종로구', dong: '종로1가' });
    expect(splitAddress('알 수 없음')).toBeNull();
  });

  it('동네별로 묶고 점수순, 시세 중앙값을 가격 기준으로', () => {
    const r = agentSearch(BACKEND)!;
    expect(r.dongs.map((d) => d.name)).toEqual(['신길동', '공덕동']);
    const [a] = r.dongs;
    expect(a).toMatchObject({ rank: 1, gu: '영등포구', source: 'agent', dealCount: 8, commute: null });
    expect(a!.buildings).toEqual(['해든빌라', '신길하우스']);
    expect(a!.priceRef).toEqual({ conv: 60, n: 2 }); // 1000만 원 -> 환산 약 4.2만 + 월세 55~57
    expect(a!.brokers.length).toBeGreaterThan(0); // 에이전트가 목록을 안 주면 예시 목록
    // 가격 판단: 같은 동네 시세 중앙값 대비
    expect(priceVerdict(a!.id, 24, 'villa', 1000, 56)).toBe('fair');
    expect(priceVerdict(a!.id, 24, 'villa', 1000, 63)).toBe('slightly_high');
    expect(priceVerdict(a!.id, 24, 'villa', 1000, 75)).toBe('high');
  });

  it('에이전트가 중개사무소 목록을 주면 그 동네 것을 써요', () => {
    const r = agentSearch({
      ...BACKEND,
      brokers: [
        { name: '신길공인중개사사무소', reg_no: '11560-2020-00001', phone: '02-000-0000', dong: '신길동' },
        { name: '공덕공인중개사사무소', reg_no: '11440-2020-00002', phone: '02-000-0001', dong: '공덕동' },
      ],
    } as never)!;
    expect(r.dongs[0]!.brokers).toEqual([
      expect.objectContaining({ name: '신길공인중개사사무소', regNo: '11560-2020-00001' }),
    ]);
  });

  it('예시 응답·오류면 쓰지 않아요', () => {
    expect(agentSearch({ ...BACKEND, mock: true })).toBeNull();
    expect(agentSearch({ ...BACKEND, ok: false })).toBeNull();
  });
});

describe('동네 찾기를 대화 에이전트에 물어요', () => {
  let app: FastifyInstance;
  let cookie = '';
  const json = { 'content-type': 'application/json' };
  beforeAll(async () => {
    vi.stubGlobal('fetch', fakeAgent);
    app = await buildApp(
      {
        ...config,
        chatAgentUrl: 'http://agent.test',
        openaiKey: '',
        phoneAgentUrl: '',
        clientDir: '__none__',
      },
      new Store(null),
    );
    const res = await app.inject({ method: 'POST', url: '/api/auth/mock-login', headers: json, payload: {} });
    cookie = String(res.headers['set-cookie']).split(';')[0] ?? '';
  });
  afterAll(async () => {
    vi.unstubAllGlobals();
    await app.close();
  });
  const call = async <T>(url: string, payload: unknown = {}) =>
    (
      await app.inject({ method: 'POST', url, headers: { ...json, cookie }, payload: payload as object })
    ).json<T>();

  it('찾기 버튼: 조건을 질문으로 보내고 받은 동네로 카드', async () => {
    let chat = await call<ChatState>('/api/chats');
    await call(`/api/chats/${chat.id}/messages`, {
      text: '여의도역으로 출근해요. 월세 60만 원 이하, 보증금 1000만 원',
    });
    asked.length = 0;
    chat = await call<ChatState>(`/api/chats/${chat.id}/actions`, { type: 'search' });
    expect(asked[0]).toContain('회사는 여의도역');
    expect(asked[0]).toContain('보증금 1000만 원');
    expect(chat.stage).toBe('dong');
    expect(chat.search?.dongs.map((d) => d.name)).toEqual(['신길동', '공덕동']);
    const last = chat.messages.at(-1)!;
    expect(last.text).toContain('실거래 추천 엔진');
    expect(last.text).toContain('교통 데이터 연결 전');
    expect(last.sources?.[0]).toMatchObject({ label: '추천 엔진(실거래 DB)', kind: 'real' });

    // 동네 자세히: 근거 실거래는 추천 엔진 후보
    chat = await call<ChatState>(`/api/chats/${chat.id}/messages`, { text: '1번 자세히 알려줘' });
    const detail = chat.messages.at(-1)!.cards[0] as { kind: string; deals: { building: string }[] };
    expect(detail.kind).toBe('dongDetail');
    expect(detail.deals.map((d) => d.building)).toEqual(['해든빌라', '신길하우스']);

    // 전화 준비: 동네의 중개사무소 수로 안내
    chat = await call<ChatState>(`/api/chats/${chat.id}/actions`, {
      type: 'prepCalls',
      dongIds: [chat.search!.dongs[0]!.id],
    });
    expect(chat.messages.at(-1)!.text).toMatch(/신길동의 등록 중개사무소 \d곳/);
  });
});
