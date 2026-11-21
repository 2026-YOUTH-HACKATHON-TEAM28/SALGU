import { html, nothing, type TemplateResult } from 'lit-html';
import type { Card } from '../../../shared/types.js';

const TYPE: Record<string, string> = { villa: '빌라', officetel: '오피스텔' };

/** 추천 엔진(실거래 DB) 후보. 과거 계약 기록이라 지금 나온 방이 아니에요. */
export function recsCard(card: Extract<Card, { kind: 'recs' }>): TemplateResult {
  return html`<article class="card recs" data-testid="recs-card">
    <header class="card-title">
      <h3>실거래 기준 추천</h3>
      <span class="sub">${card.source} · 최근 12개월 계약 기록</span>
    </header>
    <ol class="rec-list">
      ${card.items.map(
        (r, i) =>
          html`<li class="rec">
            <div class="rec-head">
              <span class="lno">${i + 1}</span>
              <div class="rec-title">
                <strong>${r.name}</strong>
                <span class="muted">${r.address ?? ''}</span>
              </div>
              ${r.score !== null ? html`<span class="score">점수 ${Math.round(r.score)}</span>` : nothing}
            </div>
            <p class="rec-price">
              <span class="money">${r.deposit ?? '-'}/${r.rent ?? '-'}</span>
              <span class="muted"
                >보증금/월세(만 원) ·
                ${TYPE[r.housingType ?? ''] ?? r.housingType ?? '유형 모름'}${
                  r.area !== null ? ` ${r.area}㎡` : ''
                }${r.floor !== null ? ` · ${r.floor}층` : ''}${r.built !== null ? ` · ${r.built}년 준공` : ''}</span
              >
            </p>
            ${
              r.reasons.length
                ? html`<ul class="ticks">
                    ${r.reasons.map((x) => html`<li>${x}</li>`)}
                  </ul>`
                : nothing
            }
          </li>`,
      )}
    </ol>
    ${
      card.notes.length
        ? html`<ul class="reasons">
            ${card.notes.map((n) => html`<li>${n}</li>`)}
          </ul>`
        : nothing
    }
    <p class="foot-note">
      과거 실거래 기록이라 지금 계약할 수 있는 방은 아니에요. 동네를 고르면 중개사무소에 전화해서 비슷한 방이
      있는지 물어볼게요.
    </p>
  </article>`;
}
