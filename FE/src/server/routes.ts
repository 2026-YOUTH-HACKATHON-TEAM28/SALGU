import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Action, ChatState, ChatSummary, ScheduleItem, SessionInfo, User } from '../shared/types.js';
import { APP_VERSION } from '../shared/version.js';
import type { Config } from './config.js';
import { Store, type UserRecord } from './store.js';
import {
  DialogError,
  advance,
  aiContext,
  applyAgentTurn,
  deferSearch,
  showSearch,
  takeDeferredSearch,
  applyAiAnswer,
  userSays,
  handleAction,
  handleText,
  newChat,
  type Ctx,
} from './mock/dialog.js';
import { intentOf } from './mock/nlu.js';
import { maskPersonal } from '../shared/format.js';
import { Ai } from './ai.js';
import { ChatAgent, mapAgentCard, mapRecs } from './chatAgent.js';
import { PhoneAgent, acceptRealProposal, planRealVisits, startRealCalls, syncReal } from './phoneAgent.js';
import type { ChatRecord } from './store.js';
import { BeAuth } from './beAuth.js';
import { agentSearch, condQuestion, restoreAgentDongs } from './dongAgent.js';
import { searchDongs } from './mock/engine.js';
import { DONGS, STATIONS, WORKPLACES, dongById } from './mock/data.js';
import { VISIT_SLOTS } from './mock/sim.js';

const COOKIE = 'sg_sid';

declare module 'fastify' {
  interface FastifyRequest {
    user: UserRecord | null;
  }
}

function publicUser(u: UserRecord): User {
  return { id: u.id, name: u.name, kind: u.kind, photo: u.photo };
}

function summary(c: ChatState): ChatSummary {
  return { id: c.id, title: c.title, updatedAt: c.updatedAt, stage: c.stage };
}

const idParam = {
  type: 'object',
  required: ['id'],
  properties: { id: { type: 'string', minLength: 3, maxLength: 64, pattern: '^[A-Za-z0-9_-]+$' } },
} as const;

export async function registerRoutes(app: FastifyInstance, config: Config, store: Store): Promise<void> {
  const ai = new Ai({
    apiKey: config.openaiKey,
    model: config.openaiModel,
    timeoutMs: 20000,
    dailyCap: config.aiDailyCap,
  });
  const agent = new ChatAgent(config.chatAgentUrl);
  const be = new BeAuth(config.beUrl);
  be.register(app);
  const phone = new PhoneAgent(config.phoneAgentUrl, {
    mockScenario: config.phoneMockScenario,
    brokersPerDong: config.phoneBrokersPerDong,
    uniqueReg: config.phoneUniqueReg,
  });
  let phoneCheckedAt = 0;
  const phoneMode = async () => {
    if (!phone.enabled) return null;
    if (Date.now() - phoneCheckedAt > 30000) {
      phoneCheckedAt = Date.now();
      await phone.health();
    }
    return phone.lastMode;
  };
  // 실제 통화 결과는 대화를 읽을 때 전화 에이전트에서 가져와요(같은 대화는 1초에 한 번까지).
  const lastSync = new Map<string, number>();
  /* 동네 찾기는 대화 에이전트(실거래 추천 엔진)에 물어봐요. 못 받으면 예시 데이터로 */
  const finishSearch = async (rec: ChatRecord) => {
    const p = takeDeferredSearch(rec.state);
    if (!p) return;
    const turn = await agent.turn(rec.state.id, condQuestion(rec.state, WORKPLACES));
    const result = agentSearch(turn?.backend, p.exclude);
    if (result) {
      showSearch(rec.state, result, new Date(), p.lead, {
        source: turn?.backend?.source ?? '추천 엔진(실거래 DB)',
        notes: turn?.backend?.notes ?? [],
      });
    } else {
      showSearch(
        rec.state,
        searchDongs(rec.state.conditions, WORKPLACES, p.exclude),
        new Date(),
        `${p.lead ? `${p.lead} ` : ''}실거래 추천을 받지 못해 예시 데이터로 보여 드려요.`,
      );
    }
  };
  const sync = async (rec: ChatRecord) => {
    restoreAgentDongs(rec.state.search);
    if (!rec.internal.real || !phone.enabled) return;
    const t = Date.now();
    if (t - (lastSync.get(rec.state.id) ?? 0) < 1000) return;
    lastSync.set(rec.state.id, t);
    if (await syncReal(rec.state, rec.internal, phone, new Date())) store.markDirty();
  };
  // 에이전트가 맡는 말: 규칙이 흐름 명령으로 알아듣지 못한 자유로운 말
  const AGENT_INTENTS = new Set(['other', 'question', 'greeting', 'oneByOne']);
  app.decorateRequest('user', null);

  app.addHook('preHandler', async (req) => {
    const sid = req.cookies[COOKIE];
    const s = store.session(sid);
    req.user = s ? (store.user(s.userId) ?? null) : null;
  });

  const needUser = async (req: FastifyRequest, reply: FastifyReply) => {
    if (!req.user)
      return reply
        .code(401)
        .send({ error: 'login_required', message: '먼저 로그인하거나 둘러보기를 눌러 주세요.' });
  };

  const setSession = (reply: FastifyReply, req: FastifyRequest, userId: string) => {
    const old = req.cookies[COOKIE];
    if (old) store.deleteSession(old);
    const sid = store.createSession(userId);
    reply.setCookie(COOKIE, sid, {
      path: '/',
      httpOnly: true,
      sameSite: 'lax',
      secure: req.protocol === 'https',
      maxAge: 30 * 86400,
    });
  };

  const ctxFor = (user: UserRecord): Ctx => ({
    now: new Date(),
    scale: config.timeScale,
    useCalls: (n) => store.useCalls(user.id, n, new Date().toISOString().slice(0, 10)),
    useTestCalls: () => store.useTestCall(user.id, new Date().toISOString().slice(0, 10)),
  });

  const sendDialogError = (reply: FastifyReply, err: unknown) => {
    if (err instanceof DialogError) return reply.code(409).send({ error: err.code, message: err.message });
    throw err;
  };

  /* 세션 · 로그인 */

  app.get('/api/ai', async () => ({
    enabled: ai.enabled,
    model: ai.enabled ? ai.model : null,
    chatAgent: agent.enabled,
    phone: phone.enabled ? (phone.lastMode ?? 'unreachable') : null,
  }));

  app.get('/api/session', async (req, reply): Promise<SessionInfo> => {
    // BE 카카오 로그인을 마치고 돌아오면(JSESSIONID) 그 사용자를 화면 계정과 이어요.
    if (be.enabled && BeAuth.beCookie(req) && req.user?.kind !== 'kakao') {
      const u = await be.me(req);
      if (u) {
        const user = store.userByKakao(u.id, u.nickname ?? '');
        setSession(reply, req, user.id);
        req.user = user;
      }
    }
    return {
      user: req.user ? publicUser(req.user) : null,
      version: APP_VERSION,
      kakaoMapKey: config.kakaoMapKey,
      kakaoTalk: req.user?.kakaoTalk ?? false,
      phoneMode: await phoneMode(),
      kakaoLogin: be.enabled,
    };
  });

  // 카카오 로그인은 서버에 카카오 키가 생기면 /oauth2/authorization/kakao 로 바꿔요. 지금은 예시 계정.
  app.post('/api/auth/mock-login', async (req, reply) => {
    const user = store.createUser('mock', '예시 사용자');
    setSession(reply, req, user.id);
    return { user: publicUser(user) };
  });

  app.post('/api/auth/guest', async (req, reply) => {
    const user = store.createUser('guest', '둘러보는 중');
    setSession(reply, req, user.id);
    return { user: publicUser(user) };
  });

  app.post('/api/auth/logout', async (req, reply) => {
    const sid = req.cookies[COOKIE];
    if (sid) store.deleteSession(sid);
    reply.clearCookie(COOKIE, { path: '/' });
    if (be.enabled) {
      await be.logout(req);
      reply.clearCookie('JSESSIONID', { path: '/' });
    }
    return { ok: true };
  });

  /* 화면에 필요한 기준 데이터 */

  app.get('/api/meta', async (_req, reply) => {
    reply.header('Cache-Control', 'public, max-age=300');
    return {
      workplaces: WORKPLACES.map(({ id, name, lat, lng }) => ({ id, name, lat, lng })),
      visitSlots: VISIT_SLOTS.map(({ id, label }) => ({ id, label })),
      dongs: DONGS.map(({ id, name, gu, lat, lng }) => ({ id, name, gu, lat, lng })),
      stations: STATIONS,
    };
  });

  /* 대화 */

  app.get('/api/chats', { preHandler: needUser }, async (req) => {
    return { chats: store.chatsOf(req.user!.id).map((c) => summary(c.state)) };
  });

  app.post('/api/chats', { preHandler: needUser }, async (req, reply) => {
    const { state, internal } = newChat(new Date());
    store.putChat({ userId: req.user!.id, state, internal });
    return reply.code(201).send(state);
  });

  app.get<{ Params: { id: string }; Querystring: { rev?: string } }>(
    '/api/chats/:id',
    { preHandler: needUser, schema: { params: idParam } },
    async (req, reply) => {
      const rec = store.chat(req.params.id, req.user!.id);
      if (!rec) return reply.code(404).send({ error: 'not_found', message: '대화를 찾지 못했어요.' });
      await sync(rec);
      if (advance(rec.state, rec.internal, new Date())) store.markDirty();
      if (req.query.rev && Number(req.query.rev) === rec.state.rev) return reply.code(204).send();
      return rec.state;
    },
  );

  app.delete<{ Params: { id: string } }>(
    '/api/chats/:id',
    { preHandler: needUser, schema: { params: idParam } },
    async (req, reply) => {
      if (!store.deleteChat(req.params.id, req.user!.id)) return reply.code(404).send({ error: 'not_found' });
      return { ok: true };
    },
  );

  app.post<{ Params: { id: string }; Body: { text: string } }>(
    '/api/chats/:id/messages',
    {
      preHandler: needUser,
      config: { rateLimit: { max: 30, timeWindow: '1 minute' } },
      schema: {
        params: idParam,
        body: {
          type: 'object',
          required: ['text'],
          additionalProperties: false,
          properties: { text: { type: 'string', minLength: 1, maxLength: 500 } },
        },
      },
    },
    async (req, reply) => {
      const rec = store.chat(req.params.id, req.user!.id);
      if (!rec) return reply.code(404).send({ error: 'not_found', message: '대화를 찾지 못했어요.' });
      await sync(rec);
      advance(rec.state, rec.internal, new Date());
      const text = maskPersonal(req.body.text.trim());
      // 1) AI 폴더의 대화 에이전트가 있으면 자유로운 말은 에이전트가 이해해요.
      const intent = intentOf(text).kind;
      // 실제 통화 중인 대화에서 "미팅 잡아줘"는 전화 에이전트로 확정 통화를 걸어요.
      if (intent === 'plan' && rec.internal.real && phone.enabled) {
        try {
          userSays(rec.state, text, new Date());
          await planRealVisits(rec.state, rec.internal, phone, null, new Date());
        } catch (err) {
          rec.state.messages.pop();
          return sendDialogError(reply, err);
        }
        store.putChat(rec);
        return rec.state;
      }
      if (agent.enabled && AGENT_INTENTS.has(intent)) {
        const turn = await agent.turn(rec.state.id, text);
        const askingMore = turn?.intent === 'control' && /다른|더\s*보여|자세히|번째/.test(text);
        const generic = turn?.intent === 'question' && turn.via.startsWith('rules');
        if (turn && !askingMore && !(generic && ai.enabled)) {
          // 에이전트의 자체 검색 말풍선(예시 응답)은 빼고 첫 답(reply)만 써요. 동네 찾기는 이 서버가 해요.
          const reply = turn.messages?.find((m) => m.kind === 'reply')?.text ?? turn.reply;
          const items = mapRecs(turn.backend);
          applyAgentTurn(
            rec.state,
            text,
            { ...turn, reply },
            mapAgentCard(turn.card, WORKPLACES),
            new Date(),
            items.length
              ? {
                  items,
                  notes: turn.backend?.notes ?? [],
                  source: turn.backend?.source ?? '추천 엔진(실거래 DB)',
                }
              : null,
          );
          store.putChat(rec);
          return rec.state;
        }
      }
      // 2) 규칙이 의도를 모르는 말이면 AI가 먼저 조건을 뽑아 봐요.
      const aiValues =
        ai.enabled && intentOf(text).kind === 'other' ? await ai.extract(text, WORKPLACES) : {};
      let result;
      if (agent.enabled) deferSearch(rec.state);
      try {
        result = handleText(rec.state, rec.internal, text, { ...ctxFor(req.user!), aiValues });
      } catch (err) {
        takeDeferredSearch(rec.state);
        return sendDialogError(reply, err);
      }
      await finishSearch(rec);
      // 규칙으로 못 답한 질문은 AI가 답해요(실패하면 규칙 안내 그대로).
      if (result.askAi && ai.enabled) {
        const answer = await ai.answer(result.askAi.question, aiContext(rec.state));
        if (answer) applyAiAnswer(rec.state, result.askAi.messageId, answer, ai.model);
      }
      store.putChat(rec);
      return rec.state;
    },
  );

  app.post<{ Params: { id: string }; Body: Action }>(
    '/api/chats/:id/actions',
    {
      preHandler: needUser,
      config: { rateLimit: { max: 60, timeWindow: '1 minute' } },
      schema: {
        params: idParam,
        body: { type: 'object', required: ['type'], properties: { type: { type: 'string', maxLength: 32 } } },
      },
    },
    async (req, reply) => {
      const rec = store.chat(req.params.id, req.user!.id);
      if (!rec) return reply.code(404).send({ error: 'not_found', message: '대화를 찾지 못했어요.' });
      await sync(rec);
      advance(rec.state, rec.internal, new Date());
      const a = req.body;
      try {
        // 전화 에이전트가 있으면 문의·확정 통화는 실제 에이전트로(없으면 시뮬레이션)
        if (phone.enabled && a.type === 'startCalls') {
          userSays(rec.state, '이대로 전화하기', new Date());
          await phoneMode();
          try {
            await startRealCalls(rec.state, rec.internal, phone, {
              now: new Date(),
              useCalls: ctxFor(req.user!).useCalls,
            });
          } catch (err) {
            rec.state.messages.pop();
            throw err;
          }
        } else if (phone.enabled && rec.internal.real && a.type === 'planVisits') {
          userSays(rec.state, '고른 방으로 미팅 잡아줘', new Date());
          try {
            await planRealVisits(rec.state, rec.internal, phone, a.listingIds ?? null, new Date());
          } catch (err) {
            rec.state.messages.pop();
            throw err;
          }
        } else if (
          phone.enabled &&
          rec.internal.real?.visitRefs[(a as { visitId?: string }).visitId ?? ''] &&
          a.type === 'acceptProposal'
        ) {
          await acceptRealProposal(rec.state, rec.internal, phone, a.visitId, new Date());
        } else {
          if (agent.enabled) deferSearch(rec.state);
          handleAction(rec.state, rec.internal, a, ctxFor(req.user!));
          await finishSearch(rec);
        }
      } catch (err) {
        takeDeferredSearch(rec.state);
        return sendDialogError(reply, err);
      }
      store.putChat(rec);
      return rec.state;
    },
  );

  /* 일정 */

  app.get('/api/schedule', { preHandler: needUser }, async (req) => {
    const items: ScheduleItem[] = [];
    for (const rec of store.chatsOf(req.user!.id)) {
      await sync(rec);
      if (advance(rec.state, rec.internal, new Date())) store.markDirty();
      const c = rec.state;
      for (const v of c.visits) {
        if (v.status !== 'confirmed') continue;
        const listing = c.listings.find((l) => l.id === v.listingId);
        if (!listing) continue;
        const dong = dongById(listing.dongId);
        items.push({
          chatId: c.id,
          visit: v,
          listing,
          broker: c.brokers.find((b) => b.id === listing.brokerId) ?? null,
          dongName: dong?.name ?? '',
          station: dong?.station ?? '',
        });
      }
    }
    items.sort((a, b) => a.visit.at.localeCompare(b.visit.at));
    return { items };
  });

  /* 카카오톡 알림(시험 연결) */

  app.post<{ Body: { on: boolean } }>(
    '/api/notify/kakao',
    {
      preHandler: needUser,
      schema: { body: { type: 'object', required: ['on'], properties: { on: { type: 'boolean' } } } },
    },
    async (req, reply) => {
      if (req.user!.kind === 'guest') {
        return reply
          .code(403)
          .send({ error: 'login_required', message: '카카오톡 알림은 로그인한 뒤에 연결할 수 있어요.' });
      }
      req.user!.kakaoTalk = req.body.on;
      store.markDirty();
      return { kakaoTalk: req.user!.kakaoTalk };
    },
  );

  app.post(
    '/api/notify/test',
    { preHandler: needUser, config: { rateLimit: { max: 3, timeWindow: '1 minute' } } },
    async (req, reply) => {
      if (!req.user!.kakaoTalk)
        return reply.code(409).send({ error: 'not_connected', message: '카카오톡이 연결되어 있지 않아요.' });
      return { ok: true, simulated: true };
    },
  );
}
