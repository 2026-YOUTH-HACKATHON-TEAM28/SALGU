/* 카카오톡 알림: 사용자가 카카오 화면에서 '카카오톡 메시지 전송(talk_message)'에 동의하면
 * 받은 토큰으로 본인 카카오톡에 '나에게 보내기'를 해요. 전화 에이전트의 알림(C6)은 아직 없어서 화면 서버가 보내요.
 * - 동의: GET /api/notify/kakao/connect -> 카카오 -> GET /api/notify/kakao/callback
 * - 보내기: POST https://kapi.kakao.com/v2/api/talk/memo/default/send (텍스트 200자, 만료면 갱신 한 번)
 * 앱 키(KAKAO_REST_API_KEY_NOTIFY = 알림 전용 카카오 앱의 REST API 키)는 서버 설정 파일에만 둬요.
 * 카카오 개발자 콘솔: Redirect URI 에 <사이트>/api/notify/kakao/callback, 동의 항목에 카카오톡 메시지 전송,
 * 플랫폼(Web) 사이트 도메인에 사이트 주소가 있어야 해요. */

export interface KakaoToken {
  access: string;
  refresh: string;
  /** 접근 토큰 만료 시각(ms) */
  expiresAt: number;
}

interface TokenResponse {
  access_token?: string;
  refresh_token?: string;
  expires_in?: number;
  error?: string;
  error_description?: string;
}

export class KakaoTalk {
  constructor(
    private readonly clientId: string,
    private readonly clientSecret: string,
  ) {}

  get enabled(): boolean {
    return Boolean(this.clientId);
  }

  authorizeUrl(redirectUri: string, state: string): string {
    const q = new URLSearchParams({
      client_id: this.clientId,
      redirect_uri: redirectUri,
      response_type: 'code',
      scope: 'talk_message',
      state,
    });
    return `https://kauth.kakao.com/oauth/authorize?${q}`;
  }

  private async token(params: Record<string, string>): Promise<TokenResponse> {
    const body = new URLSearchParams({
      client_id: this.clientId,
      ...(this.clientSecret ? { client_secret: this.clientSecret } : {}),
      ...params,
    });
    const res = await fetch('https://kauth.kakao.com/oauth/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=utf-8' },
      body,
      signal: AbortSignal.timeout(8000),
    });
    return (await res.json()) as TokenResponse;
  }

  /** 동의 뒤 받은 code 로 토큰을 받아요 */
  async exchange(code: string, redirectUri: string): Promise<KakaoToken | null> {
    try {
      const t = await this.token({ grant_type: 'authorization_code', redirect_uri: redirectUri, code });
      if (!t.access_token || !t.refresh_token) {
        console.error(`[kakao-talk] 토큰 받기 실패: ${t.error ?? 'unknown'}`);
        return null;
      }
      return {
        access: t.access_token,
        refresh: t.refresh_token,
        expiresAt: Date.now() + (t.expires_in ?? 0) * 1000,
      };
    } catch (err) {
      console.error(`[kakao-talk] 토큰 받기 실패: ${(err as Error).name}`);
      return null;
    }
  }

  private async refresh(tok: KakaoToken): Promise<KakaoToken | null> {
    try {
      const t = await this.token({ grant_type: 'refresh_token', refresh_token: tok.refresh });
      if (!t.access_token) return null;
      return {
        access: t.access_token,
        // 갱신 토큰은 만료가 가까울 때만 새로 와요
        refresh: t.refresh_token ?? tok.refresh,
        expiresAt: Date.now() + (t.expires_in ?? 0) * 1000,
      };
    } catch {
      return null;
    }
  }

  private async memo(access: string, text: string, link: string): Promise<number> {
    const template = {
      object_type: 'text',
      text: text.slice(0, 200),
      link: { web_url: link, mobile_web_url: link },
      button_title: '살구 열기',
    };
    const res = await fetch('https://kapi.kakao.com/v2/api/talk/memo/default/send', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${access}`,
        'Content-Type': 'application/x-www-form-urlencoded;charset=utf-8',
      },
      body: new URLSearchParams({ template_object: JSON.stringify(template) }),
      signal: AbortSignal.timeout(8000),
    });
    return res.status;
  }

  /** 나에게 보내기. 토큰이 바뀌면 newToken 으로 알려 줘요(저장은 부르는 쪽). 실패하면 ok:false */
  async send(
    tok: KakaoToken,
    text: string,
    link: string,
  ): Promise<{ ok: boolean; newToken?: KakaoToken; revoked?: boolean }> {
    let cur = tok;
    let renewed = false;
    try {
      if (cur.expiresAt - Date.now() < 60_000) {
        const r = await this.refresh(cur);
        if (!r) return { ok: false, revoked: true };
        cur = r;
        renewed = true;
      }
      let status = await this.memo(cur.access, text, link);
      if (status === 401 && !renewed) {
        const r = await this.refresh(cur);
        if (!r) return { ok: false, revoked: true };
        cur = r;
        renewed = true;
        status = await this.memo(cur.access, text, link);
      }
      if (status !== 200) console.error(`[kakao-talk] 보내기 응답 ${status}`);
      return { ok: status === 200, ...(renewed ? { newToken: cur } : {}) };
    } catch (err) {
      console.error(`[kakao-talk] 보내기 실패: ${(err as Error).name}`);
      return { ok: false, ...(renewed ? { newToken: cur } : {}) };
    }
  }
}
