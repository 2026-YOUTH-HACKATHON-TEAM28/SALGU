/* BE(Spring Boot) 카카오 로그인 연결.
 * BE 는 세션 쿠키(JSESSIONID) 방식이고 CORS 가 없어서, 화면 서버가 같은 주소에서 로그인 경로를 BE 로 넘겨요.
 *  - GET /oauth2/authorization/kakao  -> BE (카카오로 보내기)
 *  - GET /login/oauth2/code/kakao     -> BE (콜백, 사용자 저장 후 app.frontend-url 로 돌려보냄)
 *  - GET /api/me (BE)                  -> 이 서버가 JSESSIONID 를 들고 물어봐서 화면 계정(sg_sid)과 이어요
 * BE 의 app.frontend-url 은 이 사이트 주소(예: https://sample.localhostbar.com/)로 띄워 주세요. */
import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';

export const BE_LOGIN_PATHS = ['/oauth2/authorization/kakao', '/login/oauth2/code/kakao'] as const;

/** BE GET /api/me 응답(UserResponse): id 는 BE users.id, 로그인 안 했으면 401 */
export interface BeUser {
  id: number;
  nickname: string | null;
}

export class BeAuth {
  constructor(private readonly url: string) {}

  get enabled(): boolean {
    return Boolean(this.url);
  }

  private base(): string {
    return this.url.replace(/\/$/, '');
  }

  /** 브라우저 쿠키 중 BE 세션 쿠키만 넘겨요 */
  static beCookie(req: FastifyRequest): string {
    return (req.headers.cookie ?? '')
      .split(';')
      .map((c) => c.trim())
      .filter((c) => c.startsWith('JSESSIONID='))
      .join('; ');
  }

  private forwarded(req: FastifyRequest): Record<string, string> {
    const host = String(req.headers['x-forwarded-host'] ?? req.headers.host ?? '');
    const proto = req.protocol;
    return {
      'X-Forwarded-Host': host,
      'X-Forwarded-Proto': proto,
      'X-Forwarded-Port': host.includes(':') ? host.split(':')[1]! : proto === 'https' ? '443' : '80',
      ...(BeAuth.beCookie(req) ? { Cookie: BeAuth.beCookie(req) } : {}),
    };
  }

  /** 로그인 경로를 BE 로 그대로 넘기고, 돌려준 이동 주소와 쿠키를 브라우저에 전해요 */
  async proxy(req: FastifyRequest, reply: FastifyReply): Promise<FastifyReply> {
    let res: Response;
    try {
      res = await fetch(`${this.base()}${req.url}`, {
        method: 'GET',
        headers: this.forwarded(req),
        redirect: 'manual',
      });
    } catch {
      return reply.redirect('/?loginError=true');
    }
    const loc = res.headers.get('location');
    for (const c of res.headers.getSetCookie()) reply.header('set-cookie', c);
    if (loc) {
      // BE 주소로 돌아오는 이동은 이 사이트 주소로 바꿔요(밖으로 가는 카카오 주소는 그대로).
      const rel = loc.startsWith(this.base()) ? loc.slice(this.base().length) || '/' : loc;
      return reply
        .code(res.status >= 300 && res.status < 400 ? res.status : 302)
        .header('location', rel)
        .send();
    }
    return reply
      .code(res.status)
      .type(res.headers.get('content-type') ?? 'text/plain')
      .send(await res.text());
  }

  /** 브라우저의 JSESSIONID 로 BE 에 로그인한 사용자를 물어봐요. 로그인 안 했으면 null */
  async me(req: FastifyRequest): Promise<BeUser | null> {
    const cookie = BeAuth.beCookie(req);
    if (!cookie) return null;
    try {
      const res = await fetch(`${this.base()}/api/me`, {
        headers: { ...this.forwarded(req), Cookie: cookie },
      });
      if (res.status !== 200) return null;
      const u = (await res.json()) as BeUser;
      return typeof u.id === 'number' ? u : null;
    } catch {
      return null;
    }
  }

  async logout(req: FastifyRequest): Promise<void> {
    const cookie = BeAuth.beCookie(req);
    if (!cookie) return;
    try {
      await fetch(`${this.base()}/logout`, {
        method: 'POST',
        headers: { ...this.forwarded(req), Cookie: cookie },
      });
    } catch {
      /* 화면 계정은 그대로 로그아웃해요 */
    }
  }

  register(app: FastifyInstance): void {
    if (!this.enabled) return;
    for (const path of BE_LOGIN_PATHS) app.get(path, (req, reply) => this.proxy(req, reply));
  }
}
