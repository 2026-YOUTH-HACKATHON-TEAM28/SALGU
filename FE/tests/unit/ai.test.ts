import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';
import type { FastifyInstance } from 'fastify';
import { buildApp } from '../../src/server/app.js';
import { Store } from '../../src/server/store.js';
import { config } from '../../src/server/config.js';
import type { ChatState } from '../../src/shared/types.js';

/* OpenAI 를 실제로 부르지 않고 응답을 흉내 내요. */
const calls: { instructions: string; input: string; schema: boolean }[] = [];
const realFetch = globalThis.fetch;

function fakeOpenAi(url: string | URL | Request, init?: RequestInit): Promise<Response> {
  if (!String(url).startsWith('https://api.openai.com/')) return realFetch(url, init);
  const body = JSON.parse(String(init?.body)) as { instructions: string; input: string; text?: unknown };
  calls.push({ instructions: body.instructions, input: body.input, schema: Boolean(body.text) });
  const text = body.text
    ? JSON.stringify({
        workplace: body.input.includes('테헤란') ? 'yeoksam' : null,
        rent: body.input.includes('오십') ? 50 : null,
        deposit: null,
        maxCommute: null,
        maxTransfer: null,
        houseType: null,
        builtAfter: null,
        pet: null,
        parking: -1 as unknown as null, // 형식이 틀린 값은 버려져야 해요
        commercial: null,
      })
    : '이사 첫 주에는 전입신고와 확정일자를 먼저 챙기세요 — 그다음 공과금 명의를 바꾸면 돼요. **꼭** 확인해요.';
  return Promise.resolve(
    new Response(
      JSON.stringify({ output: [{ type: 'message', content: [{ type: 'output_text', text }] }] }),
      {
        status: 200,
        headers: { 'content-type': 'application/json' },
      },
    ),
  );
}

let app: FastifyInstance;
let cookie = '';
const json = { 'content-type': 'application/json' };

beforeAll(async () => {
  vi.stubGlobal('fetch', fakeOpenAi);
  app = await buildApp(
    { ...config, openaiKey: 'test-key', openaiModel: 'gpt-5.4-mini', clientDir: '__none__' },
    new Store(null),
  );
  const res = await app.inject({ method: 'POST', url: '/api/auth/mock-login', headers: json, payload: {} });
  cookie = String(res.headers['set-cookie']).split(';')[0] ?? '';
});
afterAll(async () => {
  vi.unstubAllGlobals();
  await app.close();
});

const post = async (url: string, payload: object = {}) =>
  (await app.inject({ method: 'POST', url, headers: { ...json, cookie }, payload })).json() as ChatState;

describe('AI 대화 보조(OpenAI)', () => {
  it('규칙으로 못 답한 질문은 AI 답으로, 출처는 AI 답변', async () => {
    const chat = await post('/api/chats');
    calls.length = 0;
    const after = await post(`/api/chats/${chat.id}/messages`, { text: '이사 첫 주에 뭐부터 하면 좋아?' });
    const last = after.messages.at(-1)!;
    expect(last.sources[0]?.kind).toBe('ai');
    expect(last.text).toContain('전입신고');
    // 화면 규칙: 줄표·굵은 글씨 없음
    expect(last.text).not.toMatch(/[—*]/);
    // 근거 자료(설명 문서)를 함께 보냄
    const answerCall = calls.find((c) => !c.schema);
    expect(answerCall?.instructions).toContain('살구 설명 문서');
  });

  it('규칙이 못 뽑은 조건은 AI가 뽑고, 형식이 틀린 값은 버려요', async () => {
    const chat = await post('/api/chats');
    const after = await post(`/api/chats/${chat.id}/messages`, {
      text: '테헤란로 쪽 다니고 한 달에 오십 정도요',
    });
    expect(after.conditions.workplace).toMatchObject({ value: 'yeoksam', source: 'said' });
    expect(after.conditions.rent).toMatchObject({ value: 50, source: 'said' });
    expect(after.conditions.parking).toBeUndefined();
  });

  it('숫자를 내는 집 찾기 흐름은 AI를 부르지 않아요', async () => {
    const chat = await post('/api/chats');
    calls.length = 0;
    await post(`/api/chats/${chat.id}/messages`, { text: '환산월세가 뭐야?' });
    expect(calls).toHaveLength(0);
  });
});
