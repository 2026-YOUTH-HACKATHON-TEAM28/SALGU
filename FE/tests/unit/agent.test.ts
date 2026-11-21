import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';
import type { FastifyInstance } from 'fastify';
import { buildApp } from '../../src/server/app.js';
import { Store } from '../../src/server/store.js';
import { config } from '../../src/server/config.js';
import { mapAgentCard, type AgentCard } from '../../src/server/chatAgent.js';
import { WORKPLACES } from '../../src/server/mock/data.js';
import type { ChatState } from '../../src/shared/types.js';

/* 조건 카드 예시 1(contracts/condition_card.md) */
const CARD: AgentCard = {
  version: '0.2-draft',
  conditions: {
    housing_types: {
      value: ['officetel', 'villa'],
      source: 'inferred',
      evidence: '깨끗하고',
      reason: "'깨끗한'을 오피스텔·신축 빌라로 해석",
    },
    max_building_age_years: { value: 10, source: 'inferred', evidence: '깨끗하고', reason: '준공 10년 이내' },
    deposit_manwon: { value: 1000, approx: true, source: 'stated', evidence: '1000/50 정도' },
    monthly_rent_manwon: { value: 50, approx: true, source: 'stated', evidence: '1000/50 정도' },
    price_band: {
      value: 'median_or_below',
      source: 'inferred',
      evidence: '싼',
      reason: '같은 조건 실거래의 가운데~아래 구간',
    },
    workplace: { value: 'place', label: '강남역', source: 'stated', evidence: '회사가 강남역' },
    max_commute_min: {
      value: 40,
      source: 'inferred',
      evidence: '출퇴근 편했으면',
      reason: '출근 시간대 통근 40분 이내',
    },
    max_transfers: { value: 1, source: 'inferred', evidence: '출퇴근 편했으면', reason: '환승 1회 이하' },
    min_floor: { value: 1, source: 'stated', evidence: '반지하는 싫고' },
  },
  priorities: ['price'],
  unverifiable: [{ phrase: '조용한', message: '데이터로 확인할 수 없어요' }],
  clarifications: [],
};

describe('조건 카드(v0.2) -> 화면 조건', () => {
  it('말한 조건은 said, 추론은 filled(이유), 반영 못 하는 건 따로', () => {
    const m = mapAgentCard(CARD, WORKPLACES, new Date('2026-11-21'));
    const by = Object.fromEntries(m.conds.map((c) => [c.key, c]));
    expect(by.workplace).toMatchObject({ value: 'gangnam', source: 'said' });
    expect(by.deposit).toMatchObject({ value: 1000, source: 'said' });
    expect(by.rent).toMatchObject({ value: 50, source: 'said' });
    expect(by.maxCommute).toMatchObject({
      value: 40,
      source: 'filled',
      reason: '출근 시간대 통근 40분 이내',
    });
    expect(by.builtAfter).toMatchObject({ value: 2016, source: 'filled' });
    expect(by.priceBand).toMatchObject({ value: 'low', source: 'filled' });
    expect(by.priority).toMatchObject({ value: 'price' });
    expect(by.houseType).toBeUndefined(); // 두 유형이면 상관없음
    expect(m.notApplied).toContain('1층 이상');
    expect(m.unverifiable).toEqual(['조용한']);
  });

  it('회사 없이 살 곳만 말하면 그곳을 기준점으로(살구가 정한 값)', () => {
    const m = mapAgentCard(
      {
        conditions: {
          preferred_areas: { value: ['홍대입구역'], source: 'stated', evidence: '홍대입구역 근처' },
        },
      },
      WORKPLACES,
    );
    expect(m.conds[0]).toMatchObject({ key: 'workplace', value: 'hongdae', source: 'filled' });
  });

  it('반려동물·주차 바람은 전화로 확인할 조건으로', () => {
    const m = mapAgentCard(
      {
        conditions: {},
        unverifiable: [
          { phrase: '고양이 키워도 되는 데', message: '데이터로 확인할 수 없어요' },
          { phrase: '주차 되는 곳', message: '데이터로 확인할 수 없어요' },
        ],
      },
      WORKPLACES,
    );
    expect(m.conds).toEqual(
      expect.arrayContaining([
        { key: 'pet', value: true, source: 'said' },
        { key: 'parking', value: true, source: 'said' },
      ]),
    );
  });
});

/* 에이전트 서버를 흉내 내요 */
const realFetch = globalThis.fetch;
function fakeAgent(url: string | URL | Request, init?: RequestInit): Promise<Response> {
  if (!String(url).startsWith('http://agent.test/')) return realFetch(url, init);
  const body = JSON.parse(String(init?.body)) as { session_id: string; message: string };
  return Promise.resolve(
    new Response(
      JSON.stringify({
        session_id: body.session_id,
        type: 'condition_card',
        reply:
          '좋아요! 강남역까지 출퇴근하기 좋은 집으로 찾아볼게요.\n살구 검색 서버에 조건을 보내 집을 요청했습니다.',
        messages: [
          { kind: 'reply', text: '좋아요! 강남역까지 출퇴근하기 좋은 집으로 찾아볼게요.' },
          { kind: 'backend_request', text: '살구 검색 서버에 조건을 보내 집을 요청했습니다.' },
        ],
        card: CARD,
        intent: 'search',
        via: 'rules',
        ready: true,
        missing: [],
        changed: ['workplace'],
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    ),
  );
}

let app: FastifyInstance;
let cookie = '';
const json = { 'content-type': 'application/json' };
beforeAll(async () => {
  vi.stubGlobal('fetch', fakeAgent);
  app = await buildApp(
    { ...config, chatAgentUrl: 'http://agent.test', openaiKey: '', clientDir: '__none__' },
    new Store(null),
  );
  const res = await app.inject({ method: 'POST', url: '/api/auth/mock-login', headers: json, payload: {} });
  cookie = String(res.headers['set-cookie']).split(';')[0] ?? '';
});
afterAll(async () => {
  vi.unstubAllGlobals();
  await app.close();
});

describe('대화 에이전트 연결', () => {
  it('자유로운 말은 에이전트가 이해하고, 첫 답만 보여요', async () => {
    const post = async (url: string, payload: object = {}) =>
      (await app.inject({ method: 'POST', url, headers: { ...json, cookie }, payload })).json() as ChatState;
    const chat = await post('/api/chats');
    const after = await post(`/api/chats/${chat.id}/messages`, {
      text: '회사가 강남역인데 1000/50 정도로 깨끗하고 싼 집',
    });
    const last = after.messages.at(-1)!;
    expect(last.cards[0]?.kind).toBe('cond');
    expect(last.text).toContain('강남역까지 출퇴근하기 좋은 집');
    expect(last.text).not.toContain('검색 서버');
    expect(last.text).toContain('1층 이상');
    expect(last.sources[0]?.kind).toBe('ai');
    expect(after.conditions.workplace).toMatchObject({ value: 'gangnam', source: 'said' });
    // 동네 찾기는 이 서버 계산 엔진이 해요
    const searched = await post(`/api/chats/${chat.id}/actions`, { type: 'search' });
    expect(searched.stage).toBe('dong');
  });
});
