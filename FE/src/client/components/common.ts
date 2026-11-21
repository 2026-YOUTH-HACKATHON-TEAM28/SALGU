import { html, nothing, type TemplateResult } from 'lit-html';
import type { StatusLabel } from '../../shared/labels.js';
import { SOURCE_KIND_LABEL } from '../../shared/labels.js';
import type { SourceTag } from '../../shared/types.js';

/** 색 점 + 글자 상태 표시(이모지 대신) */
export function badge(l: StatusLabel, opts: { live?: boolean; testid?: string } = {}): TemplateResult {
  return html`<span class="badge tone-${l.tone}" data-testid=${opts.testid ?? nothing}
    ><span class="dot ${opts.live ? 'live' : ''}" aria-hidden="true"></span>${l.text}</span
  >`;
}

export function sources(list: SourceTag[]): TemplateResult | typeof nothing {
  if (!list.length) return nothing;
  return html`<p class="sources">
    출처 ·
    ${list.map(
      (s, i) =>
        html`${i ? ' · ' : ''}${s.label}
          <span class="src-kind src-${s.kind}">${SOURCE_KIND_LABEL[s.kind]}</span>`,
    )}
  </p>`;
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
