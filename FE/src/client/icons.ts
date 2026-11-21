import { html, svg, type TemplateResult } from 'lit-html';

/* 직접 그린 선 아이콘. 헤더 버튼, 모바일 탭, 지도 회사 핀에만 써요. */

const wrap = (body: TemplateResult, size = 20) =>
  html`<svg
    class="icon"
    width=${size}
    height=${size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.8"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    ${body}
  </svg>`;

export const icons = {
  calendar: (s?: number) =>
    wrap(svg`<rect x="3.5" y="5" width="17" height="15" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/>`, s),
  map: (s?: number) =>
    wrap(svg`<path d="M9 4 3.5 6v14L9 18l6 2 5.5-2V4L15 6 9 4z"/><path d="M9 4v14M15 6v14"/>`, s),
  chats: (s?: number) => wrap(svg`<path d="M4 5h16v10H9l-5 4V5z"/><path d="M8 9h8M8 12h5"/>`, s),
  plus: (s?: number) => wrap(svg`<path d="M12 5v14M5 12h14"/>`, s),
  person: (s?: number) =>
    wrap(svg`<circle cx="12" cy="8.5" r="3.5"/><path d="M5 20c1.2-3.6 3.8-5.5 7-5.5s5.8 1.9 7 5.5"/>`, s),
  home: (s?: number) =>
    wrap(svg`<path d="M4 11 12 4l8 7"/><path d="M6 9.5V20h12V9.5"/><path d="M10 20v-5h4v5"/>`, s),
  send: (s?: number) => wrap(svg`<path d="M4 12 20 4l-6 16-3-7-7-1z"/>`, s),
  close: (s?: number) => wrap(svg`<path d="M6 6l12 12M18 6 6 18"/>`, s),
  chevron: (s?: number) => wrap(svg`<path d="m8 10 4 4 4-4"/>`, s),
  trash: (s?: number) => wrap(svg`<path d="M5 7h14M10 7V5h4v2M7 7l1 13h8l1-13"/>`, s),
  building: (s?: number) =>
    wrap(
      svg`<rect x="5" y="3.5" width="14" height="17" rx="1.5"/><path d="M9 8h2M13 8h2M9 12h2M13 12h2M10.5 20.5v-4h3v4"/>`,
      s,
    ),
};

/** 살구 로고(색 있음) */
export const logo = (size = 28) =>
  html`<svg width=${size} height=${size} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
    <circle cx="16" cy="18" r="12" fill="var(--apricot)" />
    <path
      d="M16 6c0-2 1.5-4 4-4"
      stroke="var(--leaf-dark)"
      stroke-width="2"
      fill="none"
      stroke-linecap="round"
    />
    <path d="M17 6c3-3 7-2 8 0-3 2-6 2-8 0z" fill="var(--leaf)" />
  </svg>`;

/** 카카오 로그인 버튼의 말풍선 심볼 */
export const kakaoSymbol = html`<svg
  width="18"
  height="18"
  viewBox="0 0 24 24"
  aria-hidden="true"
  focusable="false"
>
  <path
    fill="#000"
    d="M12 3.5c-5 0-9 3.1-9 7 0 2.5 1.7 4.7 4.2 6l-1 3.7c-.1.3.3.6.6.4l4.4-2.9c.3 0 .5.1.8.1 5 0 9-3.1 9-7s-4-7.3-9-7.3z"
  />
</svg>`;
