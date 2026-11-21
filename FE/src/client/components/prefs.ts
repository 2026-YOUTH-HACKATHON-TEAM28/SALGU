import { html, nothing } from 'lit-html';
import type { CondItem, CondKey } from '../../shared/types.js';
import { COND_META } from '../../shared/labels.js';
import { condValueText } from '../../shared/format.js';
import { state, ui } from '../store.js';
import { condFormView } from './condForm.js';

export function condText(key: CondKey, value: unknown): string {
  return condValueText(
    key,
    value,
    (state.meta?.workplaces ?? []).map((w) => ({ ...w, alias: [], lines: [] })),
  );
}

/** 입력창 위 '내 조건' 상자. 말한 조건은 실선, 살구가 정한 조건은 점선(마우스를 올리면 이유) */
export function prefsView() {
  const conds = state.chat?.conditions ?? {};
  const items = COND_META.map((m) => ({
    meta: m,
    item: conds[m.key] as CondItem<unknown> | undefined,
  })).filter((x): x is { meta: (typeof COND_META)[number]; item: CondItem<unknown> } => Boolean(x.item));
  if (!items.length && !state.ui.prefsForm) return nothing;
  // 중요한 항목(회사·출퇴근·월세·보증금)을 먼저
  items.sort((a, b) => Number(b.meta.primary) - Number(a.meta.primary));
  return html`<div class="prefs ${state.ui.prefsExpanded ? 'open' : ''}" data-testid="prefs">
    ${
      state.ui.prefsForm
        ? html`<div class="prefs-form">
            <h3>조건 바꾸기</h3>
            ${condFormView({ id: 'pf', submitLabel: '이 조건으로 찾기', onDone: () => ui({ prefsForm: false }), autofocus: true })}
          </div>`
        : nothing
    }
    <div class="prefs-head">
      <span class="prefs-title">내 조건</span>
      <button
        class="btn-pill"
        @click=${() => ui({ prefsForm: !state.ui.prefsForm })}
        data-testid="prefs-edit"
      >
        조건 바꾸기
      </button>
    </div>
    <div class="prefs-row">
      <ul class="prefs-items">
        ${items.map(
          ({ meta, item }) =>
            html`<li
              class="pref ${item.source === 'said' ? 'said' : 'guess'}"
              title=${
                item.source === 'said'
                  ? '말씀하신 조건'
                  : `${item.source === 'widened' ? '넓혀본 값' : '살구가 채운 값'}: ${item.reason ?? ''}`
              }
            >
              <span class="k">${meta.label}</span> <b>${condText(meta.key, item.value)}</b>
            </li>`,
        )}
      </ul>
      <button
        class="link prefs-all"
        @click=${() => ui({ prefsExpanded: !state.ui.prefsExpanded })}
        aria-expanded=${state.ui.prefsExpanded}
      >
        ${state.ui.prefsExpanded ? '접기' : '전체 보기'}
      </button>
    </div>
  </div>`;
}
