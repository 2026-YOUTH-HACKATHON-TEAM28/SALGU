import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Action, ChatState, ChatSummary, ScheduleItem, SessionInfo, User } from '../shared/types.js';
import { APP_VERSION } from '../shared/version.js';
import type { Config } from './config.js';
import { Store, type UserRecord } from './store.js';
import { DialogError, advance, handleAction, handleText, newChat, type Ctx } from './mock/dialog.js';
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
  });

  const sendDialogError = (reply: FastifyReply, err: unknown) => {
    if (err instanceof DialogError) return reply.code(409).send({ error: err.code, message: err.message });
    throw err;
  };

  /* 세션 · 로그인 */

  app.get('/api/session', async (req): Promise<SessionInfo> => ({
    user: req.user ? publicUser(req.user) : null,
    version: APP_VERSION,
    kakaoMapKey: config.kakaoMapKey,
    kakaoTalk: req.user?.kakaoTalk ?? false,
  }));

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
      advance(rec.state, rec.internal, new Date());
      try {
        handleText(rec.state, rec.internal, req.body.text, ctxFor(req.user!));
      } catch (err) {
        return sendDialogError(reply, err);
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
      advance(rec.state, rec.internal, new Date());
      try {
        handleAction(rec.state, rec.internal, req.body, ctxFor(req.user!));
      } catch (err) {
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
