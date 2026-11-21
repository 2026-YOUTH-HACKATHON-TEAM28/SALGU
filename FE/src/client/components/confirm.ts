import { html, nothing } from 'lit-html';
import { closeConfirm, state } from '../store.js';
import { formatPhone } from '../../shared/format.js';

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
      const btns = [...(e.currentTarget as HTMLElement).querySelectorAll<HTMLElement>('input, button')];
      const i = btns.indexOf(document.activeElement as HTMLElement);
      const next = e.shiftKey ? (i <= 0 ? btns.length - 1 : i - 1) : (i + 1) % btns.length;
      e.preventDefault();
      btns[next]?.focus();
    }
  };
  if (focusedFor !== c) {
    focusedFor = c;
    requestAnimationFrame(() =>
      document
        .querySelector<HTMLElement>(c.phone ? '#confirm-phone' : c.danger ? '.confirm-cancel' : '.confirm-ok')
        ?.focus(),
    );
  }
  const submit = () => {
    if (!c.phone) return closeConfirm(true);
    const el = document.querySelector<HTMLInputElement>('#confirm-phone');
    const digits = (el?.value ?? '').replace(/\D/g, '');
    if (!/^01[016789]\d{7,8}$/.test(digits)) {
      el?.setCustomValidity('휴대폰 번호를 010-1234-5678처럼 적어 주세요.');
      el?.reportValidity();
      return;
    }
    closeConfirm(true, digits);
  };
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
      ${
        c.phone
          ? html`<label class="confirm-field" for="confirm-phone">
              <span>내 휴대폰 번호</span>
              <input
                id="confirm-phone"
                type="tel"
                inputmode="numeric"
                autocomplete="tel"
                maxlength="13"
                placeholder="010-1234-5678"
                @input=${(e: Event) => {
                  const el = e.currentTarget as HTMLInputElement;
                  el.setCustomValidity('');
                  el.value = formatPhone(el.value);
                }}
                @keydown=${(e: KeyboardEvent) => e.key === 'Enter' && (e.preventDefault(), submit())}
                data-testid="confirm-phone"
              />
            </label>`
          : nothing
      }
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
          @click=${submit}
          data-testid="confirm-ok"
        >
          ${c.ok}
        </button>
      </div>
    </div>
  </div>`;
}
