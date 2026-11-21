import { html, nothing } from 'lit-html';
import { logo } from '../icons.js';
import { boot, state } from '../store.js';
import { headerView } from './header.js';
import { chatView, closeFloating } from './chat.js';
import { loginView } from './login.js';
import { sideView, tabsView } from './side.js';
import { scheduleView } from './schedule.js';
import { mapView } from '../map/mapView.js';

function toastView() {
  const t = state.ui.toast;
  if (!t) return nothing;
  return html`<div
    class="toast ${t.tone}"
    role=${t.tone === 'error' ? 'alert' : 'status'}
    data-testid="toast"
  >
    ${t.text}
  </div>`;
}

export function appView() {
  if (state.boot === 'loading' && !state.session) {
    return html`<div class="splash" aria-busy="true">
      ${logo(48)}
      <p>살구를 여는 중</p>
    </div>`;
  }
  if (state.boot === 'error' && !state.session) {
    return html`<div class="splash">
      ${logo(48)}
      <p>살구를 열지 못했어요. 잠시 뒤에 다시 시도해 주세요.</p>
      <button class="btn-primary" @click=${boot}>다시 시도</button>
      ${toastView()}
    </div>`;
  }
  if (!state.session?.user) return html`${loginView()}${toastView()}`;
  const tab = state.ui.mobileTab;
  return html`<div class="shell tab-${tab} ${state.ui.panel ? 'with-side' : ''}" @click=${closeFloating}>
    ${headerView()}
    <div class="main">
      ${chatView()} ${sideView({ map: mapView, sched: scheduleView })}
      <section class="m-pane m-map" aria-label="지도">${tab === 'map' ? mapView() : nothing}</section>
      <section class="m-pane m-sched" aria-label="일정">
        ${tab === 'sched' ? scheduleView() : nothing}
      </section>
    </div>
    ${tabsView()} ${toastView()}
  </div>`;
}
