import { html, nothing } from 'lit-html';
import { closeConfirm, state } from '../store.js';

let focusedFor: object | null = null;

/** 화면 안 확인 창. 되돌릴 수 없는 동작은 '취소'에 먼저 초점을 둬요. Esc·바깥 누르기는 취소 */
export function confirmView() {
  const c = state.ui.confirm;
  if (!c) {
    focusedFor = null;
    return nothing;
  }
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      closeConfirm(false);
    }
    if (e.key === 'Tab') {
      // 창 안에서만 초점이 돌게
      const btns = [...(e.currentTarget as HTMLElement).querySelectorAll<HTMLButtonElement>('button')];
      const i = btns.indexOf(document.activeElement as HTMLButtonElement);
      const next = e.shiftKey ? (i <= 0 ? btns.length - 1 : i - 1) : (i + 1) % btns.length;
      e.preventDefault();
      btns[next]?.focus();
    }
  };
  if (focusedFor !== c) {
    focusedFor = c;
    requestAnimationFrame(() =>
      document.querySelector<HTMLButtonElement>(c.danger ? '.confirm-cancel' : '.confirm-ok')?.focus(),
    );
  }
  return html`<div
    class="confirm-backdrop"
    @click=${(e: Event) => e.target === e.currentTarget && closeConfirm(false)}
  >
    <div
      class="confirm"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="confirm-title"
      aria-describedby=${c.body ? 'confirm-body' : nothing}
      @keydown=${onKey}
      data-testid="confirm"
    >
      <h2 id="confirm-title">${c.title}</h2>
      ${c.body ? html`<p id="confirm-body">${c.body}</p>` : nothing}
      <div class="confirm-actions">
        <button
          class="btn-ghost confirm-cancel"
          @click=${() => closeConfirm(false)}
          data-testid="confirm-cancel"
        >
          ${c.cancel ?? '취소'}
        </button>
        <button
          class="${c.danger ? 'btn-danger' : 'btn-primary'} confirm-ok"
          @click=${() => closeConfirm(true)}
          data-testid="confirm-ok"
        >
          ${c.ok}
        </button>
      </div>
    </div>
  </div>`;
}
