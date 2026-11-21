import { html, type TemplateResult } from 'lit-html';
import type { Card, Message } from '../../shared/types.js';
import { condCard, condFormCard } from './cards/cond.js';
import { dongDetailCard, dongsCard, noMatchCard } from './cards/dongs.js';
import { callPrepCard, callsCard } from './cards/calls.js';
import { checksCard } from './cards/checks.js';

function conceptCard(c: Extract<Card, { kind: 'concept' }>) {
  return html`<article class="card concept">
    <h3>${c.title}</h3>
    ${c.body.slice(1).map((p) => html`<p>${p}</p>`)}
  </article>`;
}

/** 카드 종류별로 그려요. 지난 카드는 접거나 읽기 전용으로 보여요. */
export function renderCard(card: Card, _msg: Message): TemplateResult {
  switch (card.kind) {
    case 'cond':
      return condCard(card);
    case 'condForm':
      return condFormCard(card);
    case 'dongs':
      return dongsCard(card);
    case 'dongDetail':
      return dongDetailCard(card);
    case 'noMatch':
      return noMatchCard(card);
    case 'callPrep':
      return callPrepCard(card);
    case 'calls':
      return callsCard(card);
    case 'checks':
      return checksCard(card);
    case 'plan':
    case 'final':
      return html`<article class="card"><p class="muted">이 카드는 준비 중이에요.</p></article>`;
    case 'concept':
      return conceptCard(card);
  }
}
