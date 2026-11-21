import { existsSync } from 'node:fs';
import Fastify, { type FastifyError, type FastifyInstance } from 'fastify';
import helmet from '@fastify/helmet';
import fastifyStatic from '@fastify/static';
import cookie from '@fastify/cookie';
import rateLimit from '@fastify/rate-limit';
import type { Config } from './config.js';
import { APP_VERSION } from '../shared/version.js';
import { registerRoutes } from './routes.js';
import { Store } from './store.js';

/** 화면(정적 파일)과 /api 를 함께 내보내는 서버를 만들어요. 시험에서도 이 함수를 그대로 써요. */
export async function buildApp(config: Config, store = new Store(config.dataDir)): Promise<FastifyInstance> {
  const app = Fastify({
    trustProxy: config.trustProxy,
    bodyLimit: 64 * 1024,
    logger: {
      level: process.env.LOG_LEVEL || (config.isProd ? 'info' : 'warn'),
      redact: ['req.headers.cookie', 'req.headers.authorization'],
    },
  });

  await app.register(helmet, {
    contentSecurityPolicy: {
      useDefaults: true,
      directives: {
        'script-src': ["'self'", 'https://dapi.kakao.com', 'https://*.daumcdn.net'],
        'img-src': [
          "'self'",
          'data:',
          'https://*.tile.openstreetmap.org',
          'https://*.daumcdn.net',
          'https://*.kakao.com',
        ],
        'connect-src': ["'self'", 'https://dapi.kakao.com'],
        'style-src': ["'self'", "'unsafe-inline'"],
        'upgrade-insecure-requests': null,
      },
    },
    crossOriginEmbedderPolicy: false,
    // 지도 타일 서버(OpenStreetMap)는 출처(Referer)가 없는 요청을 막아요(403). 주소 경로는 빼고 도메인만 보내요.
    referrerPolicy: { policy: 'strict-origin-when-cross-origin' },
  });

  await app.register(cookie);
  await app.register(rateLimit, { global: true, max: 300, timeWindow: '1 minute' });

  // 다른 사이트에서 보낸 쓰기 요청 막기: JSON 본문만 받고, Origin 이 있으면 같은 호스트여야 해요.
  app.addHook('onRequest', async (req, reply) => {
    if (req.method === 'GET' || req.method === 'HEAD' || !req.url.startsWith('/api/')) return;
    const origin = req.headers.origin;
    if (origin) {
      let host = '';
      try {
        host = new URL(origin).host;
      } catch {
        host = '';
      }
      if (host !== req.headers.host && host !== req.headers['x-forwarded-host']) {
        return reply.code(403).send({ error: 'bad_origin', message: '허용되지 않은 요청이에요.' });
      }
    }
    const hasBody =
      Number(req.headers['content-length'] ?? 0) > 0 || Boolean(req.headers['transfer-encoding']);
    if (hasBody && !(req.headers['content-type'] ?? '').startsWith('application/json')) {
      return reply.code(415).send({ error: 'json_only' });
    }
  });

  app.addHook('onClose', async () => store.close());

  app.setErrorHandler((err: FastifyError, req, reply) => {
    const status = err.statusCode ?? 500;
    if (status >= 500) req.log.error(err);
    const message =
      status === 429
        ? '요청이 너무 많아요. 잠시 뒤에 다시 시도해 주세요.'
        : status >= 500
          ? '잠시 문제가 생겼어요. 다시 시도해 주세요.'
          : '요청 내용을 확인해 주세요.';
    return reply.code(status).send({ error: err.code ?? 'error', message });
  });

  app.get('/api/health', async () => ({ ok: true, version: APP_VERSION }));
  await registerRoutes(app, config, store);

  if (existsSync(config.clientDir)) {
    await app.register(fastifyStatic, {
      root: config.clientDir,
      wildcard: false,
      // 해시가 붙은 파일은 오래 캐시하고, index.html 은 매번 확인해요.
      setHeaders(res, path) {
        if (/[\\/]assets[\\/]/.test(path)) res.header('Cache-Control', 'public, max-age=31536000, immutable');
        else res.header('Cache-Control', 'no-cache');
      },
    });
    app.setNotFoundHandler((req, reply) => {
      if (req.url.startsWith('/api/')) return reply.code(404).send({ error: 'not_found' });
      return reply.type('text/html').header('Cache-Control', 'no-cache').sendFile('index.html');
    });
  }

  return app;
}
