import { html, nothing, type TemplateResult } from 'lit-html';
import type { Card, Listing } from '../../../shared/types.js';
import { PRICE_LABEL } from '../../../shared/labels.js';
import { dateTime, depRent } from '../../../shared/format.js';
import { act, state } from '../../store.js';
import { brokerOf, listingCard } from './listing.js';
import { miniMap } from './minimap.js';

function roomBody(l: Listing): TemplateResult {
  const b = brokerOf(l);
  return html`<p class="info-line">
    ${b?.name ?? ''} · 등록 ${b?.regNo ?? ''} · 입주 ${l.moveIn} ·
    ${l.slots.length ? `보여 줄 수 있는 시간 ${l.slots.map(dateTime).join(', ')}` : '보여 줄 시간은 확정 전화로 물어봐요'}
  </p>`;
}

/** 찾은 방: 통화로 들은 방에서 미팅 잡을 방을 골라요 */
export function roomsCard(_card: Extract<Card, { kind: 'rooms' }>): TemplateResult {
  const chat = state.chat;
  const ids = new Set(chat?.batch?.calls.map((c) => c.id));
  const listings = (chat?.listings ?? []).filter((l) => ids.has(l.callId));
  if (!chat || !listings.length) return html`<article class="card folded">통화로 들은 방이 없어요.</article>`;
  const picked = new Set(chat.selectedListingIds);
  const planning = chat.visits.some((v) => v.status === 'requesting');
  const n = listings.filter((l) => picked.has(l.id)).length;
  const order = ['fair', 'unknown', 'slightly_high', 'high'];
  const sorted = [...listings].sort(
    (a, b) => order.indexOf(a.priceVerdict) - order.indexOf(b.priceVerdict) || a.no - b.no,
  );
  return html`<article class="card rooms" data-testid="rooms-card">
    <header class="card-title">
      <h3>찾은 방</h3>
      <span class="sub">통화로 들은 방 ${listings.length}개 · 미팅 잡을 방을 골라 주세요</span>
    </header>
    ${miniMap(
      sorted.map((l) => ({
        lat: l.lat,
        lng: l.lng,
        label: `${PRICE_LABEL[l.priceVerdict].text} · ${depRent(l.deposit, l.rent)}`,
        kind: 'listing' as const,
        tone: PRICE_LABEL[l.priceVerdict].tone,
        sub: String(l.no),
      })),
      { mode: 'listing', caption: `통화로 찾은 방 ${listings.length}개` },
    )}
    <div class="listing-list">
      ${sorted.map((l) =>
        listingCard(l, roomBody(l), {
          lead: html`<input
            type="checkbox"
            class="pick"
            aria-label="${l.no}번 ${l.building} 고르기"
            .checked=${picked.has(l.id)}
            ?disabled=${state.pending || planning}
            @change=${() => act({ type: 'toggleListing', listingId: l.id })}
            data-testid="pick-listing"
          />`,
        }),
      )}
    </div>
    <div class="card-foot">
      <button
        class="btn-primary"
        ?disabled=${n === 0 || state.pending || planning}
        @click=${() => act({ type: 'planVisits', listingIds: chat.selectedListingIds })}
        data-testid="plan-picked"
      >
        고른 방 ${n}곳 미팅 잡기
      </button>
      <span class="note">동선이 짧은 순서로 배치하고 중개사무소마다 다시 전화해 시간을 확정해요</span>
    </div>
    <p class="foot-note">
      가격은 같은 조건 과거 실거래와 비교한 예시 값이에요. 계약 전에 등기부등본과 건축물대장은 방문할 때 직접
      확인해 주세요.
    </p>
    ${planning ? html`<p class="note">확정 전화가 진행 중이에요.</p>` : nothing}
  </article>`;
}
