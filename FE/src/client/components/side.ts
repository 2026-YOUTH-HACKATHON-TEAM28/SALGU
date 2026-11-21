import { html, nothing } from 'lit-html';
import { icons } from '../icons.js';
import { state, ui } from '../store.js';

/** PC 옆 칸: [지도] [일정] 탭 · 닫기 */
export function sideView(content: { map: () => unknown; sched: () => unknown }) {
  const panel = state.ui.panel;
  if (!panel) return nothing;
  return html`<aside class="side" aria-label=${panel === 'map' ? '지도' : '일정'} data-testid="side">
    <div class="side-tabs" role="tablist">
      <button role="tab" aria-selected=${panel === 'map'} @click=${() => ui({ panel: 'map', mapDot: false })}>
        ${icons.map(18)}지도
      </button>
      <button role="tab" aria-selected=${panel === 'sched'} @click=${() => ui({ panel: 'sched' })}>
        ${icons.calendar(18)}일정${state.schedule.length ? html`<i class="count">${state.schedule.length}</i>` : nothing}
      </button>
      <button class="icon-btn side-close" aria-label="옆 칸 닫기" @click=${() => ui({ panel: null })}>
        ${icons.close()}
      </button>
    </div>
    <div class="side-body">${panel === 'map' ? content.map() : content.sched()}</div>
  </aside>`;
}

/** 모바일 하단 탭: 집 찾기 · 지도 · 일정 */
export function tabsView() {
  const t = state.ui.mobileTab;
  return html`<nav class="tabs" aria-label="화면 전환">
    <button
      aria-current=${t === 'chat' ? 'page' : nothing}
      @click=${() => ui({ mobileTab: 'chat' })}
      data-testid="tab-chat"
    >
      ${icons.home()}<span>집 찾기</span>
    </button>
    <button
      aria-current=${t === 'map' ? 'page' : nothing}
      @click=${() => ui({ mobileTab: 'map', mapDot: false })}
      data-testid="tab-map"
    >
      ${icons.map()}<span>지도</span>${state.ui.mapDot ? html`<i class="tab-dot" aria-label="새 지도 표시"></i>` : nothing}
    </button>
    <button
      aria-current=${t === 'sched' ? 'page' : nothing}
      @click=${() => ui({ mobileTab: 'sched' })}
      data-testid="tab-sched"
    >
      ${icons.calendar()}<span>일정</span>
    </button>
  </nav>`;
}
