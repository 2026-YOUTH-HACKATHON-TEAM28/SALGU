import { html, nothing, type TemplateResult } from 'lit-html';
import type { Card, CondItem, CondKey, Conditions } from '../../../shared/types.js';
import { COND_META, REQUIRED_CONDS } from '../../../shared/labels.js';
import { act, send, state, ui } from '../../store.js';
import { condFormView } from '../condForm.js';
import { condText } from '../prefs.js';

/** 그 자리에서 고칠 수 있는 조건: 값 칸, 단위, 한 번에 바뀌는 양 */
const INLINE: Partial<Record<CondKey, { unit: string; step: number; min: number; max: number }>> = {
  rent: { unit: '만 원', step: 5, min: 10, max: 300 },
  deposit: { unit: '만 원', step: 500, min: 0, max: 50000 },
  maxCommute: { unit: '분', step: 5, min: 10, max: 120 },
};

const PHONE_CHECK: CondKey[] = ['pet', 'parking'];

function latestCondCardId(): string | null {
  const msgs = state.chat?.messages ?? [];
  for (let i = msgs.length - 1; i >= 0; i--) {
    const c = msgs[i]?.cards.find((x) => x.kind === 'cond');
    if (c) return c.id;
  }
  return null;
}

function inlineEditor(key: CondKey, item: CondItem<unknown> | undefined): TemplateResult {
  const cfg = INLINE[key]!;
  const start = Number(item?.value ?? (key === 'deposit' ? 1000 : key === 'maxCommute' ? 40 : 60));
  const commit = async (form: HTMLFormElement) => {
    const input = form.elements.namedItem('v') as HTMLInputElement;
    const v = Number(input.value);
    if (!Number.isFinite(v) || v < cfg.min || v > cfg.max) {
      input.setCustomValidity(`${cfg.min}~${cfg.max} 사이로 적어 주세요.`);
      input.reportValidity();
      return;
    }
    if (await act({ type: 'setCond', key, value: v })) ui({ inlineEdit: null });
  };
  const bump = (e: Event, d: number) => {
    const input = (e.currentTarget as HTMLElement)
      .closest('form')
      ?.elements.namedItem('v') as HTMLInputElement;
    input.value = String(Math.min(cfg.max, Math.max(cfg.min, Number(input.value || start) + d)));
    input.setCustomValidity('');
  };
  return html`<form
    class="inline-edit"
    @submit=${(e: Event) => {
      e.preventDefault();
      void commit(e.currentTarget as HTMLFormElement);
    }}
    @keydown=${(e: KeyboardEvent) => e.key === 'Escape' && ui({ inlineEdit: null })}
    data-testid=${`inline-${key}`}
  >
    <button
      type="button"
      class="step"
      aria-label="${cfg.step} 내리기"
      @click=${(e: Event) => bump(e, -cfg.step)}
    >
      −
    </button>
    <input
      name="v"
      type="number"
      inputmode="numeric"
      min=${cfg.min}
      max=${cfg.max}
      step=${cfg.step}
      .value=${String(start)}
      aria-label="새 값(${cfg.unit})"
      autofocus
      @input=${(e: Event) => (e.currentTarget as HTMLInputElement).setCustomValidity('')}
    />
    <span class="unit">${cfg.unit}</span>
    <button
      type="button"
      class="step"
      aria-label="${cfg.step} 올리기"
      @click=${(e: Event) => bump(e, cfg.step)}
    >
      +
    </button>
    <button type="submit" class="btn-primary small">확인</button>
    <button type="button" class="btn-ghost small" @click=${() => ui({ inlineEdit: null })}>취소</button>
  </form>`;
}

function row(key: CondKey, item: CondItem<unknown> | undefined, editable: boolean): TemplateResult {
  const meta = COND_META.find((m) => m.key === key)!;
  const missing = !item && REQUIRED_CONDS.includes(key);
  const canInline = editable && key in INLINE;
  const editing = canInline && state.ui.inlineEdit === key;
  const value = missing
    ? html`<span class="need">필요</span>`
    : editing
      ? inlineEditor(key, item)
      : canInline
        ? html`<button class="value-btn" @click=${() => ui({ inlineEdit: key })} data-testid=${`edit-${key}`}>
            <span class="money">${condText(key, item?.value)}</span><span class="edit-hint">바꾸기</span>
          </button>`
        : html`<span>${condText(key, item?.value)}</span>`;
  const guess = item && item.source !== 'said';
  return html`<li class="cond-row ${guess ? 'guess' : ''}" data-testid=${`cond-${key}`}>
    <span class="cond-k">${meta.label}</span>
    <div class="cond-v">
      ${value}
      ${PHONE_CHECK.includes(key) && item?.value === true ? html`<span class="note">전화로 확인</span>` : nothing}
      ${
        guess
          ? html`<p class="why">
              ${
                item.source === 'widened'
                  ? html`넓혀본 값 · 원래 ${condText(key, item.original)}
                    ${
                      editable
                        ? html`<button
                            class="link"
                            @click=${() => act({ type: 'resetCond', key })}
                            data-testid=${`reset-${key}`}
                          >
                            원래대로
                          </button>`
                        : nothing
                    }`
                  : html`살구가 채운 값 · ${item.reason}`
              }
            </p>`
          : nothing
      }
    </div>
  </li>`;
}

/** S-02 조건 카드: 중요한 것(회사·출퇴근·월세·보증금) 먼저, 나머지는 펼쳐 보기.
 *  '말씀하신 조건'과 '살구가 정한 조건(채운 값·넓혀본 값)'을 나눠 보여요. */
export function condCard(card: Extract<Card, { kind: 'cond' }>): TemplateResult {
  const conds: Conditions = state.chat?.conditions ?? {};
  const latest = latestCondCardId() === card.id;
  if (!latest) {
    return html`<article class="card folded">
      조건을 정리했어요. 바꾼 조건은 아래 최신 카드와 '내 조건'에 있어요.
    </article>`;
  }
  const all = COND_META.map((m) => ({ ...m, item: conds[m.key] as CondItem<unknown> | undefined }));
  const said = all.filter((m) => m.item?.source === 'said' || (!m.item && REQUIRED_CONDS.includes(m.key)));
  const saidPrimary = said.filter((m) => m.primary);
  const saidMore = said.filter((m) => !m.primary);
  const guessed = all.filter((m) => m.item && m.item.source !== 'said');
  const missing = REQUIRED_CONDS.filter((k) => !conds[k]);
  const moreOpen = state.ui.condMore.has(card.id);
  const editing = state.ui.condEdit === card.id;
  const searched = Boolean(state.chat?.search);

  return html`<article class="card cond" data-testid="cond-card">
    <header class="card-title">
      <h3>조건 카드</h3>
      <span class="sub">말한 내용으로 채웠어요. 값을 누르면 바로 고칠 수 있어요</span>
    </header>
    <section aria-labelledby=${`${card.id}-said`}>
      <h4 id=${`${card.id}-said`}>말씀하신 조건</h4>
      <ul class="cond-list">
        ${saidPrimary.map((m) => row(m.key, m.item, true))}
      </ul>
      ${
        saidMore.length
          ? html`${
                moreOpen
                  ? html`<ul class="cond-list">
                      ${saidMore.map((m) => row(m.key, m.item, true))}
                    </ul>`
                  : nothing
              }
              <button
                class="link more"
                aria-expanded=${moreOpen}
                @click=${() =>
                  update(() =>
                    moreOpen ? state.ui.condMore.delete(card.id) : state.ui.condMore.add(card.id),
                  )}
                data-testid="cond-more"
              >
                ${moreOpen ? '접기' : `조건 ${saidMore.length}개 더 보기`}
              </button>`
          : nothing
      }
    </section>
    ${
      guessed.length
        ? html`<section class="guessed" aria-labelledby=${`${card.id}-guess`}>
            <h4 id=${`${card.id}-guess`}>살구가 정한 조건</h4>
            <p class="note">
              말씀하지 않았거나 맞는 동네가 없어 살구가 정한 값이에요. 값을 누르면 바로 바꿀 수 있어요.
            </p>
            <ul class="cond-list">
              ${guessed.map((m) => row(m.key, m.item, true))}
            </ul>
          </section>`
        : nothing
    }
    ${
      card.ask
        ? html`<div class="ask" role="group" aria-label="되묻기">
            <p>${card.ask.question}</p>
            <div class="actions">
              ${card.ask.options.map((o) => html`<button class="btn-line small" @click=${() => send(o.text)}>${o.label}</button>`)}
            </div>
          </div>`
        : nothing
    }
    ${
      editing
        ? condFormView({ id: card.id, submitLabel: '이 조건으로 찾기', onDone: () => ui({ condEdit: null }) })
        : html`<div class="actions">
            <button
              class="btn-primary"
              ?disabled=${missing.length > 0 || state.pending}
              @click=${() => act({ type: 'search' })}
              data-testid="cond-search"
            >
              ${searched ? '이 조건으로 다시 찾기' : '이대로 찾기'}
            </button>
            <button class="btn-ghost" @click=${() => ui({ condEdit: card.id, inlineEdit: null })}>
              조건 고치기
            </button>
          </div>`
    }
  </article>`;
}

/** [조건 골라서 찾기] 양식 카드 */
export function condFormCard(card: Extract<Card, { kind: 'condForm' }>): TemplateResult {
  if (card.done) return html`<article class="card folded">채운 조건으로 찾았어요.</article>`;
  return html`<article class="card">
    ${condFormView({ id: card.id, submitLabel: '이 조건으로 찾기', autofocus: true })}
  </article>`;
}

function update(fn: () => void): void {
  fn();
  ui({});
}
