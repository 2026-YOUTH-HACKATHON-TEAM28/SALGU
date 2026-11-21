import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';
import type { FastifyInstance } from 'fastify';
import { buildApp } from '../../src/server/app.js';
import { Store } from '../../src/server/store.js';
import { config } from '../../src/server/config.js';
import type { ChatState, SessionInfo } from '../../src/shared/types.js';
import { fakeAgentFetch } from '../fixtures/fakeChatAgent.js';

/* BE(카카오 로그인)와 전화 에이전트를 흉내 내요 */
const BE = 'http://be.test';
const PHONE = 'http://phone.test';
const realFetch = globalThis.fetch;
const batches = new Map<string, { reg: string; name: string; polls: number }>();
const seen: { url: string; headers: Record<string, string> }[] = [];

const ok = (body: unknown, init: ResponseInit = {}) =>
  new Response(JSON.stringify(body), {
    status: 200,
    ...init,
    headers: { 'content-type': 'application/json', ...(init.headers ?? {}) },
  });

function fake(input: string | URL | Request, init?: RequestInit): Promise<Response> {
  const url = String(input);
  const headers = Object.fromEntries(new Headers(init?.headers).entries());
  if (url.startsWith(BE)) {
    seen.push({ url, headers });
    const path = url.slice(BE.length);
    if (path.startsWith('/oauth2/authorization/kakao'))
      return Promise.resolve(
        new Response(null, {
          status: 302,
          headers: { location: 'https://kauth.kakao.com/oauth/authorize?client_id=x' },
        }),
      );
    if (path.startsWith('/login/oauth2/code/kakao'))
      return Promise.resolve(
        new Response(null, {
          status: 302,
          headers: { location: `${BE}/`, 'set-cookie': 'JSESSIONID=abc; Path=/; HttpOnly' },
        }),
      );
    if (path === '/api/me')
      return Promise.resolve(
        headers.cookie === 'JSESSIONID=abc'
          ? ok({ id: 42, nickname: '살구' })
          : new Response(null, { status: 401 }),
      );
    if (path === '/logout') return Promise.resolve(new Response(null, { status: 204 }));
  }
  if (url.startsWith(PHONE)) {
    const path = url.slice(PHONE.length);
    if (path === '/api/health') return Promise.resolve(ok({ status: 'ok', mode: 'mock' }));
    if (path === '/api/broker-call-batches' && init?.method === 'POST') {
      const body = JSON.parse(String(init.body)) as { brokers: { reg: string; name: string }[] };
      const b = body.brokers[0]!;
      const id = `b${batches.size + 1}`;
      batches.set(id, { reg: b.reg, name: b.name, polls: 0 });
      return Promise.resolve(
        ok({
          batch_id: id,
          status: 'running',
          calls: [{ call_id: `${id}-c1`, kind: 'inquiry', broker: b, status: 'waiting' }],
        }),
      );
    }
    const m = /^\/api\/broker-call-batches\/(\w+)$/.exec(path);
    if (m) {
      const b = batches.get(m[1]!)!;
      b.polls++;
      return Promise.resolve(
        ok({
          batch_id: m[1],
          status: 'done',
          calls: [
            {
              call_id: `${m[1]}-c1`,
              kind: 'inquiry',
              broker: { reg: b.reg, name: b.name },
              status: 'done',
              outcome: 'has_listing',
              listings: [
                {
                  building: '해든빌라',
                  floor: '3',
                  area_m2: null,
                  deposit_manwon: 1000,
                  monthly_rent_manwon: 60,
                  maintenance_fee_manwon: 5,
                  move_in: '12월 초',
                },
              ],
              broker_slots: [{ start: '2026-11-28T16:00:00+09:00' }],
              quotes: {
                '0': { speaker: 'agent', text: '안녕하세요, 살구 AI 비서입니다.' },
                '1': { speaker: 'broker', text: '3층에 1000에 60 있어요.' },
              },
              unverified: ['listings[0].area_m2'],
            },
          ],
        }),
      );
    }
  }
  return realFetch(input, init);
}

let app: FastifyInstance;
const json = { 'content-type': 'application/json' };
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

beforeAll(async () => {
  vi.stubGlobal('fetch', fakeAgentFetch('http://agent.test', fake as typeof fetch));
  app = await buildApp(
    {
      ...config,
      beUrl: BE,
      phoneAgentUrl: PHONE,
      phoneUniqueReg: false,
      chatAgentUrl: 'http://agent.test',
      kakaoRestKey: '',
      openaiKey: '',
      timeScale: 2000,
      clientDir: '__none__',
    },
    new Store(null),
  );
});
afterAll(async () => {
  vi.unstubAllGlobals();
  await app.close();
});

describe('BE 카카오 로그인 연결', () => {
  it('로그인 시작은 BE 를 거쳐 카카오로 보내요', async () => {
    const r = await app.inject({
      method: 'GET',
      url: '/oauth2/authorization/kakao',
      headers: { host: 'site.test' },
    });
    expect(r.statusCode).toBe(302);
    expect(r.headers.location).toMatch(/^https:\/\/kauth\.kakao\.com\//);
    expect(seen.at(-1)?.headers['x-forwarded-host']).toBe('site.test');
  });

  it('콜백 뒤 BE 주소는 이 사이트 주소로, JSESSIONID 는 브라우저로', async () => {
    const r = await app.inject({ method: 'GET', url: '/login/oauth2/code/kakao?code=c&state=s' });
    expect(r.statusCode).toBe(302);
    expect(r.headers.location).toBe('/');
    expect(String(r.headers['set-cookie'])).toContain('JSESSIONID=abc');
  });

  it('JSESSIONID 로 BE 사용자를 화면 계정과 이어요', async () => {
    const r = await app.inject({ method: 'GET', url: '/api/session', headers: { cookie: 'JSESSIONID=abc' } });
    const s = r.json<SessionInfo>();
    expect(s.kakaoLogin).toBe(true);
    expect(s.user).toMatchObject({ kind: 'kakao', name: '살구' });
    const sg = String(r.headers['set-cookie']).split(';')[0]!;
    // 다시 와도 같은 계정
    const again = await app.inject({
      method: 'GET',
      url: '/api/session',
      headers: { cookie: `JSESSIONID=abc; ${sg}` },
    });
    expect(again.json<SessionInfo>().user?.id).toBe(s.user?.id);
    // 로그아웃하면 BE 세션도 끝내요
    const out = await app.inject({
      method: 'POST',
      url: '/api/auth/logout',
      headers: { ...json, cookie: `JSESSIONID=abc; ${sg}` },
      payload: {},
    });
    expect(out.statusCode).toBe(200);
    expect(seen.at(-1)?.url).toBe(`${BE}/logout`);
    expect(String(out.headers['set-cookie'])).toContain('JSESSIONID=;');
  });

  it('BE 세션이 없으면 계정을 만들지 않아요', async () => {
    const r = await app.inject({ method: 'GET', url: '/api/session', headers: { cookie: 'JSESSIONID=zzz' } });
    expect(r.json<SessionInfo>().user).toBeNull();
  });
});

describe('전화 에이전트 연결', () => {
  let cookie = '';
  const call = async <T>(method: 'GET' | 'POST', url: string, payload?: unknown) => {
    const res = await app.inject({
      method,
      url,
      headers: method === 'POST' ? { ...json, cookie } : { cookie },
      payload: method === 'POST' ? ((payload ?? {}) as object) : undefined,
    });
    return { status: res.statusCode, body: (res.body ? res.json() : null) as T };
  };

  it('문의 통화 결과를 찾은 방으로(확인 못 한 면적은 표시)', async () => {
    const res = await app.inject({ method: 'POST', url: '/api/auth/mock-login', headers: json, payload: {} });
    cookie = String(res.headers['set-cookie']).split(';')[0] ?? '';
    const s = (await call<SessionInfo>('GET', '/api/session')).body;
    expect(s.phoneMode).toBe('mock');

    let chat = (await call<ChatState>('POST', '/api/chats')).body;
    await call('POST', `/api/chats/${chat.id}/messages`, {
      text: '여의도역으로 출근해요. 월세 60만 원 이하, 보증금 1000만 원',
    });
    chat = (await call<ChatState>('POST', `/api/chats/${chat.id}/actions`, { type: 'search' })).body;
    const dongIds = chat.selectedDongIds.slice(0, 1);
    await call('POST', `/api/chats/${chat.id}/actions`, { type: 'prepCalls', dongIds });
    await call('POST', `/api/chats/${chat.id}/actions`, {
      type: 'updatePrep',
      patch: { moveIn: '12월 초', term: '2년', visitSlot: 'sat-pm' },
    });
    chat = (await call<ChatState>('POST', `/api/chats/${chat.id}/actions`, { type: 'startCalls' })).body;
    expect(batches.size).toBe(1);
    expect(chat.batch?.calls).toHaveLength(1);
    expect(chat.messages.at(-1)?.text).toContain('실제로 전화를 걸지는 않아요');

    for (let i = 0; i < 20 && !chat.batch?.doneAt; i++) {
      await sleep(250);
      chat = (await call<ChatState>('GET', `/api/chats/${chat.id}`)).body;
    }
    expect(chat.batch?.doneAt).toBeTruthy();
    expect(chat.batch?.calls[0]).toMatchObject({ status: 'done', outcome: 'has_listing' });
    expect(chat.batch?.calls[0]?.lines[1]).toMatchObject({ who: 'broker' });
    const l = chat.listings[0]!;
    expect(l).toMatchObject({
      building: '해든빌라',
      floor: 3,
      deposit: 1000,
      rent: 60,
      priceVerdict: 'unknown',
    });
    expect(l.unverified).toContain('area');
    expect(l.slots[0]).toBe('2026-11-28T16:00:00');
    expect(chat.stage).toBe('pick');
  });
});
