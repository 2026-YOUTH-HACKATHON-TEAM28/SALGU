import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import type { FastifyInstance } from 'fastify';
import { buildApp } from '../../src/server/app.js';
import { Store } from '../../src/server/store.js';
import { config } from '../../src/server/config.js';
import type { ChatState, ScheduleItem } from '../../src/shared/types.js';

let app: FastifyInstance;
let cookie = '';

const json = { 'content-type': 'application/json' };
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

beforeAll(async () => {
  app = await buildApp({ ...config, timeScale: 2000, clientDir: '__none__' }, new Store(null));
  const res = await app.inject({ method: 'POST', url: '/api/auth/mock-login', headers: json, payload: {} });
  cookie = String(res.headers['set-cookie']).split(';')[0] ?? '';
});
afterAll(async () => app.close());

const call = async <T>(method: 'GET' | 'POST' | 'DELETE', url: string, payload?: unknown) => {
  const body = method === 'POST' ? (payload ?? {}) : payload;
  const res = await app.inject({
    method,
    url,
    headers: body === undefined ? { cookie } : { ...json, cookie },
    payload: body as object,
  });
  return { status: res.statusCode, body: (res.body ? res.json() : null) as T };
};

describe('세션', () => {
  it('로그인 전에는 대화 API 를 막아요', async () => {
    const res = await app.inject({ method: 'GET', url: '/api/chats' });
    expect(res.statusCode).toBe(401);
  });
  it('세션 쿠키는 HttpOnly, SameSite=Lax', async () => {
    const res = await app.inject({ method: 'POST', url: '/api/auth/guest', headers: json, payload: {} });
    expect(String(res.headers['set-cookie'])).toMatch(/HttpOnly/);
    expect(String(res.headers['set-cookie'])).toMatch(/SameSite=Lax/);
  });
  it('다른 사이트에서 보낸 쓰기 요청은 막아요', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/api/chats',
      headers: { ...json, cookie, origin: 'https://evil.example' },
      payload: {},
    });
    expect(res.statusCode).toBe(403);
  });
  it('JSON 이 아닌 본문은 받지 않아요', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/api/auth/guest',
      headers: { 'content-type': 'text/plain' },
      payload: 'x',
    });
    expect(res.statusCode).toBe(415);
  });
});

describe('집 찾기 흐름(mock)', () => {
  let chat: ChatState;

  it('말에서 조건을 뽑아 조건 카드', async () => {
    chat = (await call<ChatState>('POST', '/api/chats')).body;
    const r = await call<ChatState>('POST', `/api/chats/${chat.id}/messages`, {
      text: '여의도역으로 출근해요. 월세 60만 원 이하, 보증금 1000만 원이면 좋겠어요',
    });
    expect(r.status).toBe(200);
    chat = r.body;
    expect(chat.conditions.workplace?.value).toBe('yeouido');
    expect(chat.conditions.rent).toMatchObject({ value: 60, source: 'said' });
    expect(chat.conditions.deposit).toMatchObject({ value: 1000, source: 'said' });
    expect(chat.messages.at(-1)?.cards[0]?.kind).toBe('cond');
  });

  it('찾기: 동네 3곳, 말하지 않은 출퇴근은 살구가 채운 값', async () => {
    chat = (await call<ChatState>('POST', `/api/chats/${chat.id}/actions`, { type: 'search' })).body;
    expect(chat.stage).toBe('dong');
    expect(chat.search?.dongs).toHaveLength(3);
    expect(chat.conditions.maxCommute).toMatchObject({ value: 40, source: 'filled' });
    expect(chat.conditions.maxCommute?.reason).toBeTruthy();
  });

  it('그 자리에서 월세를 바꾸면 말씀하신 조건', async () => {
    chat = (
      await call<ChatState>('POST', `/api/chats/${chat.id}/actions`, {
        type: 'setCond',
        key: 'rent',
        value: 65,
      })
    ).body;
    expect(chat.conditions.rent).toMatchObject({ value: 65, source: 'said' });
    const bad = await call<{ message: string }>('POST', `/api/chats/${chat.id}/actions`, {
      type: 'setCond',
      key: 'rent',
      value: -3,
    });
    expect(bad.status).toBe(409);
  });

  it('입주일·계약 기간 없이는 전화하지 않아요', async () => {
    chat = (
      await call<ChatState>('POST', `/api/chats/${chat.id}/actions`, {
        type: 'prepCalls',
        dongIds: chat.selectedDongIds,
      })
    ).body;
    expect(chat.prep?.dongIds).toHaveLength(3);
    const r = await call<{ error: string }>('POST', `/api/chats/${chat.id}/actions`, { type: 'startCalls' });
    expect(r.status).toBe(409);
    expect(r.body.error).toBe('prep_required');
  });

  it('통화가 끝나면 매물 확인 카드와 상태', async () => {
    await call('POST', `/api/chats/${chat.id}/actions`, {
      type: 'updatePrep',
      patch: { moveIn: '12월 초', term: '2년', visitSlot: 'sat-pm' },
    });
    chat = (await call<ChatState>('POST', `/api/chats/${chat.id}/actions`, { type: 'startCalls' })).body;
    expect(chat.batch?.calls).toHaveLength(9);
    expect(chat.live).toBe(true);
    expect(chat.batch?.calls.every((c) => c.status === 'waiting')).toBe(true);
    for (let i = 0; i < 40 && chat.live; i++) {
      await sleep(100);
      chat = (await call<ChatState>('GET', `/api/chats/${chat.id}`)).body;
    }
    expect(chat.batch?.doneAt).toBeTruthy();
    expect(chat.stage).toBe('check');
    expect(chat.batch?.calls.every((c) => c.status === 'done' && c.outcome)).toBe(true);
    for (const l of chat.listings) {
      expect(['registry_wait', 'recommend', 'caution', 'exclude']).toContain(l.check);
      if (l.registryReply === 'will_send') expect(l.detail?.ruleVersion).toBe('r1-2026-11');
    }
  });

  it('바뀐 게 없으면 204', async () => {
    const r = await app.inject({
      method: 'GET',
      url: `/api/chats/${chat.id}?rev=${chat.rev}`,
      headers: { cookie },
    });
    expect(r.statusCode).toBe(204);
  });

  it('미팅: 확정 전화 뒤 확정된 방문만 일정에', async () => {
    const r = await call<ChatState>('POST', `/api/chats/${chat.id}/actions`, {
      type: 'planVisits',
      includeCaution: true,
    });
    chat = r.body;
    if (!chat.visits.length) return; // 추천·주의 매물이 없는 시나리오
    expect(chat.visits.every((v) => v.status === 'requesting')).toBe(true);
    for (let i = 0; i < 40 && chat.live; i++) {
      await sleep(100);
      chat = (await call<ChatState>('GET', `/api/chats/${chat.id}`)).body;
    }
    expect(chat.visits.every((v) => v.status !== 'requesting')).toBe(true);
    const sched = (await call<{ items: ScheduleItem[] }>('GET', '/api/schedule')).body;
    const confirmed = chat.visits.filter((v) => v.status === 'confirmed');
    expect(sched.items).toHaveLength(confirmed.length);
    for (const v of confirmed)
      expect(chat.listings.find((l) => l.id === v.listingId)?.contact).toBe('confirmed');
  });

  it('다른 사람의 대화는 볼 수 없어요', async () => {
    const res = await app.inject({ method: 'POST', url: '/api/auth/guest', headers: json, payload: {} });
    const other = String(res.headers['set-cookie']).split(';')[0] ?? '';
    const r = await app.inject({ method: 'GET', url: `/api/chats/${chat.id}`, headers: { cookie: other } });
    expect(r.statusCode).toBe(404);
  });
});

describe('맞는 동네가 없을 때', () => {
  it('넓혀본 조건으로 표시하고 원래 값을 기억', async () => {
    let chat = (await call<ChatState>('POST', '/api/chats')).body;
    chat = (
      await call<ChatState>('POST', `/api/chats/${chat.id}/messages`, {
        text: '강남역 출근, 월세 30만 원 이하, 출퇴근 20분 이내',
      })
    ).body;
    chat = (await call<ChatState>('POST', `/api/chats/${chat.id}/actions`, { type: 'search' })).body;
    const card = chat.messages.at(-1)?.cards[0];
    expect(card?.kind).toBe('noMatch');
    chat = (
      await call<ChatState>('POST', `/api/chats/${chat.id}/actions`, {
        type: 'widen',
        key: 'maxCommute',
        value: 30,
      })
    ).body;
    expect(chat.conditions.maxCommute).toMatchObject({ value: 30, source: 'widened', original: 20 });
    chat = (
      await call<ChatState>('POST', `/api/chats/${chat.id}/actions`, { type: 'resetCond', key: 'maxCommute' })
    ).body;
    expect(chat.conditions.maxCommute).toMatchObject({ value: 20, source: 'said' });
  });

  it('주민등록번호는 저장 전에 가려요', async () => {
    let chat = (await call<ChatState>('POST', '/api/chats')).body;
    chat = (
      await call<ChatState>('POST', `/api/chats/${chat.id}/messages`, {
        text: '990101-1234567 여의도 월세 50',
      })
    ).body;
    expect(JSON.stringify(chat)).not.toContain('1234567');
  });
});

describe('보안 헤더', () => {
  it('지도 타일이 막히지 않게 출처는 도메인까지 보내요', async () => {
    const res = await app.inject({ method: 'GET', url: '/api/health' });
    expect(res.headers['referrer-policy']).toBe('strict-origin-when-cross-origin');
  });
});

describe('카카오맵 허용', () => {
  it('CSP 가 카카오맵 SDK 본체(kakaocdn)와 지도 그림을 막지 않아요', async () => {
    const res = await app.inject({ method: 'GET', url: '/api/health' });
    const csp = String(res.headers['content-security-policy']);
    expect(csp).toMatch(/script-src[^;]*https:\/\/\*\.kakaocdn\.net/);
    expect(csp).toMatch(/img-src[^;]*https:\/\/\*\.kakaocdn\.net/);
    expect(csp).toMatch(/img-src[^;]*https:\/\/\*\.daumcdn\.net/);
  });
});
