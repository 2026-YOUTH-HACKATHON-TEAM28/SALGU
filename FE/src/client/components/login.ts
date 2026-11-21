import { html } from 'lit-html';
import { kakaoSymbol, logo } from '../icons.js';
import { login, state } from '../store.js';

/** S-00 로그인 */
export function loginView() {
  const busy = state.boot === 'loading';
  return html`<main class="login" aria-labelledby="login-title">
    <div class="login-box">
      <div class="login-logo">${logo(56)}</div>
      <h1 id="login-title">살구 <span>살 집 구하기</span></h1>
      <p class="login-lead">
        회사 위치랑 예산만 알려 주시면, 동네 고르는 것부터 집 보러 가는 약속까지 같이 챙겨요.
      </p>
      <button class="btn-kakao" ?disabled=${busy} @click=${() => login('mock')} data-testid="login-kakao">
        ${kakaoSymbol}<span>카카오로 시작하기</span>
      </button>
      <button
        class="btn-ghost wide"
        ?disabled=${busy}
        @click=${() => login('guest')}
        data-testid="login-guest"
      >
        로그인 없이 둘러보기
      </button>
      <ul class="login-notes">
        <li>로그인하면 대화와 방문 일정을 이어서 볼 수 있어요.</li>
        <li>카카오에서는 닉네임과 프로필 사진만 받아요.</li>
        <li>지금은 카카오 연결 전이라 예시 계정으로 들어가요.</li>
      </ul>
    </div>
  </main>`;
}
