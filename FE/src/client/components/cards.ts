import { html, type TemplateResult } from 'lit-html';
import type { Card, Message } from '../../shared/types.js';

function conceptCard(c: Extract<Card, { kind: 'concept' }>) {
  return html`<article class="card concept">
    <h3>${c.title}</h3>
    ${c.body.slice(1).map((p) => html`<p>${p}</p>`)}
  </article>`;
}

/** 카드 종류별로 그려요. 지난 카드는 접거나 읽기 전용으로 보여요. */
export function renderCard(card: Card, _msg: Message): TemplateResult {
  switch (card.kind) {
    case 'concept':
      return conceptCard(card);
    default:
      return html`<article class="card"><p class="muted">이 카드는 준비 중이에요.</p></article>`;
  }
}
