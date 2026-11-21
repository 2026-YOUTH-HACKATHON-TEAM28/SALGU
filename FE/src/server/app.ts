import { existsSync } from 'node:fs';
import Fastify, { type FastifyInstance } from 'fastify';
import helmet from '@fastify/helmet';
import fastifyStatic from '@fastify/static';
import type { Config } from './config.js';
import { APP_VERSION } from '../shared/version.js';

/** 화면(정적 파일)과 /api 를 함께 내보내는 서버를 만들어요. 시험에서도 이 함수를 그대로 써요. */
export async function buildApp(config: Config): Promise<FastifyInstance> {
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
        'connect-src': ["'self'"],
        'style-src': ["'self'", "'unsafe-inline'"],
        'upgrade-insecure-requests': null,
      },
    },
    crossOriginEmbedderPolicy: false,
  });

  app.get('/api/health', async () => ({ ok: true, version: APP_VERSION }));

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
